"""Schema-v2 task-evidence verification and pairwise retention policy."""

from __future__ import annotations

import math
from dataclasses import dataclass

from metering import self_information

from apps.agent_protocol import (
    AGENT_SCHEMA_VERSION,
    ProtocolError,
    normalize_json_value,
    require_bool,
    require_exact_keys,
    require_nonempty_string,
    require_schema_version,
    require_sha256,
)
from apps.selection_gate.report_validation import (
    RequestError,
    nonnegative_number,
    number_as_float,
    probability,
    same_number,
)
from apps.stdio_connector import canonical_digest


@dataclass(frozen=True)
class VerifiedTaskCase:
    case_id: str
    evidence: object
    outcome: str
    passed: bool
    safety_passed: bool
    target_probability: float
    target_surprisal_bits: float

    def selection_evidence(self) -> dict[str, object]:
        return {
            "evidence": self.evidence,
            "outcome": self.outcome,
            "passed": self.passed,
            "safety_passed": self.safety_passed,
            "target_probability": self.target_probability,
        }


@dataclass(frozen=True)
class VerifiedTaskReport:
    candidate: str
    evaluation: str
    cases: dict[str, dict[str, object]]
    passed_count: int
    safety_failures: int
    mean_target_surprisal_bits: float | None


def _verify_task_case(raw_case: object, location: str) -> VerifiedTaskCase:
    if type(raw_case) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(
        raw_case,
        {
            "case_id",
            "evidence",
            "outcome",
            "passed",
            "safety_passed",
            "target_probability",
            "target_surprisal",
        },
        location,
    )
    case_id = require_nonempty_string(raw_case["case_id"], f"{location}.case_id")
    outcome = require_nonempty_string(raw_case["outcome"], f"{location}.outcome")
    passed = require_bool(raw_case["passed"], f"{location}.passed")
    safety_passed = require_bool(raw_case["safety_passed"], f"{location}.safety_passed")
    target_probability = probability(
        raw_case["target_probability"], f"{location}.target_probability"
    )
    measured = self_information(target_probability, base=2)
    infinite = math.isinf(measured)

    raw_surprisal = raw_case["target_surprisal"]
    surprisal_location = f"{location}.target_surprisal"
    if type(raw_surprisal) is not dict:
        raise ProtocolError(f"{surprisal_location} must be a JSON object")
    require_exact_keys(raw_surprisal, {"infinite", "value_bits"}, surprisal_location)
    if (
        require_bool(raw_surprisal["infinite"], f"{surprisal_location}.infinite")
        != infinite
    ):
        raise ProtocolError(f"{surprisal_location}.infinite does not match Metering")
    if infinite:
        if raw_surprisal["value_bits"] is not None:
            raise ProtocolError(f"{surprisal_location}.value_bits must be null")
    else:
        reported = nonnegative_number(
            raw_surprisal["value_bits"], f"{surprisal_location}.value_bits"
        )
        if not same_number(reported, measured):
            raise ProtocolError(
                f"{surprisal_location}.value_bits does not match Metering"
            )

    return VerifiedTaskCase(
        case_id=case_id,
        evidence=normalize_json_value(raw_case["evidence"], f"{location}.evidence"),
        outcome=outcome,
        passed=passed,
        safety_passed=safety_passed,
        target_probability=target_probability,
        target_surprisal_bits=measured,
    )


def _verify_task_summary(
    value: object,
    location: str,
    *,
    case_count: int,
    passed_count: int,
    safety_failures: int,
) -> None:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(
        value,
        {"case_count", "passed_count", "safety_failures"},
        location,
    )
    expected = {
        "case_count": case_count,
        "passed_count": passed_count,
        "safety_failures": safety_failures,
    }
    if value != expected:
        raise ProtocolError(f"{location} does not match cases")


def _verify_forecast_measurement(
    value: object,
    location: str,
    *,
    case_count: int,
    surprisal_values: list[float],
) -> float | None:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(value, {"aggregate", "base", "metering_measure"}, location)
    base_exact, _ = number_as_float(value["base"], f"{location}.base")
    if base_exact != 2 or value["metering_measure"] != "self_information":
        raise ProtocolError(f"{location} must report base-2 self_information")

    aggregate = value["aggregate"]
    aggregate_location = f"{location}.aggregate"
    if type(aggregate) is not dict:
        raise ProtocolError(f"{aggregate_location} must be a JSON object")
    require_exact_keys(
        aggregate,
        {"infinite", "mean_target_surprisal_bits", "sample_count"},
        aggregate_location,
    )
    if aggregate["sample_count"] != case_count:
        raise ProtocolError(f"{aggregate_location}.sample_count does not match cases")
    any_infinite = any(math.isinf(value) for value in surprisal_values)
    if (
        require_bool(aggregate["infinite"], f"{aggregate_location}.infinite")
        != any_infinite
    ):
        raise ProtocolError(f"{aggregate_location}.infinite does not match cases")
    if any_infinite:
        if aggregate["mean_target_surprisal_bits"] is not None:
            raise ProtocolError(f"{location} aggregate mean must be null")
        return None

    expected_mean = math.fsum(surprisal_values) / case_count
    mean = nonnegative_number(
        aggregate["mean_target_surprisal_bits"],
        f"{aggregate_location}.mean_target_surprisal_bits",
    )
    if not same_number(mean, expected_mean):
        raise ProtocolError(f"{location} aggregate mean does not match cases")
    return mean


def _verify_task_report(raw_report: object, location: str) -> VerifiedTaskReport:
    if type(raw_report) is not dict:
        raise RequestError(f"{location} must be a JSON object")
    try:
        require_exact_keys(
            raw_report,
            {
                "candidate",
                "cases",
                "evaluation",
                "forecast_measurement",
                "schema_version",
                "task_summary",
            },
            location,
        )
        require_schema_version(
            raw_report["schema_version"], f"{location}.schema_version"
        )
        candidate = require_sha256(raw_report["candidate"], f"{location}.candidate")
        evaluation = require_nonempty_string(
            raw_report["evaluation"], f"{location}.evaluation"
        )
        raw_cases = raw_report["cases"]
        if type(raw_cases) is not list or not raw_cases:
            raise ProtocolError(f"{location}.cases must be a non-empty JSON array")
        cases: dict[str, dict[str, object]] = {}
        surprisal_values: list[float] = []
        passed_count = 0
        safety_failures = 0
        for index, raw_case in enumerate(raw_cases):
            task_case = _verify_task_case(
                raw_case,
                f"{location}.cases[{index}]",
            )
            if task_case.case_id in cases:
                raise ProtocolError(
                    f"{location} contains duplicate case: {task_case.case_id}"
                )
            cases[task_case.case_id] = task_case.selection_evidence()
            surprisal_values.append(task_case.target_surprisal_bits)
            passed_count += int(task_case.passed)
            safety_failures += int(not task_case.safety_passed)

        _verify_task_summary(
            raw_report["task_summary"],
            f"{location}.task_summary",
            case_count=len(cases),
            passed_count=passed_count,
            safety_failures=safety_failures,
        )
        mean = _verify_forecast_measurement(
            raw_report["forecast_measurement"],
            f"{location}.forecast_measurement",
            case_count=len(cases),
            surprisal_values=surprisal_values,
        )
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc

    return VerifiedTaskReport(
        candidate=candidate,
        evaluation=evaluation,
        cases=cases,
        passed_count=passed_count,
        safety_failures=safety_failures,
        mean_target_surprisal_bits=mean,
    )


def select_task_reports(request: dict[str, object]) -> dict[str, object]:
    try:
        require_exact_keys(
            request,
            {"schema_version", "incumbent_report", "challenger_report", "policy"},
            "request",
        )
        require_schema_version(request["schema_version"])
        policy = request["policy"]
        if type(policy) is not dict:
            raise ProtocolError("policy must be a JSON object")
        require_exact_keys(
            policy,
            {"type", "minimum_pass_improvement", "reject_safety_regression"},
            "policy",
        )
        if policy["type"] != "task-pass-count-v1":
            raise ProtocolError("policy.type must be task-pass-count-v1")
        minimum = policy["minimum_pass_improvement"]
        if type(minimum) is not int or minimum < 1:
            raise ProtocolError(
                "policy.minimum_pass_improvement must be a positive integer"
            )
        reject_safety = require_bool(
            policy["reject_safety_regression"], "policy.reject_safety_regression"
        )
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc

    incumbent = _verify_task_report(request["incumbent_report"], "incumbent_report")
    challenger = _verify_task_report(request["challenger_report"], "challenger_report")
    if incumbent.candidate == challenger.candidate:
        raise RequestError("incumbent and challenger candidates must differ")
    if incumbent.evaluation != challenger.evaluation:
        raise RequestError("incumbent and challenger evaluations must match")
    if set(incumbent.cases) != set(challenger.cases):
        raise RequestError("incumbent and challenger case identifier sets must match")

    pass_improvement = challenger.passed_count - incumbent.passed_count
    safety_regression = challenger.safety_failures > incumbent.safety_failures
    if reject_safety and safety_regression:
        promote = False
        reason = "safety_regression"
    elif pass_improvement >= minimum:
        promote = True
        reason = "required_pass_improvement_met"
    else:
        promote = False
        reason = "required_pass_improvement_not_met"
    selected = challenger.candidate if promote else incumbent.candidate
    evidence_id = canonical_digest(
        {
            "challenger_cases": challenger.cases,
            "evaluation": incumbent.evaluation,
            "incumbent_cases": incumbent.cases,
            "policy": policy,
            "schema_version": AGENT_SCHEMA_VERSION,
        }
    )
    return {
        "challenger": challenger.candidate,
        "comparison": {
            "challenger": {
                "mean_target_surprisal_bits": challenger.mean_target_surprisal_bits,
                "passed_count": challenger.passed_count,
                "safety_failures": challenger.safety_failures,
            },
            "incumbent": {
                "mean_target_surprisal_bits": incumbent.mean_target_surprisal_bits,
                "passed_count": incumbent.passed_count,
                "safety_failures": incumbent.safety_failures,
            },
            "pass_improvement": pass_improvement,
        },
        "decision": "promote_challenger" if promote else "retain_incumbent",
        "evaluation": incumbent.evaluation,
        "evidence_id": evidence_id,
        "incumbent": incumbent.candidate,
        "policy": policy,
        "reason": reason,
        "schema_version": AGENT_SCHEMA_VERSION,
        "selected": selected,
    }
