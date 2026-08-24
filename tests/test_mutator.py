from __future__ import annotations

import hashlib
import json
import os
import selectors
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "apps" / "mutator" / "mutator.py"


def run_mutator(request: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        input=request,
        capture_output=True,
        check=False,
        text=True,
        env=os.environ.copy(),
    )


def run_mutator_bytes(
    request: bytes, *arguments: str
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        input=request,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )


def request_document(*, draw: object = 0.6) -> dict[str, object]:
    return {
        "schema_version": 1,
        "catalogue": {
            "loci": [
                {
                    "locus": "planner",
                    "alleles": ["react-v1", "plan-execute-v1", "reflect-v1"],
                },
                {"locus": "max_steps", "alleles": [4, 8, 12]},
            ]
        },
        "parent_genome": {"planner": "react-v1", "max_steps": 8},
        "mutation_distribution": [
            {
                "locus": "planner",
                "allele": "plan-execute-v1",
                "probability": 0.5,
            },
            {"locus": "planner", "allele": "reflect-v1", "probability": 0.25},
            {"locus": "max_steps", "allele": 12, "probability": 0.25},
        ],
        "draw": draw,
    }


def encode(document: object) -> str:
    return json.dumps(document, separators=(",", ":"), sort_keys=True)


def assert_invalid(result: subprocess.CompletedProcess[str], code: str) -> str:
    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)["error"]
    assert error["code"] == code
    assert result.stderr == encode({"error": error}) + "\n"
    return error["message"]


def test_mutator_generates_one_deterministic_child_and_named_measurements():
    result = run_mutator(encode(request_document()))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    response = json.loads(result.stdout)
    assert response["schema_version"] == 1
    assert response["parent"]["genome"] == {
        "max_steps": 8,
        "planner": "react-v1",
    }
    assert response["child"]["genome"] == {
        "max_steps": 8,
        "planner": "plan-execute-v1",
    }
    assert response["mutation"] == {
        "after": "plan-execute-v1",
        "before": "react-v1",
        "locus": "planner",
        "mutation_id": response["mutation"]["mutation_id"],
        "probability": 0.5,
        "surprisal": {
            "base": 2.0,
            "infinite": False,
            "measure": "self_information",
            "value": 1.0,
        },
    }
    expected_catalogue_id = hashlib.sha256(
        encode(
            {
                "catalogue": {
                    "loci": [
                        {"alleles": [12, 4, 8], "locus": "max_steps"},
                        {
                            "alleles": [
                                "plan-execute-v1",
                                "react-v1",
                                "reflect-v1",
                            ],
                            "locus": "planner",
                        },
                    ]
                },
                "genome_schema": "flat-json-atoms-v1",
                "schema_version": 1,
            }
        ).encode("ascii")
    ).hexdigest()
    assert response["catalogue_id"] == expected_catalogue_id
    assert len(response["parent"]["candidate_id"]) == 64
    assert len(response["child"]["candidate_id"]) == 64
    assert len(response["mutation"]["mutation_id"]) == 64
    assert response["parent"]["candidate_id"] != response["child"]["candidate_id"]
    assert response["mutation_distribution"]["support_count"] == 3
    assert response["mutation_distribution"]["entropy"] == {
        "base": 2.0,
        "infinite": False,
        "measure": "entropy",
        "value": 1.5,
    }
    assert response["mutation_distribution"]["support"] == [
        {"allele": 12, "locus": "max_steps", "probability": 0.25},
        {
            "allele": "plan-execute-v1",
            "locus": "planner",
            "probability": 0.5,
        },
        {"allele": "reflect-v1", "locus": "planner", "probability": 0.25},
    ]
    assert result.stdout == encode(response) + "\n"


def test_mutator_normalizes_semantic_order_before_selection_and_identity():
    first = request_document()
    second = request_document()
    second["catalogue"]["loci"].reverse()  # type: ignore[index,union-attr]
    for locus in second["catalogue"]["loci"]:  # type: ignore[index,union-attr]
        locus["alleles"].reverse()
    second["mutation_distribution"].reverse()  # type: ignore[union-attr]

    first_result = run_mutator(encode(first))
    second_result = run_mutator(encode(second))

    assert first_result.returncode == second_result.returncode == 0
    assert first_result.stdout == second_result.stdout


def test_mutator_draw_selects_against_the_normalized_support():
    first = json.loads(run_mutator(encode(request_document(draw=0.1))).stdout)
    second = json.loads(run_mutator(encode(request_document(draw=0.3))).stdout)
    third = json.loads(run_mutator(encode(request_document(draw=0.9))).stdout)

    assert (first["mutation"]["locus"], first["mutation"]["after"]) == (
        "max_steps",
        12,
    )
    assert (second["mutation"]["locus"], second["mutation"]["after"]) == (
        "planner",
        "plan-execute-v1",
    )
    assert (third["mutation"]["locus"], third["mutation"]["after"]) == (
        "planner",
        "reflect-v1",
    )
    assert first["catalogue_id"] == second["catalogue_id"] == third["catalogue_id"]
    assert (
        first["parent"]["candidate_id"]
        == second["parent"]["candidate_id"]
        == third["parent"]["candidate_id"]
    )


def test_mutator_rejects_illegal_or_nonchanging_transitions():
    cases: list[dict[str, object]] = []

    bad_parent = request_document()
    bad_parent["parent_genome"]["planner"] = "unknown"  # type: ignore[index]
    cases.append(bad_parent)

    bad_allele = request_document()
    bad_allele["mutation_distribution"][0]["allele"] = "unknown"  # type: ignore[index]
    cases.append(bad_allele)

    no_change = request_document()
    no_change["mutation_distribution"][0]["allele"] = "react-v1"  # type: ignore[index]
    cases.append(no_change)

    duplicate = request_document()
    duplicate["mutation_distribution"].append(  # type: ignore[union-attr]
        {
            "locus": "planner",
            "allele": "plan-execute-v1",
            "probability": 0.1,
        }
    )
    cases.append(duplicate)

    for document in cases:
        assert_invalid(run_mutator(encode(document)), "invalid_request")


def test_mutator_rejects_bad_probability_models_draws_and_float_genes():
    not_normalized = request_document()
    not_normalized["mutation_distribution"][0][  # type: ignore[index]
        "probability"
    ] = 0.4
    assert "sum to 1" in assert_invalid(
        run_mutator(encode(not_normalized)), "invalid_probability"
    )

    zero_probability = request_document()
    zero_probability["mutation_distribution"][0][  # type: ignore[index]
        "probability"
    ] = 0
    assert_invalid(run_mutator(encode(zero_probability)), "invalid_request")

    invalid_draw = request_document(draw=1)
    assert_invalid(run_mutator(encode(invalid_draw)), "invalid_request")

    float_gene = request_document()
    float_gene["catalogue"]["loci"][1][  # type: ignore[index]
        "alleles"
    ] = [4.0, 8.0, 12.0]
    float_gene["parent_genome"]["max_steps"] = 8.0  # type: ignore[index]
    assert "floating-point genome values" in assert_invalid(
        run_mutator(encode(float_gene)), "invalid_request"
    )


def test_mutator_does_not_assign_probability_mass_missing_within_tolerance():
    document = request_document(draw=0.9999999999998)
    document["mutation_distribution"][0][  # type: ignore[index]
        "probability"
    ] = 0.4999999999995

    message = assert_invalid(run_mutator(encode(document)), "invalid_request")

    assert "does not normalize" in message


def test_mutator_jsonl_replies_before_input_reaches_eof():
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
        assert selector.select(timeout=10), (
            "Mutator did not flush a JSONL response"
        )
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


def test_mutator_jsonl_returns_errors_and_continues():
    valid = encode(request_document())
    invalid = encode({**request_document(), "draw": 1})

    result = run_mutator("{\n" + invalid + "\n" + valid + "\n", "--jsonl")

    assert result.returncode == 0
    assert result.stderr == ""
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]["error"]["code"] == "invalid_request"
    assert responses[1]["error"]["code"] == "invalid_request"
    assert responses[2]["child"]["genome"]["planner"] == "plan-execute-v1"


def test_mutator_jsonl_rejects_invalid_utf8_and_continues():
    valid = encode(request_document()).encode()

    result = run_mutator_bytes(b"\xff\n" + valid + b"\n", "--jsonl")

    assert result.returncode == 0
    assert result.stderr == b""
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]["error"]["code"] == "invalid_request"
    assert "UTF-8" in responses[0]["error"]["message"]
    assert responses[1]["schema_version"] == 1


def test_mutator_rejects_duplicate_keys_and_unsupported_arguments():
    duplicate = run_mutator(
        '{"schema_version":1,"schema_version":1,"catalogue":{},'
        '"parent_genome":{},"mutation_distribution":[],"draw":0}'
    )
    assert "duplicate key" in assert_invalid(duplicate, "invalid_request")

    arguments = run_mutator(encode(request_document()), "--unknown")
    assert "arguments" in assert_invalid(arguments, "invalid_request")
