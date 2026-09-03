"""Pure next-action planner for the bounded Population Driver machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from apps.population.contract import RESOURCE_NAMES, PopulationState
from apps.population_driver.population_driver_protocol import (
    controller_timeout_seconds,
    total_cost,
)
from apps.population_driver.stopping import state_reaches_development_goal

ActionKind = Literal["advance_pending", "start_round", "stop"]


@dataclass(frozen=True)
class DriverAction:
    """One explicit control instruction emitted from fully replayed state."""

    kind: ActionKind
    execute_controller: bool = False
    status: str | None = None


def _resource_limit_status(context: dict[str, object]) -> str | None:
    config = cast(dict[str, object], context["config"])
    population_config = cast(dict[str, object], config["population"])
    experiment = cast(dict[str, object], population_config["experiment"])
    state = cast(PopulationState, context["population"])
    used = total_cost(state.runs, str(population_config["experiment_id"]))
    per_candidate = cast(dict[str, int], experiment["budget"])
    limits = cast(dict[str, object], config["limits"])
    maximum = cast(dict[str, int], limits["max_total_candidate_cost"])
    if any(
        used[name] + 2 * per_candidate[name] > maximum[name] for name in RESOURCE_NAMES
    ):
        return "candidate_cost_limit"
    return None


def final_phase_started(state: PopulationState) -> bool:
    """Return whether final work has begun, before or after its sealing run."""

    return state.final_evaluation_started or any(
        experiment["role"] == "final" for experiment in state.experiments.values()
    )


def stop_status(context: dict[str, object]) -> str | None:
    """Return the first deterministic stop reason, or ``None`` to continue."""

    config = cast(dict[str, object], context["config"])
    limits = cast(dict[str, object], config["limits"])
    state = cast(PopulationState, context["population"])
    rounds = cast(list[object], context["rounds"])
    if final_phase_started(state):
        return "final_evidence_sealed"
    if (
        state.head_id == context["last_population_head"]
        and state_reaches_development_goal(config, state)
    ):
        return "development_goal_reached"
    if len(rounds) >= int(limits["max_rounds"]):
        return "round_limit"
    if state.head_id != context["last_population_head"]:
        return "population_state_advanced"
    if not context["expected_parent_id"]:
        return "empty_archive"
    if int(context["proposal_calls"]) >= int(limits["max_proposal_calls"]):
        return "proposal_call_limit"
    resource_status = _resource_limit_status(context)
    if resource_status is not None:
        return resource_status
    controller_timeout = controller_timeout_seconds(config)
    evidence_timeout = int(
        cast(dict[str, object], config["evidence_adapter"])["timeout_seconds"]
    )
    if int(
        context["reserved_wall_seconds"]
    ) + controller_timeout + evidence_timeout > int(limits["max_wall_seconds"]):
        return "wall_reservation_limit"
    return None


def plan(context: dict[str, object], *, allow_controller: bool) -> DriverAction:
    """Plan exactly one durable action from replayed state."""

    pending = cast(dict[str, object] | None, context["pending"])
    if pending is not None:
        population = cast(PopulationState, context["population"])
        if final_phase_started(population):
            return DriverAction("stop", status="final_evidence_sealed")
        if (
            pending["stage"] in {"controller_pending", "controller_complete"}
            and population.head_id != pending["population_start_record_id"]
        ):
            return DriverAction("stop", status="population_state_advanced")
        return DriverAction(
            "advance_pending",
            execute_controller=allow_controller,
        )
    status = stop_status(context)
    if status is not None:
        return DriverAction("stop", status=status)
    return DriverAction("start_round")
