#!/usr/bin/env python3
"""Run bounded archive-allocation-mutation-evaluation population evolution."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = ROOT / "apps"
CONTROLLER_ROOT = APPS_ROOT / "controller"
POPULATION_ROOT = APPS_ROOT / "population"
DRIVER_ROOT = Path(__file__).resolve().parent
for import_root in (APPS_ROOT, CONTROLLER_ROOT, POPULATION_ROOT, DRIVER_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from agent_protocol import (  # noqa: E402
    ProtocolError,
    run_adapter,
)
from population_policy import (  # noqa: E402
    decode_allocation_request,
    decode_archive_request,
)
from population_protocol import (  # noqa: E402
    POPULATION_SCHEMA_VERSION,
    RESOURCE_NAMES,
    PopulationError,
    PopulationState,
    decode_candidate_request,
    decode_run_request,
)
from population_state import (  # noqa: E402
    append_validated_record,
    initialize as initialize_population,
    load_state as load_population_state,
    locked_state as locked_population_state,
)
from population_driver_protocol import (  # noqa: E402
    CONTROLLER_RECEIPT_SCHEMA,
    DRIVER_SCHEMA_VERSION,
    EVIDENCE_RECEIPT_SCHEMA,
    PopulationDriverError,
    RequestError,
    controller_request,
    controller_timeout_seconds,
    decode_evidence_adapter_response,
    decode_request,
    decode_retry_request,
    evidence_adapter_request,
    safe_feedback,
    total_cost,
    validate_controller_result,
    validate_normalized_config,
)
from population_driver_state import (  # noqa: E402
    _fsync_directory,
    append_driver_record,
    create_driver_ledger,
    locked_driver,
    read_driver_records,
    read_pending,
    read_receipt,
    receipt_reference_for_existing,
    remove_pending,
    validate_record_chain,
    write_pending,
    write_receipt,
)
from stdio_connector import (  # noqa: E402
    JsonProcessError,
    canonical_digest,
    canonical_json,
    decode_json_object,
    run_json_process,
    run_stdio_application,
)

CONTROLLER = ROOT / "apps/controller/controller.py"
POPULATION_DIRECTORY = "population"
ROUND_RECORD_KEYS = {
    "archive_member_candidate_ids",
    "attempts",
    "child_candidate_id",
    "controller_receipt",
    "evidence_attempts",
    "evidence_receipt",
    "evidence_wall_reservation_seconds",
    "intent_id",
    "kind",
    "next_allocation_record_id",
    "parent_allocation_record_id",
    "parent_candidate_id",
    "parent_record_id",
    "population_head_record_id",
    "population_record_ids",
    "record_id",
    "round",
    "schema_version",
    "selection",
    "sequence",
}
HEADER_RECORD_KEYS = {
    "config_id",
    "configuration",
    "experiment_id",
    "initial_candidate_record_id",
    "kind",
    "parent_record_id",
    "population_head_record_id",
    "population_id",
    "record_id",
    "schema_version",
    "seed_candidate_id",
    "sequence",
}
PENDING_KEYS = {
    "attempts",
    "config_id",
    "controller_receipt",
    "controller_request",
    "evidence_attempts",
    "evidence_receipt",
    "evidence_wall_reservation_seconds",
    "intent_id",
    "last_error",
    "parent_allocation_record_id",
    "parent_candidate_id",
    "pending_id",
    "population_start_record_id",
    "population_start_sequence",
    "round",
    "schema_version",
    "stage",
}
ATTEMPT_KEYS = {
    "attempt_id",
    "ordinal",
    "reason",
    "retry",
    "wall_reservation_seconds",
}


def _population_root(state_root: Path) -> Path:
    return state_root / POPULATION_DIRECTORY


def _load_population(state_root: Path) -> PopulationState:
    root = _population_root(state_root)
    try:
        with locked_population_state(root):
            return load_population_state(root)
    except PopulationError as exc:
        raise PopulationDriverError(str(exc)) from exc


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
            _population_root(temporary), config
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
        _fsync_directory(state_root.parent)
    except OSError as exc:
        raise PopulationDriverError(
            f"cannot initialize Population Driver: {exc}"
        ) from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _controller_receipt_name(attempt_id: str) -> str:
    return f"{attempt_id}.controller.json"


def _evidence_receipt_name(attempt_id: str) -> str:
    return f"{attempt_id}.evidence.json"


def _population_record_by_id(
    state: PopulationState, record_id: object, location: str
) -> dict[str, object]:
    if type(record_id) is not str:
        raise PopulationDriverError(f"{location} must be a record ID")
    for record in state.records:
        if record.get("record_id") == record_id:
            return record
    raise PopulationDriverError(f"{location} is absent from the Population ledger")


def _validate_attempts(
    raw_attempts: object,
    *,
    intent_id: str,
    controller_timeout: int,
) -> list[dict[str, object]]:
    if type(raw_attempts) is not list or not raw_attempts:
        raise PopulationDriverError("round attempts must be a non-empty array")
    attempts: list[dict[str, object]] = []
    for index, raw_attempt in enumerate(raw_attempts):
        if type(raw_attempt) is not dict or set(raw_attempt) != ATTEMPT_KEYS:
            raise PopulationDriverError(f"round attempt {index + 1} is malformed")
        ordinal = index + 1
        if raw_attempt["ordinal"] != ordinal or type(raw_attempt["ordinal"]) is not int:
            raise PopulationDriverError(f"round attempt {ordinal} has a wrong ordinal")
        if raw_attempt["retry"] is not (ordinal > 1):
            raise PopulationDriverError(
                f"round attempt {ordinal} has a wrong retry flag"
            )
        if (
            type(raw_attempt["reason"]) is not str
            or not raw_attempt["reason"]
            or type(raw_attempt["attempt_id"]) is not str
        ):
            raise PopulationDriverError(f"round attempt {ordinal} is malformed")
        if raw_attempt["wall_reservation_seconds"] != controller_timeout:
            raise PopulationDriverError(
                f"round attempt {ordinal} has a wrong wall reservation"
            )
        expected_id = canonical_digest(
            {
                "intent_id": intent_id,
                "ordinal": ordinal,
                "reason": raw_attempt["reason"],
                "retry": ordinal > 1,
            }
        )
        if raw_attempt["attempt_id"] != expected_id:
            raise PopulationDriverError(f"round attempt {ordinal} has a wrong identity")
        attempts.append(raw_attempt)
    return attempts


def _controller_receipt_document(
    state_root: Path,
    reference: object,
    *,
    expected_request: dict[str, object],
    config: dict[str, object],
    attempts: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    if type(reference) is not dict:
        raise PopulationDriverError("Controller receipt reference is malformed")
    if reference.get("name") != _controller_receipt_name(
        str(attempts[-1]["attempt_id"])
    ):
        raise PopulationDriverError("Controller receipt has the wrong name")
    document = read_receipt(state_root, reference)
    if set(document) != {
        "attempt_id",
        "controller_request",
        "controller_result",
        "receipt_schema",
    }:
        raise PopulationDriverError("Controller receipt has the wrong keys")
    if document["receipt_schema"] != CONTROLLER_RECEIPT_SCHEMA:
        raise PopulationDriverError("Controller receipt has the wrong schema")
    if document["attempt_id"] != attempts[-1]["attempt_id"]:
        raise PopulationDriverError("Controller receipt identifies the wrong attempt")
    if canonical_json(document["controller_request"]) != canonical_json(
        expected_request
    ):
        raise PopulationDriverError("Controller receipt changed the round request")
    result = document["controller_result"]
    if type(result) is not dict:
        raise PopulationDriverError("Controller receipt result is malformed")
    validation = validate_controller_result(expected_request, result, config)
    return document, result, validation


def _evidence_receipt_document(
    state_root: Path,
    reference: object,
    *,
    config: dict[str, object],
    controller_reference: dict[str, object],
    controller_result: dict[str, object],
    round_number: int,
    candidate_ids: set[str],
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    if type(reference) is not dict:
        raise PopulationDriverError("evidence receipt reference is malformed")
    controller_name = controller_reference.get("name")
    if type(controller_name) is not str or not controller_name.endswith(
        ".controller.json"
    ):
        raise PopulationDriverError("Controller receipt name is malformed")
    expected_name = controller_name.removesuffix(".controller.json") + ".evidence.json"
    if reference.get("name") != expected_name:
        raise PopulationDriverError("evidence receipt has the wrong name")
    document = read_receipt(state_root, reference)
    if set(document) != {
        "evidence_request",
        "evidence_response",
        "receipt_schema",
    }:
        raise PopulationDriverError("evidence receipt has the wrong keys")
    if document["receipt_schema"] != EVIDENCE_RECEIPT_SCHEMA:
        raise PopulationDriverError("evidence receipt has the wrong schema")
    expected_request = evidence_adapter_request(
        config=config,
        controller_receipt=controller_reference,
        controller_result=controller_result,
        round_number=round_number,
    )
    if canonical_json(document["evidence_request"]) != canonical_json(expected_request):
        raise PopulationDriverError("evidence receipt changed the adapter request")
    response = document["evidence_response"]
    if type(response) is not dict:
        raise PopulationDriverError("evidence receipt response is malformed")
    population = cast(dict[str, object], config["population"])
    decoded = decode_evidence_adapter_response(
        response,
        candidate_ids=candidate_ids,
        experiment=cast(dict[str, object], population["experiment"]),
    )
    return document, decoded


def _verify_population_round_records(
    state: PopulationState,
    record: dict[str, object],
    *,
    experiment_id: str,
    parent_id: str,
    child_id: str,
    expected_candidate_body: dict[str, object],
    expected_parent_run_body: dict[str, object],
    expected_child_run_body: dict[str, object],
    expected_draw: dict[str, int] | None,
    start_sequence: int,
) -> str | None:
    references = record["population_record_ids"]
    if type(references) is not dict or set(references) != {
        "allocation",
        "archive",
        "candidate",
        "challenger_run",
        "incumbent_run",
    }:
        raise PopulationDriverError("round population_record_ids are malformed")
    candidate_reference = references["candidate"]
    if candidate_reference is not None:
        candidate_record = _population_record_by_id(
            state, candidate_reference, "round candidate record"
        )
        body = candidate_record.get("body")
        if candidate_record.get("kind") != "candidate" or type(body) is not dict:
            raise PopulationDriverError("round candidate record is malformed")
        candidate = body.get("candidate")
        if type(candidate) is not dict or candidate.get("candidate_id") != child_id:
            raise PopulationDriverError("round candidate record changed the child")
        if canonical_json(body) != canonical_json(expected_candidate_body):
            raise PopulationDriverError("round candidate lineage receipt changed")
    else:
        known_record_id = state.candidate_record_ids.get(child_id)
        if known_record_id is None:
            raise PopulationDriverError("round child is absent from Population state")
        known_record = _population_record_by_id(
            state, known_record_id, "known round child"
        )
        if int(known_record["sequence"]) > start_sequence:
            raise PopulationDriverError("round omitted its newly appended child record")

    expected_run_bodies = {
        "challenger_run": expected_child_run_body,
        "incumbent_run": expected_parent_run_body,
    }
    for key, expected_candidate, expected_suffix in (
        ("incumbent_run", parent_id, "incumbent"),
        ("challenger_run", child_id, "challenger"),
    ):
        run_record = _population_record_by_id(state, references[key], f"round {key}")
        body = run_record.get("body")
        run = body.get("run") if type(body) is dict else None
        if (
            run_record.get("kind") != "run"
            or type(run) is not dict
            or run.get("candidate_id") != expected_candidate
            or run.get("experiment_id") != experiment_id
            or run.get("replicate_id")
            != f"round-{int(record['round']):06d}-{expected_suffix}"
        ):
            raise PopulationDriverError(f"round {key} record changed identity")
        if canonical_json(body) != canonical_json(expected_run_bodies[key]):
            raise PopulationDriverError(f"round {key} evidence changed")

    archive_record = _population_record_by_id(
        state, references["archive"], "round archive record"
    )
    if archive_record.get("kind") != "archive":
        raise PopulationDriverError("round archive reference is not an archive")
    archive_body = archive_record.get("body")
    if (
        type(archive_body) is not dict
        or archive_body.get("experiment_id") != experiment_id
    ):
        raise PopulationDriverError("round archive changed experiment")
    members = archive_body.get("members")
    if type(members) is not list:
        raise PopulationDriverError("round archive members are malformed")
    member_ids = [
        member.get("candidate_id") for member in members if type(member) is dict
    ]
    if member_ids != record["archive_member_candidate_ids"]:
        raise PopulationDriverError("round archive member summary changed")

    allocation_reference = references["allocation"]
    selected: str | None = None
    if allocation_reference is not None:
        allocation_record = _population_record_by_id(
            state, allocation_reference, "round allocation record"
        )
        allocation_body = allocation_record.get("body")
        allocation_request = (
            allocation_body.get("request") if type(allocation_body) is dict else None
        )
        result = (
            allocation_body.get("result") if type(allocation_body) is dict else None
        )
        if (
            allocation_record.get("kind") != "allocation"
            or type(allocation_body) is not dict
            or type(allocation_request) is not dict
            or allocation_request.get("archive_record_id") != references["archive"]
            or expected_draw is None
            or allocation_request.get("draw") != expected_draw
            or type(result) is not dict
            or type(result.get("selected_candidate_id")) is not str
        ):
            raise PopulationDriverError("round allocation record is malformed")
        selected = str(result["selected_candidate_id"])
    elif expected_draw is not None and member_ids:
        raise PopulationDriverError("round omitted its required parent allocation")
    if record["next_allocation_record_id"] != allocation_reference:
        raise PopulationDriverError("round allocation references disagree")
    expected_head = allocation_reference or references["archive"]
    if record["population_head_record_id"] != expected_head:
        raise PopulationDriverError("round population head is inconsistent")
    _population_record_by_id(state, expected_head, "round population head")
    ordered_references = [
        reference
        for reference in (
            candidate_reference,
            references["incumbent_run"],
            references["challenger_run"],
            references["archive"],
            allocation_reference,
        )
        if reference is not None
    ]
    sequences = [
        int(_population_record_by_id(state, reference, "round record")["sequence"])
        for reference in ordered_references
    ]
    if sequences != list(
        range(start_sequence + 1, start_sequence + 1 + len(sequences))
    ):
        raise PopulationDriverError("round Population records are not one exact suffix")
    return selected


def _verify_pending_population_prefix(
    state: PopulationState,
    pending: dict[str, object],
    config: dict[str, object],
    validation: dict[str, object],
    evidence: dict[str, dict[str, object]],
    evidence_reference: dict[str, object],
) -> None:
    start_sequence = int(pending["population_start_sequence"])
    tail = state.records[start_sequence + 1 :]
    if not tail:
        return
    position = 0

    def compare(kind: str, body: dict[str, object]) -> bool:
        nonlocal position
        if position >= len(tail):
            return False
        record = tail[position]
        if record.get("kind") != kind or canonical_json(
            record.get("body")
        ) != canonical_json(body):
            raise PopulationDriverError(
                "pending Population prefix conflicts at sequence "
                f"{start_sequence + position + 1}"
            )
        position += 1
        return position < len(tail)

    parent = cast(dict[str, object], validation["parent"])
    child = cast(dict[str, object], validation["child"])
    parent_id = str(parent["candidate_id"])
    child_id = str(child["candidate_id"])
    child_record_id = state.candidate_record_ids.get(child_id)
    child_sequence = None
    if child_record_id is not None:
        child_sequence = int(
            _population_record_by_id(state, child_record_id, "pending child")[
                "sequence"
            ]
        )
    if child_record_id is None or (
        child_sequence is not None and child_sequence > start_sequence
    ):
        try:
            candidate_body = decode_candidate_request(
                {
                    "artifact": child["artifact"],
                    "parents": [parent_id],
                    "schema_version": POPULATION_SCHEMA_VERSION,
                    "variation": {
                        "choice": {
                            "controller_proposal_id": validation["proposal_id"],
                            "round": pending["round"],
                            "round_intent_id": pending["intent_id"],
                        },
                        "policy_id": config["mutation_policy_id"],
                        "type": "mutation-v1",
                    },
                },
                state,
            )
        except (PopulationError, ValueError) as exc:
            raise PopulationDriverError(str(exc)) from exc
        if not compare("candidate", candidate_body):
            return

    population = cast(dict[str, object], config["population"])
    experiment_id = str(population["experiment_id"])
    round_number = int(pending["round"])
    parent_run = _run_body(
        candidate_id=parent_id,
        experiment_id=experiment_id,
        replicate_id=f"round-{round_number:06d}-incumbent",
        report_evidence=cast(dict[str, object], validation["parent_evidence"]),
        adapter_evidence=evidence[parent_id],
        evidence_reference=evidence_reference,
        state=state,
    )
    if not compare("run", parent_run):
        return
    child_run = _run_body(
        candidate_id=child_id,
        experiment_id=experiment_id,
        replicate_id=f"round-{round_number:06d}-challenger",
        report_evidence=cast(dict[str, object], validation["child_evidence"]),
        adapter_evidence=evidence[child_id],
        evidence_reference=evidence_reference,
        state=state,
    )
    if not compare("run", child_run):
        return
    archive_body = decode_archive_request(
        {
            "experiment_id": experiment_id,
            "schema_version": POPULATION_SCHEMA_VERSION,
        },
        state,
    )
    if not compare("archive", archive_body):
        return
    members = cast(list[dict[str, object]], archive_body["members"])
    limits = cast(dict[str, object], config["limits"])
    if members and round_number < int(limits["max_rounds"]):
        allocation_body = decode_allocation_request(
            {
                "archive_record_id": tail[position - 1]["record_id"],
                "draw": cast(list[dict[str, int]], config["allocation_draws"])[
                    round_number - 1
                ],
                "schema_version": POPULATION_SCHEMA_VERSION,
            },
            state,
        )
        if not compare("allocation", allocation_body):
            return
    if position != len(tail):
        raise PopulationDriverError("pending Population prefix has extra records")


def _cleanup_stale_pending(state_root: Path, records: list[dict[str, object]]) -> None:
    pending = read_pending(state_root)
    if pending is None:
        return
    round_number = pending.get("round")
    if type(round_number) is not int or round_number > len(records) - 1:
        return
    if round_number == len(records) - 1:
        completed = records[round_number]
        if completed.get("intent_id") == pending.get("intent_id"):
            remove_pending(state_root)
            return
    raise PopulationDriverError(
        "pending intent conflicts with completed driver records"
    )


def _verify_context(
    state_root: Path,
    supplied_config: dict[str, object] | None = None,
) -> dict[str, object]:
    records = read_driver_records(state_root)
    validate_record_chain(records)
    if set(records[0]) != HEADER_RECORD_KEYS:
        raise PopulationDriverError("driver header has the wrong keys")
    header = records[0]
    config = validate_normalized_config(header["configuration"])
    config_id = canonical_digest(config)
    if header["config_id"] != config_id:
        raise PopulationDriverError("driver header config_id is invalid")
    if supplied_config is not None and canonical_json(
        supplied_config
    ) != canonical_json(config):
        raise PopulationDriverError(
            "request does not match the initialized driver configuration"
        )
    population = cast(dict[str, object], config.get("population"))
    initial_parent = cast(dict[str, object], config.get("initial_parent"))
    if (
        type(population) is not dict
        or type(initial_parent) is not dict
        or header["experiment_id"] != population.get("experiment_id")
        or header["seed_candidate_id"] != initial_parent.get("candidate_id")
    ):
        raise PopulationDriverError(
            "driver header configuration references are invalid"
        )

    state = _load_population(state_root)
    if header["population_id"] != state.records[0].get("record_id"):
        raise PopulationDriverError(
            "driver header identifies another Population ledger"
        )
    if canonical_json(state.configuration) != canonical_json(
        population["configuration"]
    ):
        raise PopulationDriverError("Population configuration changed")
    initial_candidate_record = _population_record_by_id(
        state, header["initial_candidate_record_id"], "initial candidate record"
    )
    initial_body = initial_candidate_record.get("body")
    initial_candidate = (
        initial_body.get("candidate") if type(initial_body) is dict else None
    )
    if (
        initial_candidate_record.get("kind") != "candidate"
        or type(initial_candidate) is not dict
        or initial_candidate != initial_parent
        or initial_candidate.get("candidate_id") != header["seed_candidate_id"]
        or initial_candidate_record.get("sequence") != 1
    ):
        raise PopulationDriverError("initial candidate record is invalid")
    experiment_id = str(population["experiment_id"])
    experiment_record_id = state.experiment_record_ids.get(experiment_id)
    if experiment_record_id != header["population_head_record_id"]:
        raise PopulationDriverError("initial Population head is not the experiment")
    experiment_record = _population_record_by_id(
        state, experiment_record_id, "initial experiment record"
    )
    if (
        experiment_record.get("kind") != "experiment"
        or experiment_record.get("sequence") != 2
        or state.experiments.get(experiment_id) != population["experiment"]
    ):
        raise PopulationDriverError("initial experiment record is invalid")

    previous_feedback: dict[str, object] | None = None
    expected_parent_id = str(header["seed_candidate_id"])
    expected_allocation_id: str | None = None
    proposal_calls = 0
    reserved_wall = 0
    controller_timeout = controller_timeout_seconds(config)
    evidence_timeout = int(
        cast(dict[str, object], config["evidence_adapter"])["timeout_seconds"]
    )
    last_population_head = str(header["population_head_record_id"])
    verified_rounds: list[dict[str, object]] = []
    for round_number, record in enumerate(records[1:], start=1):
        if set(record) != ROUND_RECORD_KEYS:
            raise PopulationDriverError(
                f"driver round {round_number} has the wrong keys"
            )
        if record["round"] != round_number or type(record["round"]) is not int:
            raise PopulationDriverError(
                f"driver round {round_number} has a wrong number"
            )
        if record["parent_candidate_id"] != expected_parent_id:
            raise PopulationDriverError(
                f"driver round {round_number} used the wrong parent"
            )
        if record["parent_allocation_record_id"] != expected_allocation_id:
            raise PopulationDriverError(
                f"driver round {round_number} used the wrong allocation"
            )
        if round_number == 1:
            expected_start_head = str(header["population_head_record_id"])
        else:
            expected_start_head = last_population_head
        parent = state.candidates.get(expected_parent_id)
        if parent is None:
            raise PopulationDriverError(
                f"driver round {round_number} parent is absent from Population state"
            )
        expected_request = controller_request(
            config,
            parent,
            round_number,
            previous_feedback,
            parent_allocation_record_id=expected_allocation_id,
        )
        intent_id = canonical_digest(
            {
                "config_id": config_id,
                "controller_request": expected_request,
                "parent_allocation_record_id": expected_allocation_id,
                "parent_candidate_id": expected_parent_id,
                "population_start_record_id": expected_start_head,
                "round": round_number,
            }
        )
        if record["intent_id"] != intent_id:
            raise PopulationDriverError(
                f"driver round {round_number} intent is invalid"
            )
        attempts = _validate_attempts(
            record["attempts"],
            intent_id=intent_id,
            controller_timeout=controller_timeout,
        )
        proposal_calls += len(attempts)
        reserved_wall += sum(
            int(attempt["wall_reservation_seconds"]) for attempt in attempts
        )
        evidence_attempts = record["evidence_attempts"]
        if type(evidence_attempts) is not int or evidence_attempts < 1:
            raise PopulationDriverError(
                f"driver round {round_number} has an invalid evidence attempt count"
            )
        expected_evidence_reservation = evidence_attempts * evidence_timeout
        if record["evidence_wall_reservation_seconds"] != expected_evidence_reservation:
            raise PopulationDriverError(
                f"driver round {round_number} has a wrong evidence wall reservation"
            )
        reserved_wall += expected_evidence_reservation
        controller_reference = record["controller_receipt"]
        if type(controller_reference) is not dict:
            raise PopulationDriverError("round Controller receipt is malformed")
        _, controller_result, validation = _controller_receipt_document(
            state_root,
            controller_reference,
            expected_request=expected_request,
            config=config,
            attempts=attempts,
        )
        parent_id = str(cast(dict[str, object], validation["parent"])["candidate_id"])
        child_id = str(cast(dict[str, object], validation["child"])["candidate_id"])
        if record["child_candidate_id"] != child_id:
            raise PopulationDriverError(f"driver round {round_number} changed child ID")
        if canonical_json(record["selection"]) != canonical_json(
            validation["selection"]
        ):
            raise PopulationDriverError(
                f"driver round {round_number} changed Controller selection"
            )
        evidence_reference = record["evidence_receipt"]
        if type(evidence_reference) is not dict:
            raise PopulationDriverError("round evidence receipt is malformed")
        _, evidence = _evidence_receipt_document(
            state_root,
            evidence_reference,
            config=config,
            controller_reference=controller_reference,
            controller_result=controller_result,
            round_number=round_number,
            candidate_ids={parent_id, child_id},
        )
        child = cast(dict[str, object], validation["child"])
        try:
            expected_candidate_body = decode_candidate_request(
                {
                    "artifact": child["artifact"],
                    "parents": [parent_id],
                    "schema_version": POPULATION_SCHEMA_VERSION,
                    "variation": {
                        "choice": {
                            "controller_proposal_id": validation["proposal_id"],
                            "round": round_number,
                            "round_intent_id": intent_id,
                        },
                        "policy_id": config["mutation_policy_id"],
                        "type": "mutation-v1",
                    },
                },
                state,
            )
        except (PopulationError, ValueError) as exc:
            raise PopulationDriverError(str(exc)) from exc
        experiment_id = str(population["experiment_id"])
        expected_parent_run_body = _run_body(
            candidate_id=parent_id,
            experiment_id=experiment_id,
            replicate_id=f"round-{round_number:06d}-incumbent",
            report_evidence=cast(dict[str, object], validation["parent_evidence"]),
            adapter_evidence=evidence[parent_id],
            evidence_reference=evidence_reference,
            state=state,
        )
        expected_child_run_body = _run_body(
            candidate_id=child_id,
            experiment_id=experiment_id,
            replicate_id=f"round-{round_number:06d}-challenger",
            report_evidence=cast(dict[str, object], validation["child_evidence"]),
            adapter_evidence=evidence[child_id],
            evidence_reference=evidence_reference,
            state=state,
        )
        limits = cast(dict[str, object], config["limits"])
        expected_draw = (
            cast(list[dict[str, int]], config["allocation_draws"])[round_number - 1]
            if round_number < int(limits["max_rounds"])
            else None
        )
        start_record = _population_record_by_id(
            state, expected_start_head, "round Population start"
        )
        selected = _verify_population_round_records(
            state,
            record,
            experiment_id=experiment_id,
            parent_id=parent_id,
            child_id=child_id,
            expected_candidate_body=expected_candidate_body,
            expected_parent_run_body=expected_parent_run_body,
            expected_child_run_body=expected_child_run_body,
            expected_draw=expected_draw,
            start_sequence=int(start_record["sequence"]),
        )
        last_population_head = str(record["population_head_record_id"])
        previous_feedback = safe_feedback(controller_result, round_number)
        expected_allocation_id = cast(str | None, record["next_allocation_record_id"])
        expected_parent_id = selected or ""
        verified_rounds.append(record)

    _cleanup_stale_pending(state_root, records)
    pending = read_pending(state_root)
    if pending is not None:
        if set(pending) != PENDING_KEYS:
            raise PopulationDriverError("pending round intent has the wrong keys")
        round_number = len(verified_rounds) + 1
        if pending["round"] != round_number or pending["config_id"] != config_id:
            raise PopulationDriverError("pending round intent identifies another run")
        if pending["schema_version"] != DRIVER_SCHEMA_VERSION:
            raise PopulationDriverError("pending round intent has the wrong schema")
        if pending["parent_candidate_id"] != expected_parent_id:
            raise PopulationDriverError("pending round intent used the wrong parent")
        if pending["parent_allocation_record_id"] != expected_allocation_id:
            raise PopulationDriverError(
                "pending round intent used the wrong allocation"
            )
        if pending["population_start_record_id"] != last_population_head:
            raise PopulationDriverError(
                "pending round intent used the wrong Population head"
            )
        start_sequence = pending["population_start_sequence"]
        if type(start_sequence) is not int or not 0 <= start_sequence < len(
            state.records
        ):
            raise PopulationDriverError("pending population start sequence is invalid")
        if state.records[start_sequence].get("record_id") != last_population_head:
            raise PopulationDriverError("pending Population start sequence changed")
        parent = state.candidates.get(expected_parent_id)
        if parent is None:
            raise PopulationDriverError(
                "pending parent is absent from Population state"
            )
        expected_request = controller_request(
            config,
            parent,
            round_number,
            previous_feedback,
            parent_allocation_record_id=expected_allocation_id,
        )
        if canonical_json(pending["controller_request"]) != canonical_json(
            expected_request
        ):
            raise PopulationDriverError("pending Controller request changed")
        expected_intent_id = canonical_digest(
            {
                "config_id": config_id,
                "controller_request": expected_request,
                "parent_allocation_record_id": expected_allocation_id,
                "parent_candidate_id": expected_parent_id,
                "population_start_record_id": last_population_head,
                "round": round_number,
            }
        )
        if pending["intent_id"] != expected_intent_id:
            raise PopulationDriverError("pending round intent identity changed")
        pending_attempts = _validate_attempts(
            pending["attempts"],
            intent_id=expected_intent_id,
            controller_timeout=controller_timeout,
        )
        proposal_calls += len(pending_attempts)
        reserved_wall += sum(
            int(attempt["wall_reservation_seconds"]) for attempt in pending_attempts
        )
        evidence_attempts = pending["evidence_attempts"]
        if type(evidence_attempts) is not int or evidence_attempts < 0:
            raise PopulationDriverError("pending evidence attempt count changed")
        expected_evidence_reservation = max(1, evidence_attempts) * evidence_timeout
        if (
            pending["evidence_wall_reservation_seconds"]
            != expected_evidence_reservation
        ):
            raise PopulationDriverError("pending evidence wall reservation changed")
        reserved_wall += expected_evidence_reservation
        if pending["stage"] not in {
            "controller_pending",
            "controller_complete",
            "evidence_complete",
        }:
            raise PopulationDriverError("pending round intent has an invalid stage")
        if pending["last_error"] is not None and (
            type(pending["last_error"]) is not str or not pending["last_error"]
        ):
            raise PopulationDriverError(
                "pending round intent has an invalid last_error"
            )
        if pending["stage"] != "evidence_complete" and len(state.records) != (
            start_sequence + 1
        ):
            raise PopulationDriverError(
                "Population state advanced before pending evidence completed"
            )
        if pending["stage"] == "controller_pending":
            if (
                pending["controller_receipt"] is not None
                or pending["evidence_receipt"] is not None
            ):
                raise PopulationDriverError(
                    "pending Controller stage has premature receipts"
                )
        else:
            if type(pending["controller_receipt"]) is not dict:
                raise PopulationDriverError("pending Controller receipt is missing")
            _, controller_result, validation = _controller_receipt_document(
                state_root,
                pending["controller_receipt"],
                expected_request=expected_request,
                config=config,
                attempts=pending_attempts,
            )
            if pending["stage"] == "evidence_complete":
                if evidence_attempts < 1:
                    raise PopulationDriverError(
                        "completed pending evidence has no adapter attempt"
                    )
                parent_id = str(
                    cast(dict[str, object], validation["parent"])["candidate_id"]
                )
                child_id = str(
                    cast(dict[str, object], validation["child"])["candidate_id"]
                )
                evidence_reference = pending["evidence_receipt"]
                if type(evidence_reference) is not dict:
                    raise PopulationDriverError("pending evidence receipt is malformed")
                _, evidence = _evidence_receipt_document(
                    state_root,
                    evidence_reference,
                    config=config,
                    controller_reference=cast(
                        dict[str, object], pending["controller_receipt"]
                    ),
                    controller_result=controller_result,
                    round_number=round_number,
                    candidate_ids={parent_id, child_id},
                )
                _verify_pending_population_prefix(
                    state,
                    pending,
                    config,
                    validation,
                    evidence,
                    evidence_reference,
                )
            elif pending["evidence_receipt"] is not None:
                raise PopulationDriverError("pending evidence receipt is premature")

    return {
        "config": config,
        "config_id": config_id,
        "expected_allocation_id": expected_allocation_id,
        "expected_parent_id": expected_parent_id,
        "header": header,
        "last_population_head": last_population_head,
        "pending": pending,
        "population": state,
        "previous_feedback": previous_feedback,
        "proposal_calls": proposal_calls,
        "records": records,
        "reserved_wall_seconds": reserved_wall,
        "rounds": verified_rounds,
    }


def _new_attempt(
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


def _start_pending(
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
                _new_attempt(
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


def _pending_body(pending: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in pending.items() if key not in {"pending_id"}}


def _update_pending(
    state_root: Path,
    pending: dict[str, object],
    **changes: object,
) -> dict[str, object]:
    body = _pending_body(pending)
    body.update(changes)
    return write_pending(state_root, body)


def _error_detail(error: BaseException) -> str:
    message = str(error).strip()
    return message if message else error.__class__.__name__


def _run_controller_attempt(
    state_root: Path,
    config: dict[str, object],
    pending: dict[str, object],
) -> dict[str, object]:
    attempts = cast(list[dict[str, object]], pending["attempts"])
    attempt = attempts[-1]
    name = _controller_receipt_name(str(attempt["attempt_id"]))
    existing = receipt_reference_for_existing(state_root, name)
    if existing is not None:
        try:
            _controller_receipt_document(
                state_root,
                existing,
                expected_request=cast(dict[str, object], pending["controller_request"]),
                config=config,
                attempts=attempts,
            )
        except PopulationDriverError:
            raise
        return _update_pending(
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
        return _update_pending(
            state_root,
            pending,
            last_error=f"Controller attempt requires explicit retry: {_error_detail(exc)}",
        )
    return _update_pending(
        state_root,
        pending,
        controller_receipt=reference,
        last_error=None,
        stage="controller_complete",
    )


def _run_evidence_adapter(
    state_root: Path,
    config: dict[str, object],
    pending: dict[str, object],
    context: dict[str, object],
) -> dict[str, object]:
    attempts = cast(list[dict[str, object]], pending["attempts"])
    attempt_id = str(attempts[-1]["attempt_id"])
    name = _evidence_receipt_name(attempt_id)
    controller_reference = cast(dict[str, object], pending["controller_receipt"])
    _, controller_result, validation = _controller_receipt_document(
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
        _evidence_receipt_document(
            state_root,
            existing,
            config=config,
            controller_reference=controller_reference,
            controller_result=controller_result,
            round_number=int(pending["round"]),
            candidate_ids={parent_id, child_id},
        )
        return _update_pending(
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
            return _update_pending(
                state_root,
                pending,
                last_error="evidence adapter wall reservation limit reached",
            )
        pending = _update_pending(
            state_root,
            pending,
            evidence_wall_reservation_seconds=(
                int(pending["evidence_wall_reservation_seconds"]) + adapter_timeout
            ),
        )
    pending = _update_pending(
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
        return _update_pending(
            state_root,
            pending,
            last_error=f"evidence adapter can be resumed: {_error_detail(exc)}",
        )
    return _update_pending(
        state_root,
        pending,
        evidence_receipt=reference,
        last_error=None,
        stage="evidence_complete",
    )


def _ensure_population_record(
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


def _run_body(
    *,
    candidate_id: str,
    experiment_id: str,
    replicate_id: str,
    report_evidence: dict[str, object],
    adapter_evidence: dict[str, object],
    evidence_reference: dict[str, object],
    state: PopulationState,
) -> dict[str, object]:
    request = {
        "candidate_id": candidate_id,
        "evidence": {
            "behavior_distribution": adapter_evidence["behavior_distribution"],
            "cost": adapter_evidence["cost"],
            "evidence_receipt": {
                "sha256": evidence_reference["sha256"],
                "uri": evidence_reference["uri"],
            },
            "information_model": None,
            "protected_passed": adapter_evidence["protected_passed"],
            "target_probabilities": report_evidence["target_probabilities"],
            "task": report_evidence["task"],
        },
        "experiment_id": experiment_id,
        "replicate_id": replicate_id,
        "schema_version": POPULATION_SCHEMA_VERSION,
        "seed": adapter_evidence["seed"],
    }
    try:
        return decode_run_request(request, state)
    except (PopulationError, ValueError) as exc:
        raise PopulationDriverError(str(exc)) from exc


def _ingest_population_round(
    state_root: Path,
    config: dict[str, object],
    pending: dict[str, object],
) -> dict[str, object]:
    attempts = cast(list[dict[str, object]], pending["attempts"])
    controller_reference = cast(dict[str, object], pending["controller_receipt"])
    _, controller_result, validation = _controller_receipt_document(
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
    _, evidence = _evidence_receipt_document(
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
    root = _population_root(state_root)
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
                existing_child_record = _population_record_by_id(
                    state, existing_child_record_id, "child candidate"
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
                candidate_record, sequence = _ensure_population_record(
                    root, state, sequence, "candidate", candidate_body
                )
                child_record_id = str(candidate_record["record_id"])

            parent_run_body = _run_body(
                candidate_id=parent_id,
                experiment_id=experiment_id,
                replicate_id=f"round-{round_number:06d}-incumbent",
                report_evidence=cast(dict[str, object], validation["parent_evidence"]),
                adapter_evidence=evidence[parent_id],
                evidence_reference=evidence_reference,
                state=state,
            )
            parent_run_record, sequence = _ensure_population_record(
                root, state, sequence, "run", parent_run_body
            )
            child_run_body = _run_body(
                candidate_id=child_id,
                experiment_id=experiment_id,
                replicate_id=f"round-{round_number:06d}-challenger",
                report_evidence=cast(dict[str, object], validation["child_evidence"]),
                adapter_evidence=evidence[child_id],
                evidence_reference=evidence_reference,
                state=state,
            )
            child_run_record, sequence = _ensure_population_record(
                root, state, sequence, "run", child_run_body
            )
            archive_body = decode_archive_request(
                {
                    "experiment_id": experiment_id,
                    "schema_version": POPULATION_SCHEMA_VERSION,
                },
                state,
            )
            archive_record, sequence = _ensure_population_record(
                root, state, sequence, "archive", archive_body
            )
            members = cast(list[dict[str, object]], archive_body["members"])
            member_ids = [str(member["candidate_id"]) for member in members]
            allocation_record: dict[str, object] | None = None
            limits = cast(dict[str, object], config["limits"])
            if members and round_number < int(limits["max_rounds"]):
                draws = cast(list[dict[str, int]], config["allocation_draws"])
                allocation_body = decode_allocation_request(
                    {
                        "archive_record_id": archive_record["record_id"],
                        "draw": draws[round_number - 1],
                        "schema_version": POPULATION_SCHEMA_VERSION,
                    },
                    state,
                )
                allocation_record, sequence = _ensure_population_record(
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


def _complete_pending_round(
    state_root: Path,
    context: dict[str, object],
    pending: dict[str, object],
) -> dict[str, object]:
    config = cast(dict[str, object], context["config"])
    ingested = _ingest_population_round(state_root, config, pending)
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


def _advance_pending(
    state_root: Path,
    context: dict[str, object],
    *,
    execute_controller: bool,
) -> bool:
    config = cast(dict[str, object], context["config"])
    pending = cast(dict[str, object], context["pending"])
    if pending["stage"] == "controller_pending":
        attempts = cast(list[dict[str, object]], pending["attempts"])
        receipt_name = _controller_receipt_name(str(attempts[-1]["attempt_id"]))
        existing = receipt_reference_for_existing(state_root, receipt_name)
        if existing is None and not execute_controller:
            return False
        pending = _run_controller_attempt(state_root, config, pending)
        if pending["stage"] == "controller_pending":
            return False
    if pending["stage"] == "controller_complete":
        pending = _run_evidence_adapter(state_root, config, pending, context)
        if pending["stage"] == "controller_complete":
            return False
    if pending["stage"] != "evidence_complete":
        raise PopulationDriverError("pending round reached an unknown stage")
    _complete_pending_round(state_root, context, pending)
    return True


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


def _stop_status(context: dict[str, object]) -> str | None:
    config = cast(dict[str, object], context["config"])
    limits = cast(dict[str, object], config["limits"])
    state = cast(PopulationState, context["population"])
    rounds = cast(list[object], context["rounds"])
    if state.final_evaluation_started:
        return "final_evidence_sealed"
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
    config_timeout = controller_timeout_seconds(config)
    evidence_timeout = int(
        cast(dict[str, object], config["evidence_adapter"])["timeout_seconds"]
    )
    if int(context["reserved_wall_seconds"]) + config_timeout + evidence_timeout > int(
        limits["max_wall_seconds"]
    ):
        return "wall_reservation_limit"
    return None


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
        "population_state_path": str(_population_root(state_root)),
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


def _drive(
    state_root: Path,
    config: dict[str, object],
    *,
    execute_existing_pending: bool,
) -> dict[str, object]:
    allow_existing = execute_existing_pending
    while True:
        context = _verify_context(state_root, config)
        pending = cast(dict[str, object] | None, context["pending"])
        if pending is not None:
            population_state = cast(PopulationState, context["population"])
            if population_state.final_evaluation_started:
                return _summary(state_root, context, "final_evidence_sealed")
            if (
                pending["stage"] in {"controller_pending", "controller_complete"}
                and population_state.head_id != pending["population_start_record_id"]
            ):
                return _summary(state_root, context, "population_state_advanced")
            completed = _advance_pending(
                state_root,
                context,
                execute_controller=allow_existing,
            )
            allow_existing = True
            if not completed:
                refreshed = _verify_context(state_root, config)
                return _summary(state_root, refreshed, "pending_round")
            continue
        status = _stop_status(context)
        if status is not None:
            return _summary(state_root, context, status)
        _start_pending(state_root, context)
        allow_existing = True


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
        context = _verify_context(state_root)
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
        receipt_name = _controller_receipt_name(str(attempts[-1]["attempt_id"]))
        if receipt_reference_for_existing(state_root, receipt_name) is not None:
            raise PopulationDriverError(
                "Controller receipt exists; use run to resume without another model call"
            )
        config = cast(dict[str, object], context["config"])
        population_state = cast(PopulationState, context["population"])
        if population_state.final_evaluation_started:
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
            _new_attempt(
                str(pending["intent_id"]),
                len(attempts) + 1,
                str(retry["reason"]),
                controller_timeout,
            ),
        ]
        _update_pending(
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
        context = _verify_context(state_root)
        return _summary(state_root, context, "verified")


def _application(source: str, arguments: list[str]) -> dict[str, object]:
    if len(arguments) != 2 or arguments[0] not in {"retry", "run", "verify"}:
        raise RequestError(
            "usage: population_driver.py {run|retry|verify} STATE_DIRECTORY"
        )
    command, raw_root = arguments
    root = Path(raw_root)
    if command == "run":
        return run_population_driver(source, root)
    if command == "retry":
        return retry_population_driver(source, root)
    if source.strip():
        raise RequestError("verify standard input must be empty")
    return verify_population_driver(root)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        lambda source: _application(source, arguments),
        [],
        error_rules=(
            (RequestError, "invalid_request"),
            ((PopulationDriverError, OSError), "population_driver_error"),
        ),
        stream_error_code="population_driver_error",
    )


if __name__ == "__main__":
    raise SystemExit(main())
