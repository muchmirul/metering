"""Named evidence aggregation, Pareto retention, and exact parent allocation."""

from __future__ import annotations

import math
import statistics
from fractions import Fraction
from typing import cast

from metering import ProbabilityError, entropy, kl_divergence

from apps.agent_protocol import (
    ProtocolError,
    normalize_json_value,
    require_exact_keys,
    require_sha256,
)
from apps._support.wire import canonical_json

from apps.population.population_protocol import (
    ALLOCATION_POLICY,
    RESOURCE_NAMES,
    PopulationError,
    PopulationState,
    RequestError,
    finite_or_infinite,
    nonnegative_integer,
    positive_integer,
    require_population_schema,
)


def _internal_number(document: object) -> float:
    value = cast(dict[str, object], document)
    return math.inf if value["infinite"] else float(value["value"])


def _candidate_aggregate(
    candidate_id: str,
    runs: list[dict[str, object]],
    configuration: dict[str, object],
) -> dict[str, object]:
    task_rates: list[float] = []
    passed_count = 0
    case_count = 0
    replicate_count = len(runs)
    survival = True
    behavior_rows: list[list[float]] = []
    information_values: list[float | None] = []
    costs = {name: 0 for name in RESOURCE_NAMES}
    weighted_surprisal: list[float] = []
    surprisal_count = 0
    infinite_surprisal = False

    for body in runs:
        evidence = cast(dict[str, object], body["evidence"])
        measurements = cast(dict[str, object], body["measurements"])
        task = cast(dict[str, int], evidence["task"])
        passed_count += task["passed_count"]
        case_count += task["case_count"]
        task_rates.append(float(measurements["task_rate"]))
        survival = survival and bool(measurements["survival_passed"])
        behavior_rows.append(cast(list[float], evidence["behavior_distribution"]))
        information_values.append(
            cast(float | None, measurements["information_value_bits"])
        )
        cost = cast(dict[str, int], evidence["cost"])
        for name in RESOURCE_NAMES:
            costs[name] += cost[name]
        run_surprisal = cast(
            dict[str, object], measurements["mean_target_surprisal_bits"]
        )
        if run_surprisal["infinite"]:
            infinite_surprisal = True
        else:
            weighted_surprisal.append(
                float(run_surprisal["value"]) * task["case_count"]
            )
        surprisal_count += task["case_count"]

    behavior = [
        math.fsum(row[index] for row in behavior_rows) / replicate_count
        for index in range(len(behavior_rows[0]))
    ]
    try:
        entropy(behavior)
    except ProbabilityError as exc:
        raise PopulationError(
            f"aggregate behavior distribution is invalid: {exc}"
        ) from exc
    policy = cast(dict[str, object], configuration["archive_policy"])
    kappa = float(policy["reliability_kappa"])
    mean_rate = math.fsum(task_rates) / replicate_count
    variability = statistics.stdev(task_rates) if replicate_count >= 2 else 0.0
    reliability = mean_rate - kappa * variability
    information = (
        None
        if any(item is None for item in information_values)
        else math.fsum(cast(list[float], information_values)) / replicate_count
    )
    mean_surprisal = (
        math.inf
        if infinite_surprisal
        else math.fsum(weighted_surprisal) / surprisal_count
    )
    return {
        "behavior_distribution": behavior,
        "candidate_id": candidate_id,
        "cost": costs,
        "information_value_bits": information,
        "mean_target_surprisal_bits": finite_or_infinite(mean_surprisal),
        "novelty_bits": {"infinite": False, "value": 0.0},
        "reliability": reliability,
        "replicate_count": replicate_count,
        "survival_passed": survival,
        "task": {
            "case_count": case_count,
            "passed_count": passed_count,
            "rate": passed_count / case_count,
        },
    }


def _dominates(
    challenger: dict[str, object],
    incumbent: dict[str, object],
    include_information: bool,
) -> bool:
    challenger_task = cast(dict[str, object], challenger["task"])
    incumbent_task = cast(dict[str, object], incumbent["task"])
    comparisons: list[tuple[object, object, str]] = [
        (
            Fraction(
                int(challenger_task["passed_count"]),
                int(challenger_task["case_count"]),
            ),
            Fraction(
                int(incumbent_task["passed_count"]),
                int(incumbent_task["case_count"]),
            ),
            "max",
        ),
        (float(challenger["reliability"]), float(incumbent["reliability"]), "max"),
        (
            _internal_number(challenger["novelty_bits"]),
            _internal_number(incumbent["novelty_bits"]),
            "max",
        ),
        (
            _internal_number(challenger["mean_target_surprisal_bits"]),
            _internal_number(incumbent["mean_target_surprisal_bits"]),
            "min",
        ),
    ]
    if include_information:
        comparisons.append(
            (
                float(challenger["information_value_bits"]),
                float(incumbent["information_value_bits"]),
                "max",
            )
        )
    challenger_cost = cast(dict[str, int], challenger["cost"])
    incumbent_cost = cast(dict[str, int], incumbent["cost"])
    comparisons.extend(
        (challenger_cost[name], incumbent_cost[name], "min") for name in RESOURCE_NAMES
    )
    no_worse = all(
        left >= right if direction == "max" else left <= right
        for left, right, direction in comparisons
    )
    strictly_better = any(
        left > right if direction == "max" else left < right
        for left, right, direction in comparisons
    )
    return no_worse and strictly_better


def _archive_rank(
    metric: dict[str, object], include_information: bool
) -> tuple[object, ...]:
    task = cast(dict[str, object], metric["task"])
    cost = cast(dict[str, int], metric["cost"])
    information = metric["information_value_bits"]
    information_rank = (
        -float(information) if include_information and information is not None else 0.0
    )
    return (
        -_internal_number(metric["novelty_bits"]),
        -Fraction(int(task["passed_count"]), int(task["case_count"])),
        -float(metric["reliability"]),
        information_rank,
        _internal_number(metric["mean_target_surprisal_bits"]),
        *(cost[name] for name in RESOURCE_NAMES),
        str(metric["candidate_id"]),
    )


def _archive_body(experiment_id: str, state: PopulationState) -> dict[str, object]:
    if experiment_id not in state.experiments:
        raise PopulationError(f"unknown archive experiment: {experiment_id}")
    experiment = state.experiments[experiment_id]
    if experiment["role"] != "development":
        raise PopulationError("final experiments cannot create selectable archives")
    grouped: dict[str, list[dict[str, object]]] = {}
    for body in state.runs:
        run = cast(dict[str, object], body["run"])
        if run["experiment_id"] == experiment_id:
            grouped.setdefault(str(run["candidate_id"]), []).append(body)
    aggregates = {
        candidate_id: _candidate_aggregate(
            candidate_id, candidate_runs, state.configuration
        )
        for candidate_id, candidate_runs in grouped.items()
    }
    viable = {
        candidate_id: metric
        for candidate_id, metric in aggregates.items()
        if metric["survival_passed"] is True
    }
    for candidate_id, metric in viable.items():
        distances: list[float] = []
        for other_id, other in viable.items():
            if other_id == candidate_id:
                continue
            try:
                distances.append(
                    kl_divergence(
                        cast(list[float], metric["behavior_distribution"]),
                        cast(list[float], other["behavior_distribution"]),
                    )
                )
            except ProbabilityError as exc:
                raise PopulationError(
                    f"cannot compare behavior distributions: {exc}"
                ) from exc
        novelty = min(distances) if distances else 0.0
        metric["novelty_bits"] = finite_or_infinite(novelty)

    include_information = experiment["information_objective"] is True
    if include_information and any(
        metric["information_value_bits"] is None for metric in viable.values()
    ):
        raise PopulationError(
            "experiment requires information evidence for every viable candidate"
        )
    frontier = [
        metric
        for candidate_id, metric in viable.items()
        if not any(
            other_id != candidate_id and _dominates(other, metric, include_information)
            for other_id, other in viable.items()
        )
    ]
    policy = cast(dict[str, object], state.configuration["archive_policy"])
    capacity = int(policy["capacity"])
    ranked = sorted(
        frontier, key=lambda metric: _archive_rank(metric, include_information)
    )
    selected_ids = {str(metric["candidate_id"]) for metric in ranked[:capacity]}
    members = sorted(
        (metric for metric in frontier if metric["candidate_id"] in selected_ids),
        key=lambda metric: str(metric["candidate_id"]),
    )
    frontier_ids = {str(metric["candidate_id"]) for metric in frontier}
    excluded: list[dict[str, str]] = []
    for candidate_id in sorted(state.candidates):
        if candidate_id in selected_ids:
            continue
        if candidate_id not in aggregates:
            reason = "unevaluated"
        elif candidate_id not in viable:
            reason = "infeasible"
        elif candidate_id not in frontier_ids:
            reason = "dominated"
        else:
            reason = "capacity"
        excluded.append({"candidate_id": candidate_id, "reason": reason})
    objectives = [
        {"direction": "maximize", "name": "task_rate"},
        {"direction": "maximize", "name": "reliability"},
        {"direction": "maximize", "name": "novelty_bits"},
        {"direction": "minimize", "name": "mean_target_surprisal_bits"},
    ]
    if include_information:
        objectives.append({"direction": "maximize", "name": "information_value_bits"})
    objectives.extend(
        {"direction": "minimize", "name": f"cost.{name}"} for name in RESOURCE_NAMES
    )
    return {
        "eligible_count": len(viable),
        "evaluated_count": len(aggregates),
        "excluded": excluded,
        "experiment_id": experiment_id,
        "members": members,
        "objectives": objectives,
        "policy": dict(policy),
    }


def decode_archive_request(
    value: dict[str, object], state: PopulationState
) -> dict[str, object]:
    try:
        require_exact_keys(value, {"experiment_id", "schema_version"}, "request")
        require_population_schema(value["schema_version"])
        experiment_id = require_sha256(value["experiment_id"], "request.experiment_id")
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc
    return _archive_body(experiment_id, state)


def _draw(value: object, location: str = "draw") -> dict[str, int]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(value, {"denominator", "numerator"}, location)
    denominator = positive_integer(value["denominator"], f"{location}.denominator")
    numerator = nonnegative_integer(value["numerator"], f"{location}.numerator")
    if numerator >= denominator:
        raise ProtocolError(f"{location}.numerator must be less than denominator")
    return {"denominator": denominator, "numerator": numerator}


def _allocation_body(value: object, state: PopulationState) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError("allocation record body must be a JSON object")
    require_exact_keys(value, {"request", "result"}, "allocation body")
    request = value["request"]
    if type(request) is not dict:
        raise ProtocolError("allocation body.request must be a JSON object")
    require_exact_keys(
        request, {"archive_record_id", "draw"}, "allocation body.request"
    )
    archive_id = require_sha256(
        request["archive_record_id"], "allocation body.request.archive_record_id"
    )
    draw = _draw(request["draw"], "allocation body.request.draw")
    if archive_id not in state.archives:
        raise PopulationError(f"unknown allocation archive: {archive_id}")
    archive = state.archives[archive_id]
    experiment_id = str(archive["experiment_id"])
    if state.latest_archive_by_experiment.get(experiment_id) != archive_id:
        raise PopulationError(
            "parent allocation must use the latest experiment archive"
        )
    latest_run = state.last_run_sequence_by_experiment.get(experiment_id, 0)
    if latest_run > state.archive_sequences[archive_id]:
        raise PopulationError(
            "parent allocation archive is stale after new experiment evidence"
        )
    members = cast(list[dict[str, object]], archive["members"])
    ordered = sorted(str(member["candidate_id"]) for member in members)
    if not ordered:
        raise PopulationError("cannot allocate a parent from an empty archive")
    selected = ordered[(draw["numerator"] * len(ordered)) // draw["denominator"]]
    expected_result = {
        "ordered_candidates": ordered,
        "policy": ALLOCATION_POLICY,
        "probability": {"denominator": len(ordered), "numerator": 1},
        "selected_candidate_id": selected,
    }
    normalized_result = normalize_json_value(value["result"], "allocation body.result")
    if canonical_json(normalized_result) != canonical_json(expected_result):
        raise ProtocolError(
            "allocation body.result does not match its archive and draw"
        )
    return {
        "request": {"archive_record_id": archive_id, "draw": draw},
        "result": expected_result,
    }


def decode_allocation_request(
    value: dict[str, object], state: PopulationState
) -> dict[str, object]:
    try:
        require_exact_keys(
            value, {"archive_record_id", "draw", "schema_version"}, "request"
        )
        require_population_schema(value["schema_version"])
        archive_id = require_sha256(
            value["archive_record_id"], "request.archive_record_id"
        )
        draw = _draw(value["draw"], "request.draw")
        if archive_id not in state.archives:
            raise PopulationError(f"unknown allocation archive: {archive_id}")
        archive = state.archives[archive_id]
        members = cast(list[dict[str, object]], archive["members"])
        ordered = sorted(str(member["candidate_id"]) for member in members)
        if not ordered:
            raise PopulationError("cannot allocate a parent from an empty archive")
        result = {
            "ordered_candidates": ordered,
            "policy": ALLOCATION_POLICY,
            "probability": {"denominator": len(ordered), "numerator": 1},
            "selected_candidate_id": ordered[
                (draw["numerator"] * len(ordered)) // draw["denominator"]
            ],
        }
        return _allocation_body(
            {
                "request": {"archive_record_id": archive_id, "draw": draw},
                "result": result,
            },
            state,
        )
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc


# Public owner-contract names used by replay and bounded outer sequencers.
normalize_allocation_body = _allocation_body
normalize_archive_body = _archive_body
normalize_draw = _draw
