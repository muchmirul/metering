from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "apps" / "selection_gate" / "selection_gate.py"


def run_gate(request: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        input=request,
        capture_output=True,
        check=False,
        text=True,
        env=os.environ.copy(),
    )


def run_gate_bytes(
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


def encode(document: object) -> str:
    return json.dumps(document, allow_nan=False, separators=(",", ":"), sort_keys=True)


def forecast_report(
    candidate: str,
    probabilities: list[float],
    *,
    evaluation: str = "weather/holdout-v1",
    reverse: bool = False,
) -> dict[str, object]:
    outcomes: list[dict[str, object]] = []
    finite_values: list[float] = []
    infinite = False
    for index, probability in enumerate(probabilities, start=1):
        value = math.inf if probability == 0 else -math.log2(probability)
        outcome_infinite = math.isinf(value)
        infinite = infinite or outcome_infinite
        if not outcome_infinite:
            finite_values.append(value)
        outcomes.append(
            {
                "infinite": outcome_infinite,
                "observation": f"case-{index}",
                "target": "yes" if index % 2 else "no",
                "target_probability": probability,
                "value_bits": None if outcome_infinite else value,
            }
        )
    if reverse:
        outcomes.reverse()
    mean = None if infinite else math.fsum(finite_values) / len(outcomes)
    return {
        "candidate": candidate,
        "evaluation": evaluation,
        "measurement": {
            "aggregate": {
                "infinite": infinite,
                "mean_target_surprisal_bits": mean,
                "sample_count": len(outcomes),
            },
            "base": 2.0,
            "metering_measure": "self_information",
            "outcomes": outcomes,
        },
    }


def request_document(
    incumbent_probabilities: list[float],
    challenger_probabilities: list[float],
    *,
    threshold: object = 0.05,
    reverse_challenger: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "incumbent_report": forecast_report("parent", incumbent_probabilities),
        "challenger_report": forecast_report(
            "child", challenger_probabilities, reverse=reverse_challenger
        ),
        "required_improvement_bits": threshold,
    }


def assert_invalid(result: subprocess.CompletedProcess[str], code: str) -> str:
    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)["error"]
    assert error["code"] == code
    assert result.stderr == encode({"error": error}) + "\n"
    return error["message"]


def test_selection_gate_promotes_a_verified_better_challenger():
    result = run_gate(encode(request_document([0.5, 0.5], [0.75, 0.75])))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    response = json.loads(result.stdout)
    assert response["decision"] == "promote_challenger"
    assert response["reason"] == "required_improvement_exceeded"
    assert response["selected"] == "child"
    assert response["incumbent"] == "parent"
    assert response["challenger"] == "child"
    assert response["comparison"]["incumbent"] == {
        "infinite": False,
        "mean_target_surprisal_bits": 1.0,
    }
    assert response["comparison"]["challenger"]["infinite"] is False
    assert math.isclose(
        response["comparison"]["challenger"]["mean_target_surprisal_bits"],
        -math.log2(0.75),
    )
    assert math.isclose(
        response["comparison"]["mean_improvement_bits"],
        1.0 + math.log2(0.75),
    )
    assert response["comparison"]["required_improvement_bits"] == 0.05
    assert response["comparison"]["sample_count"] == 2
    assert len(response["evidence_id"]) == 64
    assert result.stdout == encode(response) + "\n"


def test_selection_gate_uses_a_strict_threshold_and_retains_ties():
    tie = json.loads(
        run_gate(encode(request_document([0.5], [0.5], threshold=0))).stdout
    )
    exactly_threshold = json.loads(
        run_gate(
            encode(
                request_document(
                    [0.5],
                    [2 ** -(1.0 - 0.25)],
                    threshold=0.25,
                )
            )
        ).stdout
    )

    assert tie["decision"] == "retain_incumbent"
    assert tie["comparison"]["mean_improvement_bits"] == 0.0
    assert exactly_threshold["decision"] == "retain_incumbent"
    assert exactly_threshold["reason"] == "required_improvement_not_exceeded"


def test_selection_gate_aligns_evidence_by_identifier_not_array_position():
    ordered = json.loads(
        run_gate(encode(request_document([0.5, 0.25], [0.75, 0.5]))).stdout
    )
    reordered = json.loads(
        run_gate(
            encode(
                request_document(
                    [0.5, 0.25],
                    [0.75, 0.5],
                    reverse_challenger=True,
                )
            )
        ).stdout
    )

    assert ordered == reordered


def test_selection_gate_rejects_mismatched_evaluations_cases_and_targets():
    evaluation = request_document([0.5], [0.75])
    evaluation["challenger_report"]["evaluation"] = "other"  # type: ignore[index]

    missing_case = request_document([0.5, 0.5], [0.75, 0.75])
    challenger = missing_case["challenger_report"]  # type: ignore[assignment]
    challenger["measurement"]["outcomes"].pop()  # type: ignore[index]
    challenger["measurement"]["aggregate"]["sample_count"] = 1  # type: ignore[index]
    challenger["measurement"]["aggregate"][  # type: ignore[index]
        "mean_target_surprisal_bits"
    ] = -math.log2(0.75)

    target = request_document([0.5], [0.75])
    target["challenger_report"]["measurement"]["outcomes"][0][  # type: ignore[index]
        "target"
    ] = "different"

    for document in (evaluation, missing_case, target):
        assert_invalid(run_gate(encode(document)), "invalid_request")


def test_selection_gate_recomputes_outcomes_and_aggregate_instead_of_trusting_them():
    tampered_outcome = request_document([0.5], [0.75])
    tampered_outcome["challenger_report"]["measurement"]["outcomes"][0][  # type: ignore[index]
        "value_bits"
    ] = 0.0

    tampered_mean = request_document([0.5], [0.75])
    tampered_mean["challenger_report"]["measurement"]["aggregate"][  # type: ignore[index]
        "mean_target_surprisal_bits"
    ] = 0.0

    bad_infinite = request_document([0.5], [0.75])
    bad_infinite["challenger_report"]["measurement"]["outcomes"][0][  # type: ignore[index]
        "infinite"
    ] = True

    for document in (tampered_outcome, tampered_mean, bad_infinite):
        assert_invalid(run_gate(encode(document)), "invalid_request")


def test_selection_gate_orders_finite_and_infinite_reports_conservatively():
    finite_beats_infinite = json.loads(
        run_gate(encode(request_document([0.0], [0.5], threshold=100))).stdout
    )
    infinite_loses = json.loads(
        run_gate(encode(request_document([0.5], [0.0], threshold=0))).stdout
    )
    both_infinite = json.loads(
        run_gate(encode(request_document([0.0], [0.0], threshold=0))).stdout
    )

    assert finite_beats_infinite["decision"] == "promote_challenger"
    assert finite_beats_infinite["reason"] == (
        "finite_challenger_beats_infinite_incumbent"
    )
    assert finite_beats_infinite["comparison"]["mean_improvement_bits"] is None

    assert infinite_loses["decision"] == "retain_incumbent"
    assert infinite_loses["reason"] == "infinite_challenger_rejected"
    assert infinite_loses["comparison"]["mean_improvement_bits"] is None

    assert both_infinite["decision"] == "retain_incumbent"
    assert both_infinite["reason"] == "both_reports_infinite"
    assert both_infinite["comparison"]["mean_improvement_bits"] is None


def test_selection_gate_rejects_same_candidate_and_negative_threshold():
    same = request_document([0.5], [0.75])
    same["challenger_report"]["candidate"] = "parent"  # type: ignore[index]
    assert "must differ" in assert_invalid(run_gate(encode(same)), "invalid_request")

    negative = request_document([0.5], [0.75], threshold=-0.1)
    assert_invalid(run_gate(encode(negative)), "invalid_request")


def test_selection_gate_jsonl_returns_errors_and_continues():
    valid = encode(request_document([0.5], [0.75]))
    invalid = encode(
        {**request_document([0.5], [0.75]), "required_improvement_bits": -1}
    )

    result = run_gate("{\n" + invalid + "\n" + valid + "\n", "--jsonl")

    assert result.returncode == 0
    assert result.stderr == ""
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]["error"]["code"] == "invalid_request"
    assert responses[1]["error"]["code"] == "invalid_request"
    assert responses[2]["decision"] == "promote_challenger"


def test_selection_gate_jsonl_rejects_invalid_utf8_and_continues():
    valid = encode(request_document([0.5], [0.75])).encode()

    result = run_gate_bytes(b"\xff\n" + valid + b"\n", "--jsonl")

    assert result.returncode == 0
    assert result.stderr == b""
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]["error"]["code"] == "invalid_request"
    assert "UTF-8" in responses[0]["error"]["message"]
    assert responses[1]["decision"] == "promote_challenger"


def test_selection_gate_rejects_duplicate_keys_and_unsupported_arguments():
    duplicate = run_gate(
        '{"schema_version":1,"schema_version":1,"incumbent_report":{},'
        '"challenger_report":{},"required_improvement_bits":0}'
    )
    assert "duplicate key" in assert_invalid(duplicate, "invalid_request")

    arguments = run_gate(encode(request_document([0.5], [0.75])), "--unknown")
    assert "arguments" in assert_invalid(arguments, "invalid_request")
