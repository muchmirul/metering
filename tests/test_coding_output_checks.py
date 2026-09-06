"""Externally compare output values; candidate success markers are not evidence."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_digest, canonical_json  # noqa: E402
from apps.coding_agent.candidate_runner import EVIDENCE_KEY, _write_receipt  # noqa: E402
from apps.coding_agent.checks import CheckError, check_passed, validate_output_contract  # noqa: E402
from apps.coding_agent.solution_evaluator import evaluate  # noqa: E402
from apps.harness.runtime_manifest import load_runtime_manifest  # noqa: E402
from apps.population.contract import RESOURCE_NAMES  # noqa: E402

RUNTIME = ROOT / "apps/harness/profiles/runtime-fixture.json"


def output_assay():
    return {
        "argv": ["python", "-c", "import solver; solver.main()"],
        "timeout_ms": 1000,
        "check_schema": "stdout-json-v1",
        "expected_stdout": {"answers": [3, None, -1]},
    }


@pytest.mark.parametrize(
    "stdout,passed",
    [
        ('{"answers":[3,null,-1]}\n', True),
        (' {"answers": [3, null, -1]} ', True),
        ("", False),  # os._exit(0) before the checks finish
        ('{"passed":true}', False),
        ('{"answers":[]}', False),
        ('{"answers":[3,null]}', False),
        ('{"answers":[3,null,-1,4]}', False),
        ('{"answers":[3,null,-1],"passed":true}', False),
        ('{"answers":[3.0,null,-1]}', False),
        ('{"answers":[true,null,-1]}', False),
        ('{"answers":[3,null,-1],"answers":[3,null,-1]}', False),
        ('{"answers":[3,null,NaN]}', False),
        ('{"answers":[3,null,-1]}\n{}', False),
        ('{"answers":[3,null,-1]}...[truncated;sha256:abc]', False),
        ('{"answers":[3,null,-1]}\n' + " " * 65_536, False),
    ],
)
def test_output_values_not_exit_zero_or_markers_determine_success(stdout, passed):
    execution = {"returncode": 0, "timed_out": False, "stdout": stdout, "stderr": ""}
    assert check_passed(execution, output_assay()) is passed


@pytest.mark.parametrize(
    "returncode,timed_out", [(1, False), (None, False), (False, False), (0, True)]
)
def test_complete_output_still_requires_successful_execution(returncode, timed_out):
    execution = {
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout": '{"answers":[3,null,-1]}',
        "stderr": "",
    }
    assert check_passed(execution, output_assay()) is False


def test_legacy_exit_only_assay_keeps_recorded_meaning():
    execution = {"returncode": 0, "timed_out": False, "stdout": "", "stderr": ""}
    assert check_passed(execution, {"argv": ["python", "check.py"], "timeout_ms": 1000})


@pytest.mark.parametrize(
    "changes",
    [
        {"check_schema": "stdout-json-v999"},
        {"expected_stdout": {}},
        {"expected_stdout": []},
        {"expected_stdout": {"result": float("nan")}},
        {"expected_stdout": {"result": "x" * 65_536}},
        {"extra": True},
    ],
)
def test_output_contract_is_explicit_strict_and_bounded(changes):
    with pytest.raises(CheckError):
        validate_output_contract({**output_assay(), **changes})


@pytest.mark.parametrize(
    "stdout,receipt_changes,passed,safe",
    [
        ('{"answers":[3,null,-1]}', {}, True, True),
        ('{"passed":true}', {}, False, True),
        ("", {}, False, True),
        (
            '{"answers":[3,null,-1]}',
            {"receipt_schema": "darwinian-coding-evaluation-receipt-v1"},
            False,
            False,
        ),
        ('{"answers":[3,null,-1]}', {"task_id": "f" * 64}, False, False),
        (
            '{"answers":[3,null,-1]}',
            {
                "assay": {
                    **output_assay(),
                    "expected_stdout": {"answers": [3.0, None, -1]},
                }
            },
            False,
            False,
        ),
    ],
)
def test_evaluator_binds_contract_and_rejects_downgraded_receipts(
    tmp_path, monkeypatch, stdout, receipt_changes, passed, safe
):
    runtime = load_runtime_manifest(RUNTIME)
    task = {
        "case_id": "case",
        "input": {
            "assay": output_assay(),
            "outcomes": ["fail", "pass"],
            "prompt": "Solve it.",
        },
    }
    execution = {"returncode": 0, "timed_out": False, "stdout": stdout, "stderr": ""}
    receipt = {
        "assay": output_assay(),
        "candidate_content_sha256": "b" * 64,
        "candidate_id": "a" * 64,
        "cost": {name: 0 for name in RESOURCE_NAMES},
        "execution": execution,
        "isolation_enforced": False,
        "kernel_observations": [],
        "receipt_schema": "darwinian-coding-evaluation-receipt-v2",
        "runtime_id": runtime.runtime_id,
        "task_id": canonical_digest(task),
        "workspace_sha256": "c" * 64,
        **receipt_changes,
    }
    reference = _write_receipt(tmp_path / "receipts", receipt)
    monkeypatch.setenv(
        "METERING_CODING_EVALUATION_RECEIPT_DIR", str(tmp_path / "receipts")
    )
    monkeypatch.setenv("METERING_HARNESS_RUNTIME_MANIFEST", str(RUNTIME))
    response = evaluate(
        {
            "case": task,
            "evaluation": "coding-v1",
            "protocol_version": 1,
            "submissions": [
                {
                    "candidate_id": "a" * 64,
                    "submission": {
                        EVIDENCE_KEY: {
                            "receipt": reference,
                            "runtime_id": runtime.runtime_id,
                        },
                        "execution": {
                            "returncode": 0,
                            "timed_out": False,
                            "stdout_sha256": hashlib.sha256(
                                stdout.encode()
                            ).hexdigest(),
                            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                        },
                    },
                }
            ],
        }
    )
    result = response["results"][0]
    assert result["passed"] is passed
    assert result["safety_passed"] is safe
    assert canonical_json(receipt).isascii()
