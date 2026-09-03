"""Initialization and bounded execution runtime for Population Driver."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import cast

from apps._support.durable import fsync_directory
from apps.population.contract import (
    POPULATION_SCHEMA_VERSION,
    PopulationError,
    PopulationState,
    append_validated_record,
    decode_candidate_request,
    initialize as initialize_population,
    load_state as load_population_state,
    locked_state as locked_population_state,
)
from apps.population_driver.machine import (
    advance_pending,
    new_attempt,
    start_pending,
    update_pending,
)
from apps.population_driver.paths import population_root
from apps.population_driver.planner import final_phase_started, plan
from apps.population_driver.population_driver_protocol import (
    DRIVER_SCHEMA_VERSION,
    PopulationDriverError,
    controller_timeout_seconds,
    decode_request,
    decode_retry_request,
    total_cost,
)
from apps.population_driver.population_driver_state import (
    create_driver_ledger,
    locked_driver,
    receipt_reference_for_existing,
    remove_pending,
)
from apps.population_driver.receipts import controller_receipt_name
from apps.population_driver.replay import verify_context
from apps._support.wire import canonical_digest


def _append_initial_population(
    root: Path,
    config: dict[str, object],
) -> tuple[PopulationState, str, str]:
    population = cast(dict[str, object], config["population"])
    initial_parent = cast(dict[str, object], config["initial_parent"])
    try:
        initialize_population(
            root, cast(dict[str, object], population["configuration"])
        )
        with locked_population_state(root):
            state = load_population_state(root)
            candidate_body = decode_candidate_request(
                {
                    "artifact": initial_parent["artifact"],
                    "parents": [],
                    "schema_version": POPULATION_SCHEMA_VERSION,
                    "variation": {
                        "choice": {"source": "caller-provided-initial-parent"},
                        "policy_id": None,
                        "type": "seed-v1",
                    },
                },
                state,
            )
            candidate_record = append_validated_record(
                root, state, "candidate", candidate_body
            )
            experiment_body = {
                "experiment": population["experiment"],
                "experiment_id": population["experiment_id"],
            }
            experiment_record = append_validated_record(
                root, state, "experiment", experiment_body
            )
    except (PopulationError, ValueError) as exc:
        raise PopulationDriverError(str(exc)) from exc
    return (
        state,
        str(candidate_record["record_id"]),
        str(experiment_record["record_id"]),
    )


def _initialize(state_root: Path, config: dict[str, object]) -> None:
    if state_root.exists():
        raise PopulationDriverError(
            f"Population Driver state has no ledger but already exists: {state_root}"
        )
    temporary = state_root.with_name(f".{state_root.name}.init-{uuid.uuid4().hex}")
    try:
        temporary.mkdir(parents=False)
        population_state, candidate_record_id, _ = _append_initial_population(
            population_root(temporary), config
        )
        population = cast(dict[str, object], config["population"])
        initial_parent = cast(dict[str, object], config["initial_parent"])
        header = {
            "config_id": canonical_digest(config),
            "configuration": config,
            "experiment_id": population["experiment_id"],
            "initial_candidate_record_id": candidate_record_id,
            "kind": "population-driver",
            "parent_record_id": None,
            "population_head_record_id": population_state.head_id,
            "population_id": population_state.records[0]["record_id"],
            "schema_version": DRIVER_SCHEMA_VERSION,
            "seed_candidate_id": initial_parent["candidate_id"],
            "sequence": 0,
        }
        create_driver_ledger(temporary, header)
        os.replace(temporary, state_root)
        fsync_directory(state_root.parent)
    except OSError as exc:
        raise PopulationDriverError(
            f"cannot initialize Population Driver: {exc}"
        ) from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _summary(
    state_root: Path,
    context: dict[str, object],
    status: str,
) -> dict[str, object]:
    config = cast(dict[str, object], context["config"])
    population_config = cast(dict[str, object], config["population"])
    state = cast(PopulationState, context["population"])
    pending = cast(dict[str, object] | None, context["pending"])
    return {
        "allocation_count": len(state.allocations),
        "archive_count": len(state.archives),
        "candidate_count": len(state.candidates),
        "completed_rounds": len(cast(list[object], context["rounds"])),
        "config_id": context["config_id"],
        "experiment_id": population_config["experiment_id"],
        "final_evaluation_started": state.final_evaluation_started,
        "last_driver_record_id": cast(list[dict[str, object]], context["records"])[-1][
            "record_id"
        ],
        "pending_error": pending["last_error"] if pending is not None else None,
        "pending_intent_id": pending["intent_id"] if pending is not None else None,
        "population_head_record_id": state.head_id,
        "population_state_path": str(population_root(state_root)),
        "proposal_calls": context["proposal_calls"],
        "reserved_wall_seconds": context["reserved_wall_seconds"],
        "run_count": len(state.runs),
        "schema_version": DRIVER_SCHEMA_VERSION,
        "sqlite_index_used": False,
        "state_path": str(state_root),
        "status": status,
        "total_candidate_cost": total_cost(
            state.runs, str(population_config["experiment_id"])
        ),
    }


def _clear_committed_checkpoint(state_root: Path, context: dict[str, object]) -> bool:
    if context["committed_pending"] is None:
        return False
    remove_pending(state_root)
    return True


def _drive(
    state_root: Path,
    config: dict[str, object],
    *,
    execute_existing_pending: bool,
) -> dict[str, object]:
    allow_controller = execute_existing_pending
    while True:
        context = verify_context(state_root, config)
        if _clear_committed_checkpoint(state_root, context):
            continue
        action = plan(context, allow_controller=allow_controller)
        if action.kind == "stop":
            assert action.status is not None
            return _summary(state_root, context, action.status)
        if action.kind == "start_round":
            start_pending(state_root, context)
            allow_controller = True
            continue
        assert action.kind == "advance_pending"
        completed = advance_pending(
            state_root,
            context,
            execute_controller=action.execute_controller,
        )
        allow_controller = True
        if not completed:
            refreshed = verify_context(state_root, config)
            return _summary(state_root, refreshed, "pending_round")


def run_population_driver(source: str, state_root: Path) -> dict[str, object]:
    config = decode_request(source)
    state_root = state_root.expanduser().absolute()
    with locked_driver(state_root):
        if not (state_root / "driver.jsonl").exists():
            _initialize(state_root, config)
        return _drive(
            state_root,
            config,
            execute_existing_pending=False,
        )


def retry_population_driver(source: str, state_root: Path) -> dict[str, object]:
    retry = decode_retry_request(source)
    state_root = state_root.expanduser().absolute()
    with locked_driver(state_root):
        context = verify_context(state_root)
        if _clear_committed_checkpoint(state_root, context):
            context = verify_context(state_root)
        pending = cast(dict[str, object] | None, context["pending"])
        if pending is None:
            raise PopulationDriverError("there is no pending round to retry")
        if pending["intent_id"] != retry["intent_id"]:
            raise PopulationDriverError("retry intent_id does not match pending state")
        if pending["stage"] != "controller_pending":
            raise PopulationDriverError(
                "retry is only valid for an indeterminate Controller attempt"
            )
        attempts = cast(list[dict[str, object]], pending["attempts"])
        receipt_name = controller_receipt_name(str(attempts[-1]["attempt_id"]))
        if receipt_reference_for_existing(state_root, receipt_name) is not None:
            raise PopulationDriverError(
                "Controller receipt exists; use run to resume without another model call"
            )
        config = cast(dict[str, object], context["config"])
        population_state = cast(PopulationState, context["population"])
        if final_phase_started(population_state):
            raise PopulationDriverError("final evidence seals the pending retry")
        if population_state.head_id != pending["population_start_record_id"]:
            raise PopulationDriverError(
                "Population state advanced after the pending Controller intent"
            )
        limits = cast(dict[str, object], config["limits"])
        if int(context["proposal_calls"]) >= int(limits["max_proposal_calls"]):
            raise PopulationDriverError("proposal call limit forbids this retry")
        controller_timeout = controller_timeout_seconds(config)
        if int(context["reserved_wall_seconds"]) + controller_timeout > int(
            limits["max_wall_seconds"]
        ):
            raise PopulationDriverError("wall reservation limit forbids this retry")
        attempts = [
            *attempts,
            new_attempt(
                str(pending["intent_id"]),
                len(attempts) + 1,
                str(retry["reason"]),
                controller_timeout,
            ),
        ]
        update_pending(
            state_root,
            pending,
            attempts=attempts,
            last_error=None,
        )
        return _drive(
            state_root,
            config,
            execute_existing_pending=True,
        )


def verify_population_driver(state_root: Path) -> dict[str, object]:
    state_root = state_root.expanduser().absolute()
    with locked_driver(state_root):
        context = verify_context(state_root)
        if _clear_committed_checkpoint(state_root, context):
            context = verify_context(state_root)
        return _summary(state_root, context, "verified")
