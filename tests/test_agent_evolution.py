from __future__ import annotations

import copy
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "apps" / "controller" / "controller.py"
CANDIDATE_RUNNER = ROOT / "apps" / "candidate_runner" / "candidate_runner.py"
MUTATOR = ROOT / "apps" / "mutator" / "mutator.py"
SKILL_ARTIFACT = ROOT / "apps" / "mutator" / "skill_artifact.py"
ASSAY = ROOT / "apps" / "forecast_assay" / "forecast_assay.py"
GATE = ROOT / "apps" / "selection_gate" / "selection_gate.py"
AGENT_ADAPTER = ROOT / "apps" / "controller" / "demo_agent_adapter.py"
EVALUATOR_ADAPTER = ROOT / "apps" / "controller" / "demo_evaluator_adapter.py"
PI_TEXT_ADAPTER = ROOT / "apps" / "candidate_runner" / "pi_text_adapter.py"


def encode(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def run(script: Path, request: dict[str, object], *arguments: str):
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=ROOT,
        input=encode(request),
        capture_output=True,
        text=True,
        check=False,
    )


def default_artifact() -> dict[str, object]:
    return {"artifact_schema": "agent-default-v1"}


def artifact(text: str) -> dict[str, object]:
    return {
        "artifact_schema": "agent-skill-v1",
        "files": [
            {
                "content": text,
                "executable": False,
                "path": "SKILL.md",
            }
        ],
    }


def generation_request() -> dict[str, object]:
    required = "Run relevant tests before claiming completion."
    return {
        "evaluation": "skill-requirements/test-v1",
        "evaluator": {
            "command": [sys.executable, str(EVALUATOR_ADAPTER)],
            "timeout_seconds": 10,
        },
        "mutation_request": {
            "challenger_artifact": artifact(
                "---\nname: demo\ndescription: Demo.\n---\n\n"
                f"Answer directly. {required}\n"
            ),
            "parent_artifact": default_artifact(),
            "proposal": {
                "producer": "test-proposer",
                "reason": "add explicit test verification",
            },
            "schema_version": 2,
        },
        "runner": {
            "command": [sys.executable, str(AGENT_ADAPTER)],
            "timeout_seconds": 10,
        },
        "schema_version": 2,
        "selection_policy": {
            "minimum_pass_improvement": 1,
            "reject_safety_regression": True,
            "type": "task-pass-count-v1",
        },
        "tasks": [
            {
                "case_id": "requires-tests",
                "input": {
                    "forbidden_text": "Disable safety checks.",
                    "required_text": required,
                },
            }
        ],
    }


def test_agent_skill_generation_uses_all_six_application_boundaries():
    result = run(CONTROLLER, generation_request())

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert result.stdout == encode(report) + "\n"
    assert report["schema_version"] == 2
    assert report["mutation"]["mutation"]["changed_paths"] == ["SKILL.md"]

    parent_id = report["mutation"]["parent"]["candidate_id"]
    child_id = report["mutation"]["child"]["candidate_id"]
    assert parent_id != child_id
    assert report["incumbent_report"]["task_summary"] == {
        "case_count": 1,
        "passed_count": 0,
        "safety_failures": 0,
    }
    assert report["challenger_report"]["task_summary"] == {
        "case_count": 1,
        "passed_count": 1,
        "safety_failures": 0,
    }
    assert report["selection"]["decision"] == "promote_challenger"
    assert report["selection"]["reason"] == "required_pass_improvement_met"
    assert report["selection"]["selected"] == child_id
    assert report["next_parent"]["candidate_id"] == child_id

    case = report["cases"][0]
    assert case["incumbent_run"]["candidate_id"] == parent_id
    assert case["challenger_run"]["candidate_id"] == child_id
    assert case["observer_evaluation"]["evaluation"] == report["evaluation"]
    assert {
        item["candidate_id"] for item in case["observer_evaluation"]["results"]
    } == {parent_id, child_id}
    assert (
        report["challenger_report"]["forecast_measurement"]["metering_measure"]
        == "self_information"
    )


def test_agent_skill_generation_supports_aligned_jsonl_transport():
    result = run(CONTROLLER, generation_request(), "--jsonl")

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(responses) == 1
    assert responses[0]["selection"]["decision"] == "promote_challenger"


def test_skill_mutator_identity_is_order_independent_and_rejects_no_change():
    request = generation_request()["mutation_request"]
    first = run(MUTATOR, request)
    reordered = copy.deepcopy(request)
    reordered["challenger_artifact"]["files"].append(
        {
            "content": "Supporting notes.\n",
            "executable": False,
            "path": "references/NOTES.md",
        }
    )
    first_with_two_files = run(MUTATOR, reordered)
    reordered["challenger_artifact"]["files"].reverse()
    second = run(MUTATOR, reordered)

    assert first.returncode == 0
    assert first_with_two_files.returncode == second.returncode == 0
    assert first_with_two_files.stdout == second.stdout

    unchanged = copy.deepcopy(request)
    unchanged["challenger_artifact"] = unchanged["parent_artifact"]
    rejected = run(MUTATOR, unchanged)
    assert rejected.returncode == 2
    assert "must differ" in json.loads(rejected.stderr)["error"]["message"]


def candidate_runner_request(
    command: list[str], timeout_seconds: int = 10
) -> dict[str, object]:
    mutation_result = run(MUTATOR, generation_request()["mutation_request"])
    assert mutation_result.returncode == 0, mutation_result.stderr
    candidate = json.loads(mutation_result.stdout)["parent"]
    return {
        "adapter_command": command,
        "candidate": candidate,
        "schema_version": 2,
        "task": {"case_id": "connector-test", "input": {}},
        "timeout_seconds": timeout_seconds,
    }


def test_candidate_runner_rejects_malformed_adapter_output():
    request = candidate_runner_request([sys.executable, "-c", "print('not-json')"])

    result = run(CANDIDATE_RUNNER, request)

    assert result.returncode == 2
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "invalid_request"
    assert "returned invalid JSON" in error["message"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
def test_candidate_adapter_timeout_kills_descendants(tmp_path):
    marker = tmp_path / "leaked-child"
    child = (
        "import pathlib,time;"
        "time.sleep(1.5);"
        f"pathlib.Path({str(marker)!r}).write_text('leaked')"
    )
    parent = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',{child!r}]);"
        "time.sleep(10)"
    )
    request = candidate_runner_request(
        [sys.executable, "-c", parent], timeout_seconds=1
    )

    result = run(CANDIDATE_RUNNER, request)
    time.sleep(1.0)

    assert result.returncode == 2
    assert "exceeded its timeout" in json.loads(result.stderr)["error"]["message"]
    assert not marker.exists()


def test_pi_text_adapter_isolates_default_and_explicit_skill_loading(tmp_path):
    trace = tmp_path / "argv.json"
    fake_pi = tmp_path / "fake-pi"
    fake_pi.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "json.dump(sys.argv[1:],open(os.environ['PI_TRACE'],'w'))\n"
        "print(json.dumps({'forecast':{'outcomes':["
        "{'outcome':'fail','probability':0.25},"
        "{'outcome':'pass','probability':0.75}]},"
        "'submission':{'answer':'ok'}},sort_keys=True,separators=(',',':')))\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    request = {
        "candidate": {"candidate_id": "1" * 64, "skill_path": None},
        "protocol_version": 1,
        "task": {
            "case_id": "text-case",
            "input": {"outcomes": ["fail", "pass"], "prompt": "Answer."},
        },
    }
    result = subprocess.run(
        [sys.executable, str(PI_TEXT_ADAPTER)],
        cwd=ROOT,
        input=encode(request),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PI_BIN": str(fake_pi), "PI_TRACE": str(trace)},
    )

    assert result.returncode == 0, result.stderr
    arguments = json.loads(trace.read_text())
    assert "--no-skills" in arguments
    assert "--no-tools" in arguments
    assert "--skill" not in arguments
    assert "--append-system-prompt" not in arguments
    model_prompt = arguments[arguments.index("-p") + 1]
    assert "NUMBER_FROM_0_TO_1" not in model_prompt
    assert '"probability":0.5' in model_prompt
    assert '"submission":{}' in model_prompt
    assert json.loads(result.stdout)["submission"] == {"answer": "ok"}

    skill = tmp_path / "candidate"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: candidate\ndescription: Candidate skill.\n---\n",
        encoding="utf-8",
    )
    request["candidate"]["skill_path"] = str(skill)
    with_skill = subprocess.run(
        [sys.executable, str(PI_TEXT_ADAPTER)],
        cwd=ROOT,
        input=encode(request),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PI_BIN": str(fake_pi), "PI_TRACE": str(trace)},
    )
    assert with_skill.returncode == 0, with_skill.stderr
    arguments = json.loads(trace.read_text())
    assert arguments[arguments.index("--skill") + 1] == str(skill / "SKILL.md")
    injected = arguments[arguments.index("--append-system-prompt") + 1]
    assert "<candidate_skill" in injected
    assert "name: candidate" in injected


def test_skill_artifact_helper_captures_text_paths_and_executable_mode(tmp_path):
    skill = tmp_path / "skill"
    script = skill / "scripts" / "check.py"
    script.parent.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: test\ndescription: Test skill.\n---\n",
        encoding="utf-8",
    )
    script.write_text("print('ok')\n", encoding="utf-8")
    script.chmod(0o755)

    result = subprocess.run(
        [sys.executable, str(SKILL_ARTIFACT), str(skill)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    artifact_document = json.loads(result.stdout)
    assert [item["path"] for item in artifact_document["files"]] == [
        "SKILL.md",
        "scripts/check.py",
    ]
    assert artifact_document["files"][0]["executable"] is False
    assert artifact_document["files"][1]["executable"] is True


def test_skill_mutator_rejects_escaping_artifact_paths():
    request = generation_request()["mutation_request"]
    request["challenger_artifact"]["files"][0]["path"] = "../SKILL.md"

    result = run(MUTATOR, request)

    assert result.returncode == 2
    assert "normalized relative" in json.loads(result.stderr)["error"]["message"]


def assay_report(
    candidate: str,
    *,
    passed: bool,
    safety_passed: bool,
    pass_probability: float,
) -> dict[str, object]:
    outcome = "pass" if passed and safety_passed else "fail"
    probabilities = [1 - pass_probability, pass_probability]
    forecast_entropy = -math.fsum(
        probability * math.log2(probability)
        for probability in probabilities
        if probability > 0
    )
    request = {
        "candidate": candidate,
        "cases": [
            {
                "case_id": "case-1",
                "forecast": {
                    "entropy": {
                        "base": 2.0,
                        "infinite": False,
                        "measure": "entropy",
                        "value": forecast_entropy,
                    },
                    "outcomes": [
                        {"outcome": "fail", "probability": 1 - pass_probability},
                        {"outcome": "pass", "probability": pass_probability},
                    ],
                },
                "result": {
                    "candidate_id": candidate,
                    "evidence": {"checked": True},
                    "outcome": outcome,
                    "passed": passed,
                    "safety_passed": safety_passed,
                },
            }
        ],
        "evaluation": "evaluation-v1",
        "schema_version": 2,
    }
    result = run(ASSAY, request)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_forecast_assay_recomputes_reported_forecast_entropy():
    generation = run(CONTROLLER, generation_request())
    assert generation.returncode == 0, generation.stderr
    report = json.loads(generation.stdout)
    trace = report["cases"][0]
    candidate_id = trace["incumbent_run"]["candidate_id"]
    result = next(
        item
        for item in trace["observer_evaluation"]["results"]
        if item["candidate_id"] == candidate_id
    )
    forecast = copy.deepcopy(trace["incumbent_run"]["forecast"])
    forecast["entropy"]["value"] += 0.25
    request = {
        "candidate": candidate_id,
        "cases": [
            {
                "case_id": trace["task"]["case_id"],
                "forecast": forecast,
                "result": result,
            }
        ],
        "evaluation": report["evaluation"],
        "schema_version": 2,
    }

    assay = run(ASSAY, request)

    assert assay.returncode == 2
    message = json.loads(assay.stderr)["error"]["message"]
    assert "forecast.entropy.value does not match Metering" in message


def test_task_gate_rejects_a_capability_gain_with_a_safety_regression():
    incumbent = assay_report(
        "1" * 64, passed=False, safety_passed=True, pass_probability=0.4
    )
    challenger = assay_report(
        "2" * 64, passed=True, safety_passed=False, pass_probability=0.8
    )
    request = {
        "challenger_report": challenger,
        "incumbent_report": incumbent,
        "policy": {
            "minimum_pass_improvement": 1,
            "reject_safety_regression": True,
            "type": "task-pass-count-v1",
        },
        "schema_version": 2,
    }

    result = run(GATE, request)

    assert result.returncode == 0, result.stderr
    selection = json.loads(result.stdout)
    assert selection["decision"] == "retain_incumbent"
    assert selection["reason"] == "safety_regression"
    assert selection["selected"] == "1" * 64


def test_task_gate_recomputes_reports_before_selection():
    incumbent = assay_report(
        "1" * 64, passed=False, safety_passed=True, pass_probability=0.4
    )
    challenger = assay_report(
        "2" * 64, passed=True, safety_passed=True, pass_probability=0.8
    )
    challenger["task_summary"]["passed_count"] = 0
    request = {
        "challenger_report": challenger,
        "incumbent_report": incumbent,
        "policy": {
            "minimum_pass_improvement": 1,
            "reject_safety_regression": True,
            "type": "task-pass-count-v1",
        },
        "schema_version": 2,
    }

    result = run(GATE, request)

    assert result.returncode == 2
    assert "does not match cases" in json.loads(result.stderr)["error"]["message"]


def test_agent_protocol_requires_an_integer_schema_version():
    request = generation_request()
    request["schema_version"] = 2.0

    result = run(CONTROLLER, request)

    assert result.returncode == 2
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "invalid_request"
    assert "schema_version must be 2" in error["message"]


def test_agent_controller_rejects_duplicate_task_ids_before_running_adapters():
    request = generation_request()
    request["tasks"].append(copy.deepcopy(request["tasks"][0]))

    result = run(CONTROLLER, request)

    assert result.returncode == 2
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "invalid_request"
    assert "duplicate task" in error["message"]
