"""Schema-v1 forecast-loss pairwise selection instruction."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from metering import self_information

from apps.selection_gate.report_validation import (
    RequestError,
    nonnegative_number as _nonnegative_number,
    number_as_float as _number_as_float,
    probability as _probability,
    require_bool as _require_bool,
    require_exact_keys as _require_exact_keys,
    require_nonempty_string as _require_nonempty_string,
    same_number as _same_number,
)
from apps.stdio_connector import canonical_digest, decode_json_object

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class VerifiedReport:
    candidate: str
    evaluation: str
    infinite: bool
    mean_target_surprisal_bits: float | None
    outcomes: dict[str, tuple[str, float]]


def _decode_json(source: str) -> dict[str, object]:
    return decode_json_object(source, RequestError, parse_float=Decimal)


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
        raise RequestError(f"{location}.schema_version must be {SCHEMA_VERSION}")
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
            incumbent.mean_target_surprisal_bits - challenger.mean_target_surprisal_bits
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


def run_fixture_selection(source: str) -> dict[str, object]:
    incumbent, challenger, threshold = decode_request(source)
    return select(incumbent, challenger, threshold)


decode_document = _decode_json
