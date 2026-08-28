from __future__ import annotations

import json
import os
import runpy
import selectors
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "apps" / "controller" / "controller.py"
EXAMPLE_REQUEST = ROOT / "apps" / "controller" / "example-request.json"


def encode(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def mutation_request() -> dict[str, object]:
    return {
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


def request_document(active_version: str = "v3") -> dict[str, object]:
    return {
        "active_version": active_version,
        "evaluation": "observer-fixtures/config-port/holdout-v1",
        "mutation_request": mutation_request(),
        "probes": [
            {"operation": "read", "path": "config/mode.txt"},
            {"operation": "read", "path": "service/port.txt"},
        ],
        "required_improvement_bits": 0.05,
        "schema_version": 1,
    }


def run_controller(
    source: str, *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        input=source,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def error_document(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.returncode == 2
    assert result.stdout == ""
    return json.loads(result.stderr)


def test_checked_in_controller_request_is_executable():
    result = run_controller(EXAMPLE_REQUEST.read_text())

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["selection"]["decision"] == "promote_challenger"
    assert report["next_parent"] == report["mutation"]["child"]


def test_controller_runs_all_apps_and_promotes_a_better_child():
    result = run_controller(encode(request_document()))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert result.stdout == encode(report) + "\n"
    parent = report["mutation"]["parent"]
    child = report["mutation"]["child"]
    assert report["incumbent_report"]["candidate"] == parent["candidate_id"]
    assert report["challenger_report"]["candidate"] == child["candidate_id"]
    assert report["observer"]["finish"]["correct"] is True
    assert report["observer"]["finish"]["snapshot"]["name"] == "v3"
    assert report["runner_model"] == "observer-fixture-hypothesis-v1"
    assert len(report["cases"]) == 2
    for case in report["cases"]:
        assert case["incumbent_forecast"]["candidate_id"] == parent["candidate_id"]
        assert case["challenger_forecast"]["candidate_id"] == child["candidate_id"]
        assert case["target"] == encode(case["observer_response"]["observed_result"])
    parent_mean = report["incumbent_report"]["measurement"]["aggregate"][
        "mean_target_surprisal_bits"
    ]
    child_mean = report["challenger_report"]["measurement"]["aggregate"][
        "mean_target_surprisal_bits"
    ]
    assert parent_mean == pytest.approx(0.5849625007211563)
    assert child_mean == pytest.approx(0.2630344058337938)
    assert report["selection"]["decision"] == "promote_challenger"
    assert report["next_parent"] == child


def test_controller_captures_both_forecasts_before_observer_reveal(monkeypatch):
    api = runpy.run_path(str(SCRIPT))
    events: list[str] = []
    probe = {"operation": "read", "path": "config/mode.txt"}
    target = encode({"kind": "text", "text": "fast\n"})

    def fake_component(name, relative_path, request):
        del relative_path
        if name == "Mutator":
            return {
                "parent": {"candidate_id": "parent", "genome": {"gene": 1}},
                "child": {"candidate_id": "child", "genome": {"gene": 2}},
            }
        if name == "Candidate Runner":
            events.append(f"runner:{request['candidate_id']}")
            return {
                "candidate_id": request["candidate_id"],
                "forecast": {
                    "outcomes": [{"probability": 1.0, "target": target}]
                },
                "genome": request["genome"],
                "probe": request["probe"],
                "runner_model": "test-model",
            }
        if name == "Forecast Assay":
            return {"candidate": request["candidate"]}
        if name == "Selection Gate":
            return {"selected": "child"}
        raise AssertionError(name)

    class FakeObserver:
        def __init__(self, active_version):
            assert active_version == "v3"

        def request(self, request):
            if request["action"] == "state":
                return {
                    "available_probes": [{"probe": probe}],
                    "ok": True,
                    "snapshots": [{"name": "v3", "snapshot_id": "snapshot"}],
                }
            if request["action"] == "observe":
                events.append("observer:reveal")
                return {
                    "belief": {"v3": 1.0},
                    "done": True,
                    "observed_result": {"kind": "text", "text": "fast\n"},
                    "ok": True,
                }
            assert request == {"action": "finish", "snapshot_id": "snapshot"}
            return {"correct": True, "ok": True}

        def close(self):
            return None

        def abort(self):
            return None

    globals_ = api["run_generation"].__globals__
    monkeypatch.setitem(globals_, "_run_component", fake_component)
    monkeypatch.setitem(globals_, "ObserverSession", FakeObserver)

    report = api["run_generation"]("v3", "eval", {}, [probe], 0.0)

    assert events == ["runner:parent", "runner:child", "observer:reveal"]
    assert report["next_parent"] == {"candidate_id": "child", "genome": {"gene": 2}}


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
def test_observer_session_abort_kills_descendants(tmp_path, monkeypatch):
    api = runpy.run_path(str(SCRIPT))
    marker = tmp_path / "leaked-observer-child"
    observer = tmp_path / "fake-observer.py"
    child = (
        "import pathlib,time;"
        "time.sleep(1.5);"
        f"pathlib.Path({str(marker)!r}).write_text('leaked')"
    )
    observer.write_text(
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable,'-c',{child!r}])\n"
        "for line in sys.stdin:\n"
        "    time.sleep(10)\n",
        encoding="utf-8",
    )
    globals_ = api["ObserverSession"].__init__.__globals__
    monkeypatch.setitem(globals_, "OBSERVER", str(observer))
    monkeypatch.setitem(globals_, "COMPONENT_TIMEOUT_SECONDS", 1)
    session = api["ObserverSession"]("v1")
    try:
        with pytest.raises(api["ControllerError"], match="component timeout"):
            session.request({"action": "state"})
    finally:
        session.abort()
    time.sleep(1.0)

    assert not marker.exists()


def test_controller_retains_the_parent_when_v3_confidence_hurts_v4_results():
    result = run_controller(encode(request_document("v4")))

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["observer"]["finish"]["snapshot"]["name"] == "v4"
    assert report["selection"]["decision"] == "retain_incumbent"
    assert report["next_parent"] == report["mutation"]["parent"]
    comparison = report["selection"]["comparison"]
    assert (
        comparison["challenger"]["mean_target_surprisal_bits"]
        > comparison["incumbent"]["mean_target_surprisal_bits"]
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda request: request.update(schema_version=2), "schema_version"),
        (lambda request: request.update(active_version="v5"), "active_version"),
        (
            lambda request: request.update(required_improvement_bits=-0.1),
            "required_improvement_bits",
        ),
        (
            lambda request: request["probes"].append(request["probes"][0]),
            "duplicate probe",
        ),
        (lambda request: request.update(extra=True), "extra keys"),
    ],
)
def test_controller_rejects_invalid_request_envelopes(change, message):
    request = request_document()
    change(request)

    result = run_controller(encode(request))

    error = error_document(result)["error"]
    assert error["code"] == "invalid_request"
    assert message in error["message"]


def test_controller_reports_when_probes_do_not_identify_the_fixture():
    request = request_document()
    request["probes"] = [
        {"operation": "read", "path": "config/mode.txt"},
    ]

    result = run_controller(encode(request))

    error = error_document(result)["error"]
    assert error["code"] == "controller_error"
    assert "did not identify" in error["message"]


def test_controller_rejects_a_mutator_genome_the_runner_cannot_execute():
    request = request_document()
    request["mutation_request"] = {
        "catalogue": {
            "loci": [{"alleles": ["safe", "fast"], "locus": "mode"}]
        },
        "draw": 0,
        "mutation_distribution": [
            {"allele": "fast", "locus": "mode", "probability": 1}
        ],
        "parent_genome": {"mode": "safe"},
        "schema_version": 1,
    }

    result = run_controller(encode(request))

    error = error_document(result)["error"]
    assert error["code"] == "controller_error"
    assert "Candidate Runner failed" in error["message"]


def test_controller_jsonl_returns_errors_and_continues():
    source = "\n".join(("{", encode(request_document()), ""))

    result = run_controller(source, "--jsonl")

    assert result.returncode == 0
    assert result.stderr == ""
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]["error"]["code"] == "invalid_request"
    assert responses[1]["selection"]["decision"] == "promote_challenger"


def test_controller_jsonl_flushes_before_input_eof():
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
        assert selector.select(timeout=30), "Controller did not flush"
        response = json.loads(process.stdout.readline())
        assert response["selection"]["decision"] == "promote_challenger"
        assert process.poll() is None
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        assert process.stderr.read() == ""
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()
