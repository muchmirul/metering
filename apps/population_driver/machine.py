"""Effect interpreter for one Population Driver state-machine action."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

from apps.agent_protocol import ProtocolError, run_adapter
from apps.population.contract import (
    POPULATION_SCHEMA_VERSION,
    PopulationError,
    PopulationState,
    append_validated_record,
    decode_allocation_request,
    decode_archive_request,
    decode_candidate_request,
    load_state as load_population_state,
    locked_state as locked_population_state,
)
from apps.population_driver.paths import population_root
from apps.population_driver.population_driver_protocol import (
    CONTROLLER_RECEIPT_SCHEMA,
    DRIVER_SCHEMA_VERSION,
    EVIDENCE_RECEIPT_SCHEMA,
    PopulationDriverError,
    controller_request,
    controller_timeout_seconds,
    decode_evidence_adapter_response,
    evidence_adapter_request,
    population_run_body,
    validate_controller_result,
)
from apps.population_driver.population_driver_state import (
    append_driver_record,
    receipt_reference_for_existing,
    remove_pending,
    write_pending,
    write_receipt,
)
from apps.population_driver.receipts import (
    controller_receipt_document,
    controller_receipt_name,
    evidence_receipt_document,
    evidence_receipt_name,
)
from apps.population_driver.stopping import archive_reaches_development_goal
from apps._support.process import (
    JsonProcessError,
    run_json_process,
)
from apps._support.wire import (
    canonical_digest,
    canonical_json,
    decode_json_object,
)

ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "apps/controller/controller.py"


def new_attempt(
    intent_id: str,
    ordinal: int,
    reason: str,
    controller_timeout: int,
) -> dict[str, object]:
    retry = ordinal > 1
    return {
        "attempt_id": canonical_digest(
            {
                "intent_id": intent_id,
                "ordinal": ordinal,
                "reason": reason,
                "retry": retry,
            }
        ),
        "ordinal": ordinal,
        "reason": reason,
        "retry": retry,
        "wall_reservation_seconds": controller_timeout,
    }


def start_pending(
    state_root: Path,
    context: dict[str, object],
) -> dict[str, object]:
    config = cast(dict[str, object], context["config"])
    state = cast(PopulationState, context["population"])
    parent_id = str(context["expected_parent_id"])
    allocation_id = cast(str | None, context["expected_allocation_id"])
    round_number = len(cast(list[object], context["rounds"])) + 1
    parent = state.candidates[parent_id]
    request = controller_request(
        config,
        parent,
        round_number,
        cast(dict[str, object] | None, context["previous_feedback"]),
        parent_allocation_record_id=allocation_id,
    )
    intent_id = canonical_digest(
        {
            "config_id": context["config_id"],
            "controller_request": request,
            "parent_allocation_record_id": allocation_id,
            "parent_candidate_id": parent_id,
            "population_start_record_id": state.head_id,
            "round": round_number,
        }
    )
    evidence_timeout = int(
        cast(dict[str, object], config["evidence_adapter"])["timeout_seconds"]
    )
    return write_pending(
        state_root,
        {
            "attempts": [
                new_attempt(
                    intent_id,
                    1,
                    "initial bounded round attempt",
                    controller_timeout_seconds(config),
                )
            ],
            "config_id": context["config_id"],
            "controller_receipt": None,
            "controller_request": request,
            "evidence_attempts": 0,
            "evidence_receipt": None,
            "evidence_wall_reservation_seconds": evidence_timeout,
            "intent_id": intent_id,
            "last_error": None,
            "parent_allocation_record_id": allocation_id,
            "parent_candidate_id": parent_id,
            "population_start_record_id": state.head_id,
            "population_start_sequence": len(state.records) - 1,
            "round": round_number,
            "schema_version": DRIVER_SCHEMA_VERSION,
            "stage": "controller_pending",
        },
    )


def pending_body(pending: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in pending.items() if key not in {"pending_id"}}


def update_pending(
    state_root: Path,
    pending: dict[str, object],
    **changes: object,
) -> dict[str, object]:
    body = pending_body(pending)
    body.update(changes)
    return write_pending(state_root, body)


def error_detail(error: BaseException) -> str:
    message = str(error).strip()
    return message if message else error.__class__.__name__


def run_controller_attempt(
    state_root: Path,
    config: dict[str, object],
    pending: dict[str, object],
) -> dict[str, object]:
    attempts = cast(list[dict[str, object]], pending["attempts"])
    attempt = attempts[-1]
    name = controller_receipt_name(str(attempt["attempt_id"]))
    existing = receipt_reference_for_existing(state_root, name)
    if existing is not None:
        try:
            controller_receipt_document(
                state_root,
                existing,
                expected_request=cast(dict[str, object], pending["controller_request"]),
                config=config,
                attempts=attempts,
            )
        except PopulationDriverError:
            raise
        return update_pending(
            state_root,
            pending,
            controller_receipt=existing,
            last_error=None,
            stage="controller_complete",
        )
    request = cast(dict[str, object], pending["controller_request"])
    try:
        output = run_json_process(
            [sys.executable, str(CONTROLLER)],
            request,
            cwd=ROOT,
            timeout_seconds=controller_timeout_seconds(config),
        )
        result = decode_json_object(output, PopulationDriverError)
        if output != canonical_json(result) + "\n":
            raise PopulationDriverError("Controller returned non-canonical JSON")
        validate_controller_result(request, result, config)
        document = {
            "attempt_id": attempt["attempt_id"],
            "controller_request": request,
            "controller_result": result,
            "receipt_schema": CONTROLLER_RECEIPT_SCHEMA,
        }
        reference = write_receipt(state_root, name, document)
    except (JsonProcessError, PopulationDriverError, ProtocolError, OSError) as exc:
        return update_pending(
            state_root,
            pending,
            last_error=f"Controller attempt requires explicit retry: {error_detail(exc)}",
        )
    return update_pending(
        state_root,
        pending,
        controller_receipt=reference,
        last_error=None,
        stage="controller_complete",
    )


def run_evidence_adapter(
    state_root: Path,
    config: dict[str, object],
    pending: dict[str, object],
    context: dict[str, object],
) -> dict[str, object]:
    attempts = cast(list[dict[str, object]], pending["attempts"])
    attempt_id = str(attempts[-1]["attempt_id"])
    name = evidence_receipt_name(attempt_id)
    controller_reference = cast(dict[str, object], pending["controller_receipt"])
    _, controller_result, validation = controller_receipt_document(
        state_root,
        controller_reference,
        expected_request=cast(dict[str, object], pending["controller_request"]),
        config=config,
        attempts=attempts,
    )
    parent_id = str(cast(dict[str, object], validation["parent"])["candidate_id"])
    child_id = str(cast(dict[str, object], validation["child"])["candidate_id"])
    existing = receipt_reference_for_existing(state_root, name)
    if existing is not None:
        evidence_receipt_document(
            state_root,
            existing,
            config=config,
            controller_reference=controller_reference,
            controller_result=controller_result,
            round_number=int(pending["round"]),
            candidate_ids={parent_id, child_id},
        )
        return update_pending(
            state_root,
            pending,
            evidence_receipt=existing,
            last_error=None,
            stage="evidence_complete",
        )
    adapter_request = evidence_adapter_request(
        config=config,
        controller_receipt=controller_reference,
        controller_result=controller_result,
        round_number=int(pending["round"]),
    )
    adapter = cast(dict[str, object], config["evidence_adapter"])
    adapter_timeout = int(adapter["timeout_seconds"])
    evidence_attempts = int(pending["evidence_attempts"])
    if evidence_attempts > 0:
        limits = cast(dict[str, object], config["limits"])
        if int(context["reserved_wall_seconds"]) + adapter_timeout > int(
            limits["max_wall_seconds"]
        ):
            return update_pending(
                state_root,
                pending,
                last_error="evidence adapter wall reservation limit reached",
            )
        pending = update_pending(
            state_root,
            pending,
            evidence_wall_reservation_seconds=(
                int(pending["evidence_wall_reservation_seconds"]) + adapter_timeout
            ),
        )
    pending = update_pending(
        state_root,
        pending,
        evidence_attempts=evidence_attempts + 1,
        last_error=None,
    )
    try:
        response = run_adapter(
            "Population Driver evidence adapter",
            cast(list[str], adapter["command"]),
            adapter_request,
            timeout_seconds=adapter_timeout,
            cwd=ROOT,
        )
        population = cast(dict[str, object], config["population"])
        decode_evidence_adapter_response(
            response,
            candidate_ids={parent_id, child_id},
            experiment=cast(dict[str, object], population["experiment"]),
        )
        reference = write_receipt(
            state_root,
            name,
            {
                "evidence_request": adapter_request,
                "evidence_response": response,
                "receipt_schema": EVIDENCE_RECEIPT_SCHEMA,
            },
        )
    except (ProtocolError, PopulationDriverError, OSError) as exc:
        return update_pending(
            state_root,
            pending,
            last_error=f"evidence adapter can be resumed: {error_detail(exc)}",
        )
    return update_pending(
        state_root,
        pending,
        evidence_receipt=reference,
        last_error=None,
        stage="evidence_complete",
    )


def ensure_population_record(
    root: Path,
    state: PopulationState,
    sequence: int,
    kind: str,
    body: dict[str, object],
) -> tuple[dict[str, object], int]:
    if len(state.records) > sequence:
        record = state.records[sequence]
        if record.get("kind") != kind or canonical_json(
            record.get("body")
        ) != canonical_json(body):
            raise PopulationDriverError(
                f"Population record {sequence} conflicts with pending {kind} ingestion"
            )
        return record, sequence + 1
    if len(state.records) != sequence:
        raise PopulationDriverError("Population ledger has an impossible sequence gap")
    try:
        append_validated_record(root, state, kind, body)
    except PopulationError as exc:
        raise PopulationDriverError(str(exc)) from exc
    return state.records[-1], sequence + 1


def ingest_population_round(
    state_root: Path,
    config: dict[str, object],
    pending: dict[str, object],
) -> dict[str, object]:
    attempts = cast(list[dict[str, object]], pending["attempts"])
    controller_reference = cast(dict[str, object], pending["controller_receipt"])
    _, controller_result, validation = controller_receipt_document(
        state_root,
        controller_reference,
        expected_request=cast(dict[str, object], pending["controller_request"]),
        config=config,
        attempts=attempts,
    )
    parent = cast(dict[str, object], validation["parent"])
    child = cast(dict[str, object], validation["child"])
    parent_id = str(parent["candidate_id"])
    child_id = str(child["candidate_id"])
    evidence_reference = cast(dict[str, object], pending["evidence_receipt"])
    _, evidence = evidence_receipt_document(
        state_root,
        evidence_reference,
        config=config,
        controller_reference=controller_reference,
        controller_result=controller_result,
        round_number=int(pending["round"]),
        candidate_ids={parent_id, child_id},
    )
    population = cast(dict[str, object], config["population"])
    experiment_id = str(population["experiment_id"])
    round_number = int(pending["round"])
    root = population_root(state_root)
    try:
        with locked_population_state(root):
            state = load_population_state(root)
            start_sequence = int(pending["population_start_sequence"])
            if (
                start_sequence >= len(state.records)
                or state.records[start_sequence].get("record_id")
                != pending["population_start_record_id"]
            ):
                raise PopulationDriverError(
                    "Population ledger no longer contains the pending start head"
                )
            sequence = start_sequence + 1
            child_record_id: str | None = None
            existing_child_record_id = state.candidate_record_ids.get(child_id)
            existing_child_sequence: int | None = None
            if existing_child_record_id is not None:
                existing_child_record = state.record(existing_child_record_id)
                if existing_child_record is None:
                    raise PopulationDriverError(
                        "child candidate record is absent from Population state"
                    )
                existing_child_sequence = int(existing_child_record["sequence"])
                if state.candidates[child_id] != child:
                    raise PopulationDriverError("known child candidate changed content")
            if existing_child_record_id is None or (
                existing_child_sequence is not None
                and existing_child_sequence > start_sequence
            ):
                candidate_body = decode_candidate_request(
                    {
                        "artifact": child["artifact"],
                        "parents": [parent_id],
                        "schema_version": POPULATION_SCHEMA_VERSION,
                        "variation": {
                            "choice": {
                                "controller_proposal_id": validation["proposal_id"],
                                "round": round_number,
                                "round_intent_id": pending["intent_id"],
                            },
                            "policy_id": config["mutation_policy_id"],
                            "type": "mutation-v1",
                        },
                    },
                    state,
                )
                candidate_record, sequence = ensure_population_record(
                    root, state, sequence, "candidate", candidate_body
                )
                child_record_id = str(candidate_record["record_id"])

            parent_run_body = population_run_body(
                candidate_id=parent_id,
                experiment_id=experiment_id,
                replicate_id=f"round-{round_number:06d}-incumbent",
                report_evidence=cast(dict[str, object], validation["parent_evidence"]),
                adapter_evidence=evidence[parent_id],
                evidence_reference=evidence_reference,
                state=state,
            )
            parent_run_record, sequence = ensure_population_record(
                root, state, sequence, "run", parent_run_body
            )
            child_run_body = population_run_body(
                candidate_id=child_id,
                experiment_id=experiment_id,
                replicate_id=f"round-{round_number:06d}-challenger",
                report_evidence=cast(dict[str, object], validation["child_evidence"]),
                adapter_evidence=evidence[child_id],
                evidence_reference=evidence_reference,
                state=state,
            )
            child_run_record, sequence = ensure_population_record(
                root, state, sequence, "run", child_run_body
            )
            archive_body = decode_archive_request(
                {
                    "experiment_id": experiment_id,
                    "schema_version": POPULATION_SCHEMA_VERSION,
                },
                state,
            )
            archive_record, sequence = ensure_population_record(
                root, state, sequence, "archive", archive_body
            )
            members = cast(list[dict[str, object]], archive_body["members"])
            member_ids = [str(member["candidate_id"]) for member in members]
            allocation_record: dict[str, object] | None = None
            limits = cast(dict[str, object], config["limits"])
            if (
                members
                and round_number < int(limits["max_rounds"])
                and not archive_reaches_development_goal(config, archive_body)
            ):
                draws = cast(list[dict[str, int]], config["allocation_draws"])
                allocation_body = decode_allocation_request(
                    {
                        "archive_record_id": archive_record["record_id"],
                        "draw": draws[round_number - 1],
                        "schema_version": POPULATION_SCHEMA_VERSION,
                    },
                    state,
                )
                allocation_record, sequence = ensure_population_record(
                    root, state, sequence, "allocation", allocation_body
                )
            if len(state.records) != sequence:
                raise PopulationDriverError(
                    "Population ledger contains records not owned by the pending round"
                )
    except (PopulationError, ValueError) as exc:
        if isinstance(exc, PopulationDriverError):
            raise
        raise PopulationDriverError(str(exc)) from exc

    references = {
        "allocation": (
            allocation_record["record_id"] if allocation_record is not None else None
        ),
        "archive": archive_record["record_id"],
        "candidate": child_record_id,
        "challenger_run": child_run_record["record_id"],
        "incumbent_run": parent_run_record["record_id"],
    }
    return {
        "archive_member_candidate_ids": member_ids,
        "next_allocation_record_id": references["allocation"],
        "population_head_record_id": (
            references["allocation"] or references["archive"]
        ),
        "population_record_ids": references,
        "validation": validation,
    }


def complete_pending_round(
    state_root: Path,
    context: dict[str, object],
    pending: dict[str, object],
) -> dict[str, object]:
    config = cast(dict[str, object], context["config"])
    ingested = ingest_population_round(state_root, config, pending)
    validation = cast(dict[str, object], ingested["validation"])
    child = cast(dict[str, object], validation["child"])
    previous_record = cast(list[dict[str, object]], context["records"])[-1]
    body = {
        "archive_member_candidate_ids": ingested["archive_member_candidate_ids"],
        "attempts": pending["attempts"],
        "child_candidate_id": child["candidate_id"],
        "controller_receipt": pending["controller_receipt"],
        "evidence_attempts": pending["evidence_attempts"],
        "evidence_receipt": pending["evidence_receipt"],
        "evidence_wall_reservation_seconds": pending[
            "evidence_wall_reservation_seconds"
        ],
        "intent_id": pending["intent_id"],
        "kind": "round",
        "next_allocation_record_id": ingested["next_allocation_record_id"],
        "parent_allocation_record_id": pending["parent_allocation_record_id"],
        "parent_candidate_id": pending["parent_candidate_id"],
        "parent_record_id": previous_record["record_id"],
        "population_head_record_id": ingested["population_head_record_id"],
        "population_record_ids": ingested["population_record_ids"],
        "round": pending["round"],
        "schema_version": DRIVER_SCHEMA_VERSION,
        "selection": validation["selection"],
        "sequence": len(cast(list[object], context["records"])),
    }
    record = append_driver_record(state_root, body)
    remove_pending(state_root)
    return record


def advance_pending(
    state_root: Path,
    context: dict[str, object],
    *,
    execute_controller: bool,
) -> bool:
    config = cast(dict[str, object], context["config"])
    pending = cast(dict[str, object], context["pending"])
    if pending["stage"] == "controller_pending":
        attempts = cast(list[dict[str, object]], pending["attempts"])
        receipt_name = controller_receipt_name(str(attempts[-1]["attempt_id"]))
        existing = receipt_reference_for_existing(state_root, receipt_name)
        if existing is None and not execute_controller:
            return False
        pending = run_controller_attempt(state_root, config, pending)
        if pending["stage"] == "controller_pending":
            return False
    if pending["stage"] == "controller_complete":
        pending = run_evidence_adapter(state_root, config, pending, context)
        if pending["stage"] == "controller_complete":
            return False
    if pending["stage"] != "evidence_complete":
        raise PopulationDriverError("pending round reached an unknown stage")
    complete_pending_round(state_root, context, pending)
    return True
