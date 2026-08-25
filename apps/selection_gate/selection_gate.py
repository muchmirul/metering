"""Verify two forecast-assay reports and make one pairwise retention decision."""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from metering import ProbabilityError, self_information

APPS_ROOT = Path(__file__).resolve().parents[1]
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from agent_protocol import (  # noqa: E402
    AGENT_SCHEMA_VERSION,
    ProtocolError,
    normalize_json_value,
    require_bool,
    require_exact_keys,
    require_nonempty_string,
    require_schema_version,
    require_sha256,
)
from stdio_connector import (  # noqa: E402
    canonical_digest,
    decode_json_object,
    run_stdio_application,
)

SCHEMA_VERSION = 1
REPORT_TOLERANCE = 1e-12


class RequestError(ValueError):
    """Raised when a selection request or report violates the contract."""


@dataclass(frozen=True)
class VerifiedReport:
    candidate: str
    evaluation: str
    infinite: bool
    mean_target_surprisal_bits: float | None
    outcomes: dict[str, tuple[str, float]]


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


def _decode_json(source: str) -> dict[str, object]:
    return decode_json_object(source, RequestError, parse_float=Decimal)


def _require_exact_keys(
    value: dict[str, object], expected: set[str], location: str
) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing keys: {', '.join(missing)}")
    if extra:
        details.append(f"extra keys: {', '.join(extra)}")
    if details:
        raise RequestError(f"{location}: {'; '.join(details)}")


def _require_nonempty_string(value: object, location: str) -> str:
    if type(value) is not str or not value:
        raise RequestError(f"{location} must be a non-empty string")
    return value


def _require_bool(value: object, location: str) -> bool:
    if type(value) is not bool:
        raise RequestError(f"{location} must be a boolean")
    return value


def _number_as_float(value: object, location: str) -> tuple[Decimal, float]:
    if type(value) is bool or not isinstance(value, (int, Decimal)):
        raise RequestError(f"{location} must be a finite JSON number")
    exact = Decimal(value) if type(value) is int else value
    try:
        converted = float(exact)
    except (OverflowError, ValueError) as exc:
        raise RequestError(f"{location} is outside the finite double range") from exc
    if not math.isfinite(converted):
        raise RequestError(f"{location} is outside the finite double range")
    return exact, converted


def _probability(value: object, location: str) -> float:
    exact, converted = _number_as_float(value, location)
    if exact < 0 or exact > 1:
        raise RequestError(f"{location} must be between 0 and 1")
    if (converted == 0.0 and exact != 0) or (
        converted == 1.0 and exact != 1
    ):
        raise RequestError(
            f"{location} would change whether its value is zero or one "
            "in double precision"
        )
    return 0.0 if converted == 0.0 else converted


def _nonnegative_number(value: object, location: str) -> float:
    exact, converted = _number_as_float(value, location)
    if exact < 0:
        raise RequestError(f"{location} must be greater than or equal to 0")
    if converted == 0.0 and exact != 0:
        raise RequestError(f"{location} is positive but rounds to 0")
    return 0.0 if converted == 0.0 else converted


def _same_number(left: float, right: float) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=REPORT_TOLERANCE,
        abs_tol=REPORT_TOLERANCE,
    )


def _verify_report(raw_report: object, location: str) -> VerifiedReport:
    if type(raw_report) is not dict:
        raise RequestError(f"{location} must be a JSON object")
    _require_exact_keys(
        raw_report,
        {"schema_version", "candidate", "evaluation", "measurement"},
        location,
    )
    if (
        type(raw_report["schema_version"]) is not int
        or raw_report["schema_version"] != SCHEMA_VERSION
    ):
        raise RequestError(
            f"{location}.schema_version must be {SCHEMA_VERSION}"
        )
    candidate = _require_nonempty_string(
        raw_report["candidate"], f"{location}.candidate"
    )
    evaluation = _require_nonempty_string(
        raw_report["evaluation"], f"{location}.evaluation"
    )

    raw_measurement = raw_report["measurement"]
    if type(raw_measurement) is not dict:
        raise RequestError(f"{location}.measurement must be a JSON object")
    _require_exact_keys(
        raw_measurement,
        {"aggregate", "base", "metering_measure", "outcomes"},
        f"{location}.measurement",
    )
    base_exact, _ = _number_as_float(
        raw_measurement["base"], f"{location}.measurement.base"
    )
    if base_exact != 2:
        raise RequestError(f"{location}.measurement.base must be 2")
    if raw_measurement["metering_measure"] != "self_information":
        raise RequestError(
            f"{location}.measurement.metering_measure must be self_information"
        )

    raw_outcomes = raw_measurement["outcomes"]
    if type(raw_outcomes) is not list or not raw_outcomes:
        raise RequestError(
            f"{location}.measurement.outcomes must be a non-empty JSON array"
        )

    outcomes: dict[str, tuple[str, float]] = {}
    finite_values: list[float] = []
    any_infinite = False
    for index, raw_outcome in enumerate(raw_outcomes):
        outcome_location = f"{location}.measurement.outcomes[{index}]"
        if type(raw_outcome) is not dict:
            raise RequestError(f"{outcome_location} must be a JSON object")
        _require_exact_keys(
            raw_outcome,
            {
                "infinite",
                "observation",
                "target",
                "target_probability",
                "value_bits",
            },
            outcome_location,
        )
        observation = _require_nonempty_string(
            raw_outcome["observation"], f"{outcome_location}.observation"
        )
        target = _require_nonempty_string(
            raw_outcome["target"], f"{outcome_location}.target"
        )
        if observation in outcomes:
            raise RequestError(
                f"{location} contains duplicate observation identifier: {observation}"
            )
        probability = _probability(
            raw_outcome["target_probability"],
            f"{outcome_location}.target_probability",
        )
        measured = self_information(probability, base=2)
        measured_infinite = math.isinf(measured)
        reported_infinite = _require_bool(
            raw_outcome["infinite"], f"{outcome_location}.infinite"
        )
        if reported_infinite != measured_infinite:
            raise RequestError(
                f"{outcome_location}.infinite does not match the target probability"
            )
        raw_value = raw_outcome["value_bits"]
        if measured_infinite:
            if raw_value is not None:
                raise RequestError(
                    f"{outcome_location}.value_bits must be null for infinite surprisal"
                )
            any_infinite = True
        else:
            reported_value = _nonnegative_number(
                raw_value, f"{outcome_location}.value_bits"
            )
            if not _same_number(reported_value, measured):
                raise RequestError(
                    f"{outcome_location}.value_bits does not match Metering"
                )
            finite_values.append(measured)
        outcomes[observation] = (target, probability)

    raw_aggregate = raw_measurement["aggregate"]
    if type(raw_aggregate) is not dict:
        raise RequestError(f"{location}.measurement.aggregate must be a JSON object")
    _require_exact_keys(
        raw_aggregate,
        {"infinite", "mean_target_surprisal_bits", "sample_count"},
        f"{location}.measurement.aggregate",
    )
    sample_count = raw_aggregate["sample_count"]
    if type(sample_count) is not int or sample_count <= 0:
        raise RequestError(
            f"{location}.measurement.aggregate.sample_count must be a positive integer"
        )
    if sample_count != len(raw_outcomes):
        raise RequestError(
            f"{location}.measurement.aggregate.sample_count does not match outcomes"
        )
    aggregate_infinite = _require_bool(
        raw_aggregate["infinite"], f"{location}.measurement.aggregate.infinite"
    )
    if aggregate_infinite != any_infinite:
        raise RequestError(
            f"{location}.measurement.aggregate.infinite does not match outcomes"
        )

    raw_mean = raw_aggregate["mean_target_surprisal_bits"]
    if any_infinite:
        if raw_mean is not None:
            raise RequestError(
                f"{location}.measurement.aggregate.mean_target_surprisal_bits "
                "must be null when any outcome is infinite"
            )
        mean = None
    else:
        expected_mean = math.fsum(finite_values) / len(finite_values)
        reported_mean = _nonnegative_number(
            raw_mean,
            f"{location}.measurement.aggregate.mean_target_surprisal_bits",
        )
        if not _same_number(reported_mean, expected_mean):
            raise RequestError(
                f"{location}.measurement.aggregate.mean_target_surprisal_bits "
                "does not match outcomes"
            )
        mean = expected_mean

    return VerifiedReport(
        candidate=candidate,
        evaluation=evaluation,
        infinite=any_infinite,
        mean_target_surprisal_bits=mean,
        outcomes=outcomes,
    )


def decode_request(
    source: str,
) -> tuple[VerifiedReport, VerifiedReport, float]:
    request = _decode_json(source)
    _require_exact_keys(
        request,
        {
            "schema_version",
            "incumbent_report",
            "challenger_report",
            "required_improvement_bits",
        },
        "request",
    )
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise RequestError("schema_version must be 1")
    incumbent = _verify_report(request["incumbent_report"], "incumbent_report")
    challenger = _verify_report(request["challenger_report"], "challenger_report")
    if incumbent.candidate == challenger.candidate:
        raise RequestError("incumbent and challenger candidates must differ")
    if incumbent.evaluation != challenger.evaluation:
        raise RequestError("incumbent and challenger evaluations must match")
    if set(incumbent.outcomes) != set(challenger.outcomes):
        raise RequestError(
            "incumbent and challenger observation identifier sets must match"
        )
    for observation in sorted(incumbent.outcomes):
        incumbent_target = incumbent.outcomes[observation][0]
        challenger_target = challenger.outcomes[observation][0]
        if incumbent_target != challenger_target:
            raise RequestError(
                f"target mismatch for observation {observation}: "
                f"{incumbent_target} != {challenger_target}"
            )
    threshold = _nonnegative_number(
        request["required_improvement_bits"], "required_improvement_bits"
    )
    return incumbent, challenger, threshold


def select(
    incumbent: VerifiedReport,
    challenger: VerifiedReport,
    threshold: float,
) -> dict[str, object]:
    improvement: float | None
    if incumbent.infinite and not challenger.infinite:
        promote = True
        reason = "finite_challenger_beats_infinite_incumbent"
        improvement = None
    elif not incumbent.infinite and challenger.infinite:
        promote = False
        reason = "infinite_challenger_rejected"
        improvement = None
    elif incumbent.infinite and challenger.infinite:
        promote = False
        reason = "both_reports_infinite"
        improvement = None
    else:
        assert incumbent.mean_target_surprisal_bits is not None
        assert challenger.mean_target_surprisal_bits is not None
        improvement = (
            incumbent.mean_target_surprisal_bits
            - challenger.mean_target_surprisal_bits
        )
        improvement = 0.0 if improvement == 0.0 else improvement
        promote = improvement > threshold
        reason = (
            "required_improvement_exceeded"
            if promote
            else "required_improvement_not_exceeded"
        )

    selected = challenger.candidate if promote else incumbent.candidate
    cases = [
        {"observation": observation, "target": incumbent.outcomes[observation][0]}
        for observation in sorted(incumbent.outcomes)
    ]
    evidence_id = canonical_digest(
        {
            "cases": cases,
            "evaluation": incumbent.evaluation,
            "schema_version": SCHEMA_VERSION,
        }
    )
    return {
        "challenger": challenger.candidate,
        "comparison": {
            "challenger": {
                "infinite": challenger.infinite,
                "mean_target_surprisal_bits": challenger.mean_target_surprisal_bits,
            },
            "incumbent": {
                "infinite": incumbent.infinite,
                "mean_target_surprisal_bits": incumbent.mean_target_surprisal_bits,
            },
            "mean_improvement_bits": improvement,
            "required_improvement_bits": threshold,
            "sample_count": len(cases),
        },
        "decision": "promote_challenger" if promote else "retain_incumbent",
        "evaluation": incumbent.evaluation,
        "evidence_id": evidence_id,
        "incumbent": incumbent.candidate,
        "reason": reason,
        "schema_version": SCHEMA_VERSION,
        "selected": selected,
    }


def _verify_task_case(
    raw_case: object,
    location: str,
) -> VerifiedTaskCase:
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
    probability = _probability(
        raw_case["target_probability"], f"{location}.target_probability"
    )
    measured = self_information(probability, base=2)
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
        reported = _nonnegative_number(
            raw_surprisal["value_bits"], f"{surprisal_location}.value_bits"
        )
        if not _same_number(reported, measured):
            raise ProtocolError(
                f"{surprisal_location}.value_bits does not match Metering"
            )

    return VerifiedTaskCase(
        case_id=case_id,
        evidence=normalize_json_value(raw_case["evidence"], f"{location}.evidence"),
        outcome=outcome,
        passed=passed,
        safety_passed=safety_passed,
        target_probability=probability,
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
    base_exact, _ = _number_as_float(value["base"], f"{location}.base")
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
    mean = _nonnegative_number(
        aggregate["mean_target_surprisal_bits"],
        f"{aggregate_location}.mean_target_surprisal_bits",
    )
    if not _same_number(mean, expected_mean):
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


def _select_task_reports(request: dict[str, object]) -> dict[str, object]:
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


def _process(source: str) -> dict[str, object]:
    request = _decode_json(source)
    if request.get("schema_version") == AGENT_SCHEMA_VERSION:
        return _select_task_reports(request)
    incumbent, challenger, threshold = decode_request(source)
    return select(incumbent, challenger, threshold)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        _process,
        arguments,
        error_rules=(
            (RequestError, "invalid_request"),
            (ProbabilityError, "invalid_probability"),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
