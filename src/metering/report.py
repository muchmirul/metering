"""Offline verification and meters over a replayed Metering run.

A report is a pure calculation.  It reads the three raw artifacts, replays them
with :mod:`metering.replay`, and returns three separate readings.

The verifier answers whether the task was completed, using exact conditions and
no language model.  The resource meter counts what was spent, keeping each unit
in its own column.  The information meter measures how much of the initial
uncertainty the delivered diagnostic results actually removed.  None of the
three is folded into an overall score, because correctness and cost are not
interchangeable and only the reader knows how to weigh them.

Changing anything in this module changes what a saved run means, but it cannot
change the run itself.  Meters run after execution and read artifacts that are
already written and hashed.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .events import Diagnose, DiagnosticObservation, Event, RawActionCost
from .provenance import METER_VERSION
from .replay import ReplayState, ReplayedInteraction, replay_trace
from .schema import (
    EVENT_INTERACTION,
    EVENT_PROTOCOL_ERROR,
    EVENT_RUN_STARTED,
    EVENT_TERMINATION,
    MANIFEST_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    TERMINATION_BUDGET_EXHAUSTED,
    TERMINATION_HARNESS_CRASH,
    TERMINATION_INVALID_ACTION,
    TERMINATION_NORMAL,
    ReportError,
    StrictFields,
)
from .trace import RunPaths, read_events, read_json_bytes, write_json_atomic

__all__ = [
    "EVENT_INTERACTION",
    "EVENT_PROTOCOL_ERROR",
    "EVENT_RUN_STARTED",
    "EVENT_TERMINATION",
    "MANIFEST_SCHEMA_VERSION",
    "REPORT_SCHEMA_VERSION",
    "TERMINATION_BUDGET_EXHAUSTED",
    "TERMINATION_HARNESS_CRASH",
    "TERMINATION_INVALID_ACTION",
    "TERMINATION_NORMAL",
    "ReplayState",
    "ReplayedInteraction",
    "ReportError",
    "aggregate_reports",
    "build_report",
    "regenerate_report",
    "replay_trace",
]

_check = StrictFields(ReportError)

_RESOURCE_FIELDS = (
    "diagnostic_observations",
    "repair_actions",
    "verification_actions",
    "total_actions",
    "action_budget",
    "budget_exhaustion",
)

# A complete calibration suite has one run for each of eight equally likely
# faults. Kraft's inequality makes 24 the minimum total external path length of
# a binary decision tree with eight leaves.
_MINIMUM_SUITE_DIAGNOSTIC_OBSERVATIONS = 24


def _correctness_report(state: ReplayState) -> dict[str, Any]:
    """Report the four exact completion conditions and their conjunction.

    The conditions stay visible individually so that a failure says which part
    went wrong.  A run that repaired the right fault but never verified it is a
    different mistake from one that verified an outdated repair, and collapsing
    both into a single false would hide that.
    """

    verified_after_final_repair = state.final_repair_step is not None and any(
        step > state.final_repair_step for step in state.verification_steps
    )
    conditions = {
        "selected_repair_matches_hidden_fault": (
            state.final_repair == state.hidden_fault_id
        ),
        "verification_occurred_after_final_repair": verified_after_final_repair,
        "harness_terminated_normally": (
            state.termination_reason == TERMINATION_NORMAL
        ),
        "action_budget_was_respected": state.actions_used <= state.action_budget,
    }
    return {**conditions, "overall_task_success": all(conditions.values())}


def _resource_report(state: ReplayState, events: Sequence[Event]) -> dict[str, Any]:
    """Sum the per-event raw costs and check them against the replayed total."""

    total = RawActionCost.zero()
    for event in events:
        total = total + event.resources
    if total.total_actions != state.actions_used:
        raise ReportError("summed total action cost contradicts replay state")
    return {
        **total.to_dict(),
        "action_budget": state.action_budget,
        "budget_exhaustion": (
            state.termination_reason == TERMINATION_BUDGET_EXHAUSTED
        ),
    }


def _entropy(candidate_count: int) -> float:
    """Return the entropy in bits of a uniform choice among the candidates."""

    if type(candidate_count) is not int or candidate_count < 1:
        raise ReportError("an impossible diagnostic result eliminated every state")
    return math.log2(candidate_count)


def _information_report(state: ReplayState) -> dict[str, Any]:
    """Measure how much uncertainty the delivered diagnostic results removed.

    The prior is uniform over the eight declared states, which puts the initial
    uncertainty at three bits.  Each delivered result narrows the candidate set,
    and the bits removed are the drop in entropy that the narrowing produced.

    Only delivered diagnostic results count.  Choosing a test is an intervention
    rather than evidence, so it removes nothing on its own, and repair,
    verification, and finish carry no diagnostic content.  A repeated test
    therefore removes zero bits, which is exactly the waste the meter exists to
    expose.
    """

    candidates = list(state.public_instance.fault_ids)
    initial_uncertainty = _entropy(len(candidates))
    progression: list[dict[str, Any]] = []

    for item in state.interactions:
        if not isinstance(item.action, Diagnose):
            continue
        if type(item.observation) is not DiagnosticObservation:
            raise ReportError("replay lost the typed diagnostic observation")
        test = state.public_instance.diagnostic_test(item.action.test_id)
        if test is None:
            raise ReportError("diagnostic test is absent from public model")
        before_count = len(candidates)
        candidates = [
            fault_id
            for fault_id in candidates
            if test.outcome(fault_id) is item.observation.positive
        ]
        if not candidates:
            raise ReportError("diagnostic result is impossible under trace history")
        before_uncertainty = _entropy(before_count)
        after_uncertainty = _entropy(len(candidates))
        progression.append(
            {
                "diagnostic_index": len(progression) + 1,
                "event_step": item.event_step,
                "test_id": item.action.test_id,
                "positive": item.observation.positive,
                "candidate_count_before": before_count,
                "candidate_count_after": len(candidates),
                "uncertainty_before_bits": before_uncertainty,
                "uncertainty_after_bits": after_uncertainty,
                "uncertainty_removed_bits": before_uncertainty - after_uncertainty,
            }
        )

    remaining_uncertainty = _entropy(len(candidates))
    removed = initial_uncertainty - remaining_uncertainty
    count = len(progression)
    return {
        "name": "diagnostic_information_exposure",
        "unit": "bits",
        "prior": "uniform_over_declared_hidden_states",
        "initial_uncertainty_bits": initial_uncertainty,
        "remaining_uncertainty_bits": remaining_uncertainty,
        "total_uncertainty_removed_bits": removed,
        "diagnostic_observations": count,
        # A run with no diagnostics reports null rather than zero, because it
        # has no ratio rather than a ratio that happens to be zero.
        "uncertainty_removed_per_diagnostic_observation_bits": (
            removed / count if count else None
        ),
        "progression": progression,
    }


def build_report(
    manifest: Mapping[str, Any],
    events: Sequence[Event],
    reference: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """Build a canonical report as a pure calculation over bound artifacts."""

    state = replay_trace(manifest, events, reference, artifact_bytes=artifact_bytes)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "meter_version": METER_VERSION,
        "artifact_set_id": state.artifact_set_id,
        "artifact_hashes": {"algorithm": "sha256", **dict(state.artifact_hashes)},
        "run_id": manifest["run_id"],
        "world_id": state.public_instance.world_id,
        "world_version": state.public_instance.world_version,
        "instance_id": state.public_instance.instance_id,
        "instance_version": state.public_instance.instance_version,
        "termination_reason": state.termination_reason,
        "correctness": _correctness_report(state),
        "resources": _resource_report(state, events),
        "diagnostic_information": _information_report(state),
        # Every reading above is conditional on the declarations below.  Naming
        # the conditions inside the artifact keeps a number from being quoted
        # later as if it described agents in general.
        "scope": {
            "conditional_on": [
                "declared_hidden_fault_world",
                "uniform_prior",
                "deterministic_public_observation_model",
                "declared_policy_configuration",
                "declared_action_budget",
            ],
            "does_not_claim": [
                "that_a_model_understood_the_observations",
                "universal_harness_quality",
                "hostile_code_sandbox_enforcement",
                "survival_of_nonreturning_or_hard_exit_callbacks",
                "an_overall_agent_score",
            ],
        },
    }


def aggregate_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate raw units and efficiency across a complete calibration suite.

    Suite efficiency divides the total bits removed by the total diagnostics
    spent.  Averaging the per-run ratios instead would give a cheap run and an
    expensive run equal weight, which would report a suite as more efficient
    than the observations it actually paid for.

    Excess observations use the 24-observation binary-tree bound for all eight
    hidden states.  The value belongs only here, never in a per-run report: a
    short path can beat the worst-case depth without beating the suite bound.
    """

    totals = dict.fromkeys(
        ("diagnostic_observations", "repair_actions", "verification_actions",
         "total_actions"),
        0,
    )
    information_total = 0.0
    successful_runs = 0
    budget_exhausted_runs = 0

    for index, report in enumerate(reports):
        _check.mapping(report, f"report {index}")
        resources = _check.exact_keys(
            report.get("resources"), _RESOURCE_FIELDS, f"report {index}.resources"
        )
        information = _check.mapping(
            report.get("diagnostic_information"),
            f"report {index}.diagnostic_information",
        )
        correctness = _check.mapping(
            report.get("correctness"), f"report {index}.correctness"
        )
        for name in totals:
            totals[name] += _check.integer(
                resources[name], f"report {index} {name}"
            )
        removed = information.get("total_uncertainty_removed_bits")
        if type(removed) not in {int, float}:
            raise ReportError(f"report {index} information removed must be numeric")
        removed_float = float(removed)
        if not math.isfinite(removed_float) or removed_float < 0:
            raise ReportError(f"report {index} information removed is invalid")
        information_total += removed_float
        if correctness.get("overall_task_success") is True:
            successful_runs += 1
        if _check.boolean(
            resources["budget_exhaustion"], f"report {index} budget_exhaustion"
        ):
            budget_exhausted_runs += 1

    diagnostic_total = totals["diagnostic_observations"]
    return {
        "run_count": len(reports),
        "successful_runs": successful_runs,
        "resources": {**totals, "budget_exhausted_runs": budget_exhausted_runs},
        "diagnostic_information": {
            "total_uncertainty_removed_bits": information_total,
            "bits_per_diagnostic_observation": (
                information_total / diagnostic_total if diagnostic_total else None
            ),
            "excess_observations": (
                diagnostic_total - _MINIMUM_SUITE_DIAGNOSTIC_OBSERVATIONS
            ),
            "aggregation": "ratio_of_sums",
        },
    }


def regenerate_report(run_dir: str | Path) -> dict[str, Any]:
    """Rebuild ``report.json`` from strict, bound raw artifact bytes.

    The exact bytes of all three inputs are read from disk and passed to the
    meters, and the new report replaces the old one only after every check has
    passed.  A run whose artifacts disagree keeps whatever report it had.
    """

    paths = RunPaths.at(run_dir)
    manifest, manifest_bytes = read_json_bytes(paths.manifest)
    reference, reference_bytes = read_json_bytes(paths.reference)
    try:
        events_bytes = paths.events.read_bytes()
    except OSError as exc:
        raise ReportError(f"cannot read events artifact: {exc}") from exc
    report = build_report(
        manifest,
        read_events(paths.events),
        reference,
        artifact_bytes={
            "manifest": manifest_bytes,
            "events": events_bytes,
            "reference": reference_bytes,
        },
    )
    write_json_atomic(paths.report, report)
    return report
