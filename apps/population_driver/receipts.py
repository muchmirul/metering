"""Immutable Controller and evidence receipt replay for Population Driver."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from apps.population_driver.population_driver_protocol import (
    CONTROLLER_RECEIPT_SCHEMA,
    EVIDENCE_RECEIPT_SCHEMA,
    PopulationDriverError,
    decode_evidence_adapter_response,
    evidence_adapter_request,
    validate_controller_result,
)
from apps.population_driver.population_driver_state import read_receipt
from apps._support.wire import canonical_json


def controller_receipt_name(attempt_id: str) -> str:
    return f"{attempt_id}.controller.json"


def evidence_receipt_name(attempt_id: str) -> str:
    return f"{attempt_id}.evidence.json"


def controller_receipt_document(
    state_root: Path,
    reference: object,
    *,
    expected_request: dict[str, object],
    config: dict[str, object],
    attempts: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    if type(reference) is not dict:
        raise PopulationDriverError("Controller receipt reference is malformed")
    if reference.get("name") != controller_receipt_name(
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


def evidence_receipt_document(
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
