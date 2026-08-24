from __future__ import annotations

import hashlib
import json
import math
import os
import selectors
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "apps" / "candidate_runner" / "candidate_runner.py"
MUTATOR = ROOT / "apps" / "mutator" / "mutator.py"
OBSERVER = ROOT / "apps" / "observer" / "observer.py"


def encode(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def candidate_id(genome: dict[str, object]) -> str:
    document = {
        "genome": genome,
        "genome_schema": "flat-json-atoms-v1",
        "schema_version": 1,
    }
    return hashlib.sha256(encode(document).encode("ascii")).hexdigest()


def request_document(
    *,
    hypothesis: str = "v3",
    confidence: int = 5000,
    probe: dict[str, object] | None = None,
) -> dict[str, object]:
    genome = {
        "hypothesis": hypothesis,
        "hypothesis_probability_bps": confidence,
    }
    return {
        "candidate_id": candidate_id(genome),
        "genome": genome,
        "probe": probe
        or {"operation": "read", "path": "config/mode.txt"},
        "schema_version": 1,
    }


def run_runner(source: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        input=source,
        capture_output=True,
        text=True,
        check=False,
    )


def error_message(result: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)["error"]
    return error["code"], error["message"]


def test_candidate_runner_builds_a_normalized_probe_forecast():
    request = request_document()

    result = run_runner(encode(request))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    response = json.loads(result.stdout)
    assert result.stdout == encode(response) + "\n"
    assert response["candidate_id"] == request["candidate_id"]
    assert response["genome"] == request["genome"]
    assert response["probe"] == request["probe"]
    assert response["runner_model"] == "observer-fixture-hypothesis-v1"
    probabilities = {
        outcome["target"]: outcome["probability"]
        for outcome in response["forecast"]["outcomes"]
    }
    assert probabilities[encode({"kind": "text", "text": "fast\n"})] == pytest.approx(
        2 / 3
    )
    assert probabilities[encode({"kind": "text", "text": "safe\n"})] == pytest.approx(
        1 / 3
    )
    expected_entropy = -(2 / 3) * math.log2(2 / 3) - (1 / 3) * math.log2(1 / 3)
    assert response["forecast"]["entropy"]["value"] == pytest.approx(
        expected_entropy
    )


def test_candidate_runner_models_the_deterministic_listing_probe():
    request = request_document(probe={"operation": "list"})

    result = run_runner(encode(request))

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["forecast"]["outcomes"] == [
        {
            "probability": 1.0,
            "target": encode(
                {
                    "kind": "listing",
                    "paths": ["config/mode.txt", "service/port.txt"],
                }
            ),
        }
    ]
    assert response["forecast"]["entropy"]["value"] == 0.0


@pytest.mark.parametrize("version", ["v1", "v2", "v3", "v4"])
@pytest.mark.parametrize("path", ["config/mode.txt", "service/port.txt"])
def test_candidate_runner_model_matches_public_observer_results(version, path):
    probe = {"operation": "read", "path": path}
    runner = run_runner(
        encode(
            request_document(
                hypothesis=version,
                confidence=10000,
                probe=probe,
            )
        )
    )
    assert runner.returncode == 0, runner.stderr
    forecast = {
        outcome["target"]: outcome["probability"]
        for outcome in json.loads(runner.stdout)["forecast"]["outcomes"]
    }
    observer = subprocess.run(
        [sys.executable, str(OBSERVER), "--jsonl", "--active", version],
        cwd=ROOT,
        input=encode({"action": "observe", "probe": probe}) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert observer.returncode == 0, observer.stderr
    observed_target = encode(json.loads(observer.stdout)["observed_result"])

    assert forecast[observed_target] == 1.0


def test_candidate_runner_accepts_the_exact_mutator_candidate_identity():
    mutation_request = {
        "catalogue": {
            "loci": [
                {"alleles": ["v1", "v2", "v3", "v4"], "locus": "hypothesis"},
                {
                    "alleles": [2500, 5000, 7500],
                    "locus": "hypothesis_probability_bps",
                },
            ]
        },
        "draw": 0,
        "mutation_distribution": [
            {
                "allele": 7500,
                "locus": "hypothesis_probability_bps",
                "probability": 1,
            }
        ],
        "parent_genome": {
            "hypothesis": "v3",
            "hypothesis_probability_bps": 5000,
        },
        "schema_version": 1,
    }
    mutation = subprocess.run(
        [sys.executable, str(MUTATOR)],
        cwd=ROOT,
        input=encode(mutation_request),
        capture_output=True,
        text=True,
        check=False,
    )
    assert mutation.returncode == 0, mutation.stderr
    child = json.loads(mutation.stdout)["child"]
    request = {
        "candidate_id": child["candidate_id"],
        "genome": child["genome"],
        "probe": {"operation": "read", "path": "service/port.txt"},
        "schema_version": 1,
    }

    result = run_runner(encode(request))

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["candidate_id"] == child["candidate_id"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda request: request.update(schema_version=2), "schema_version"),
        (lambda request: request.update(candidate_id="0" * 64), "does not match"),
        (
            lambda request: request["genome"].update(hypothesis="v5"),
            "hypothesis must be one of",
        ),
        (
            lambda request: request["genome"].update(
                hypothesis_probability_bps=2499
            ),
            "must be between",
        ),
        (
            lambda request: request.update(
                probe={"operation": "read", "path": "secret.txt"}
            ),
            "probe.path must be one of",
        ),
    ],
)
def test_candidate_runner_rejects_invalid_bindings_and_models(change, message):
    request = request_document()
    change(request)

    result = run_runner(encode(request))

    code, detail = error_message(result)
    assert code == "invalid_request"
    assert message in detail


def test_candidate_runner_jsonl_returns_errors_and_continues():
    valid = encode(request_document())
    source = "\n".join(("{", valid, ""))

    result = run_runner(source, "--jsonl")

    assert result.returncode == 0
    assert result.stderr == ""
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]["error"]["code"] == "invalid_request"
    assert responses[1]["candidate_id"] == request_document()["candidate_id"]


def test_candidate_runner_jsonl_flushes_before_input_eof():
    process = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--jsonl"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        process.stdin.write(encode(request_document()) + "\n")
        process.stdin.flush()
        assert selector.select(timeout=10), "Candidate Runner did not flush"
        response = json.loads(process.stdout.readline())
        assert response["schema_version"] == 1
        assert process.poll() is None
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        assert process.stderr.read() == ""
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def test_candidate_runner_rejects_invalid_utf8():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        input=b"\xff\n",
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    assert result.returncode == 2
    assert result.stdout == b""
    assert json.loads(result.stderr)["error"]["code"] == "invalid_request"
