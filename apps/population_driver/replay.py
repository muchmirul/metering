"""Pure replay and cross-ledger proof for bounded Population Driver state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from apps.population.contract import (
    POPULATION_SCHEMA_VERSION,
    PopulationError,
    PopulationState,
    decode_allocation_request,
    decode_archive_request,
    decode_candidate_request,
)
from apps.population_driver.paths import load_population
from apps.population_driver.population_driver_protocol import (
    DRIVER_SCHEMA_VERSION,
    PopulationDriverError,
    controller_request,
    controller_timeout_seconds,
    population_run_body,
    safe_feedback,
    validate_normalized_config,
)
from apps.population_driver.population_driver_state import (
    read_driver_records,
    read_pending,
    validate_record_chain,
)
from apps.population_driver.receipts import (
    controller_receipt_document,
    evidence_receipt_document,
)
from apps.stdio_connector import canonical_digest, canonical_json

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


def _population_record_by_id(
    state: PopulationState, record_id: object, location: str
) -> dict[str, object]:
    if type(record_id) is not str:
        raise PopulationDriverError(f"{location} must be a record ID")
    record = state.record(record_id)
    if record is not None:
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
    parent_run = population_run_body(
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
    child_run = population_run_body(
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


def _classify_pending(
    records: list[dict[str, object]],
    pending: dict[str, object] | None,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    """Separate an active intent from a committed, stale checkpoint."""

    if pending is None:
        return None, None
    round_number = pending.get("round")
    if type(round_number) is not int or round_number > len(records) - 1:
        return pending, None
    if round_number == len(records) - 1:
        completed = records[round_number]
        if completed.get("intent_id") == pending.get("intent_id"):
            return None, pending
    raise PopulationDriverError(
        "pending intent conflicts with completed driver records"
    )


@dataclass
class ReplayCursor:
    previous_feedback: dict[str, object] | None
    expected_parent_id: str
    expected_allocation_id: str | None
    proposal_calls: int
    reserved_wall_seconds: int
    last_population_head: str
    rounds: list[dict[str, object]]


def _verify_header(
    state_root: Path,
    records: list[dict[str, object]],
    supplied_config: dict[str, object] | None,
) -> tuple[
    dict[str, object],
    dict[str, object],
    str,
    dict[str, object],
    PopulationState,
]:
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

    state = load_population(state_root)
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
    return header, config, config_id, population, state


def _initial_cursor(header: dict[str, object]) -> ReplayCursor:
    return ReplayCursor(
        previous_feedback=None,
        expected_parent_id=str(header["seed_candidate_id"]),
        expected_allocation_id=None,
        proposal_calls=0,
        reserved_wall_seconds=0,
        last_population_head=str(header["population_head_record_id"]),
        rounds=[],
    )


def _replay_round(
    state_root: Path,
    *,
    config: dict[str, object],
    config_id: str,
    population: dict[str, object],
    state: PopulationState,
    header: dict[str, object],
    record: dict[str, object],
    round_number: int,
    cursor: ReplayCursor,
    controller_timeout: int,
    evidence_timeout: int,
) -> None:
    if set(record) != ROUND_RECORD_KEYS:
        raise PopulationDriverError(f"driver round {round_number} has the wrong keys")
    if record["round"] != round_number or type(record["round"]) is not int:
        raise PopulationDriverError(f"driver round {round_number} has a wrong number")
    if record["parent_candidate_id"] != cursor.expected_parent_id:
        raise PopulationDriverError(
            f"driver round {round_number} used the wrong parent"
        )
    if record["parent_allocation_record_id"] != cursor.expected_allocation_id:
        raise PopulationDriverError(
            f"driver round {round_number} used the wrong allocation"
        )
    expected_start_head = (
        str(header["population_head_record_id"])
        if round_number == 1
        else cursor.last_population_head
    )
    parent = state.candidates.get(cursor.expected_parent_id)
    if parent is None:
        raise PopulationDriverError(
            f"driver round {round_number} parent is absent from Population state"
        )
    expected_request = controller_request(
        config,
        parent,
        round_number,
        cursor.previous_feedback,
        parent_allocation_record_id=cursor.expected_allocation_id,
    )
    intent_id = canonical_digest(
        {
            "config_id": config_id,
            "controller_request": expected_request,
            "parent_allocation_record_id": cursor.expected_allocation_id,
            "parent_candidate_id": cursor.expected_parent_id,
            "population_start_record_id": expected_start_head,
            "round": round_number,
        }
    )
    if record["intent_id"] != intent_id:
        raise PopulationDriverError(f"driver round {round_number} intent is invalid")
    attempts = _validate_attempts(
        record["attempts"],
        intent_id=intent_id,
        controller_timeout=controller_timeout,
    )
    cursor.proposal_calls += len(attempts)
    cursor.reserved_wall_seconds += sum(
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
    cursor.reserved_wall_seconds += expected_evidence_reservation
    controller_reference = record["controller_receipt"]
    if type(controller_reference) is not dict:
        raise PopulationDriverError("round Controller receipt is malformed")
    _, controller_result, validation = controller_receipt_document(
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
    if canonical_json(record["selection"]) != canonical_json(validation["selection"]):
        raise PopulationDriverError(
            f"driver round {round_number} changed Controller selection"
        )
    evidence_reference = record["evidence_receipt"]
    if type(evidence_reference) is not dict:
        raise PopulationDriverError("round evidence receipt is malformed")
    _, evidence = evidence_receipt_document(
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
    expected_parent_run_body = population_run_body(
        candidate_id=parent_id,
        experiment_id=experiment_id,
        replicate_id=f"round-{round_number:06d}-incumbent",
        report_evidence=cast(dict[str, object], validation["parent_evidence"]),
        adapter_evidence=evidence[parent_id],
        evidence_reference=evidence_reference,
        state=state,
    )
    expected_child_run_body = population_run_body(
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
    cursor.last_population_head = str(record["population_head_record_id"])
    cursor.previous_feedback = safe_feedback(controller_result, round_number)
    cursor.expected_allocation_id = cast(
        str | None, record["next_allocation_record_id"]
    )
    cursor.expected_parent_id = selected or ""
    cursor.rounds.append(record)


def _replay_rounds(
    state_root: Path,
    records: list[dict[str, object]],
    *,
    header: dict[str, object],
    config: dict[str, object],
    config_id: str,
    population: dict[str, object],
    state: PopulationState,
    controller_timeout: int,
    evidence_timeout: int,
) -> ReplayCursor:
    cursor = _initial_cursor(header)
    for round_number, record in enumerate(records[1:], start=1):
        _replay_round(
            state_root,
            config=config,
            config_id=config_id,
            population=population,
            state=state,
            header=header,
            record=record,
            round_number=round_number,
            cursor=cursor,
            controller_timeout=controller_timeout,
            evidence_timeout=evidence_timeout,
        )
    return cursor


def _verify_pending(
    state_root: Path,
    pending: dict[str, object] | None,
    *,
    config: dict[str, object],
    config_id: str,
    state: PopulationState,
    cursor: ReplayCursor,
    controller_timeout: int,
    evidence_timeout: int,
) -> dict[str, object] | None:
    if pending is None:
        return None
    if set(pending) != PENDING_KEYS:
        raise PopulationDriverError("pending round intent has the wrong keys")
    round_number = len(cursor.rounds) + 1
    if pending["round"] != round_number or pending["config_id"] != config_id:
        raise PopulationDriverError("pending round intent identifies another run")
    if pending["schema_version"] != DRIVER_SCHEMA_VERSION:
        raise PopulationDriverError("pending round intent has the wrong schema")
    if pending["parent_candidate_id"] != cursor.expected_parent_id:
        raise PopulationDriverError("pending round intent used the wrong parent")
    if pending["parent_allocation_record_id"] != cursor.expected_allocation_id:
        raise PopulationDriverError("pending round intent used the wrong allocation")
    if pending["population_start_record_id"] != cursor.last_population_head:
        raise PopulationDriverError(
            "pending round intent used the wrong Population head"
        )
    start_sequence = pending["population_start_sequence"]
    if type(start_sequence) is not int or not 0 <= start_sequence < len(state.records):
        raise PopulationDriverError("pending population start sequence is invalid")
    if state.records[start_sequence].get("record_id") != cursor.last_population_head:
        raise PopulationDriverError("pending Population start sequence changed")
    parent = state.candidates.get(cursor.expected_parent_id)
    if parent is None:
        raise PopulationDriverError("pending parent is absent from Population state")
    expected_request = controller_request(
        config,
        parent,
        round_number,
        cursor.previous_feedback,
        parent_allocation_record_id=cursor.expected_allocation_id,
    )
    if canonical_json(pending["controller_request"]) != canonical_json(
        expected_request
    ):
        raise PopulationDriverError("pending Controller request changed")
    expected_intent_id = canonical_digest(
        {
            "config_id": config_id,
            "controller_request": expected_request,
            "parent_allocation_record_id": cursor.expected_allocation_id,
            "parent_candidate_id": cursor.expected_parent_id,
            "population_start_record_id": cursor.last_population_head,
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
    cursor.proposal_calls += len(pending_attempts)
    cursor.reserved_wall_seconds += sum(
        int(attempt["wall_reservation_seconds"]) for attempt in pending_attempts
    )
    evidence_attempts = pending["evidence_attempts"]
    if type(evidence_attempts) is not int or evidence_attempts < 0:
        raise PopulationDriverError("pending evidence attempt count changed")
    expected_evidence_reservation = max(1, evidence_attempts) * evidence_timeout
    if pending["evidence_wall_reservation_seconds"] != expected_evidence_reservation:
        raise PopulationDriverError("pending evidence wall reservation changed")
    cursor.reserved_wall_seconds += expected_evidence_reservation
    if pending["stage"] not in {
        "controller_pending",
        "controller_complete",
        "evidence_complete",
    }:
        raise PopulationDriverError("pending round intent has an invalid stage")
    if pending["last_error"] is not None and (
        type(pending["last_error"]) is not str or not pending["last_error"]
    ):
        raise PopulationDriverError("pending round intent has an invalid last_error")
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
        return pending
    if type(pending["controller_receipt"]) is not dict:
        raise PopulationDriverError("pending Controller receipt is missing")
    _, controller_result, validation = controller_receipt_document(
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
        parent_id = str(cast(dict[str, object], validation["parent"])["candidate_id"])
        child_id = str(cast(dict[str, object], validation["child"])["candidate_id"])
        evidence_reference = pending["evidence_receipt"]
        if type(evidence_reference) is not dict:
            raise PopulationDriverError("pending evidence receipt is malformed")
        _, evidence = evidence_receipt_document(
            state_root,
            evidence_reference,
            config=config,
            controller_reference=cast(dict[str, object], pending["controller_receipt"]),
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
    return pending


def verify_context(
    state_root: Path,
    supplied_config: dict[str, object] | None = None,
) -> dict[str, object]:
    """Replay every authoritative object and derive one machine-state view."""

    records = read_driver_records(state_root)
    validate_record_chain(records)
    header, config, config_id, population, state = _verify_header(
        state_root, records, supplied_config
    )
    controller_timeout = controller_timeout_seconds(config)
    evidence_timeout = int(
        cast(dict[str, object], config["evidence_adapter"])["timeout_seconds"]
    )
    cursor = _replay_rounds(
        state_root,
        records,
        header=header,
        config=config,
        config_id=config_id,
        population=population,
        state=state,
        controller_timeout=controller_timeout,
        evidence_timeout=evidence_timeout,
    )
    pending, committed_pending = _classify_pending(records, read_pending(state_root))
    pending = _verify_pending(
        state_root,
        pending,
        config=config,
        config_id=config_id,
        state=state,
        cursor=cursor,
        controller_timeout=controller_timeout,
        evidence_timeout=evidence_timeout,
    )
    return {
        "committed_pending": committed_pending,
        "config": config,
        "config_id": config_id,
        "expected_allocation_id": cursor.expected_allocation_id,
        "expected_parent_id": cursor.expected_parent_id,
        "header": header,
        "last_population_head": cursor.last_population_head,
        "pending": pending,
        "population": state,
        "previous_feedback": cursor.previous_feedback,
        "proposal_calls": cursor.proposal_calls,
        "records": records,
        "reserved_wall_seconds": cursor.reserved_wall_seconds,
        "rounds": cursor.rounds,
    }
