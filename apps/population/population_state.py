"""Canonical hash-linked persistence and replay for Population Archive."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from agent_protocol import ProtocolError, require_exact_keys, require_sha256
from stdio_connector import canonical_digest, canonical_json, decode_json_object

from population_policy import _allocation_body, _archive_body
from population_protocol import (
    POPULATION_SCHEMA_VERSION,
    PopulationError,
    PopulationState,
    _candidate_body,
    _configuration,
    _experiment_body,
    _run_body,
    _schema,
    state_paths,
)


def _with_record_id(payload: dict[str, object]) -> dict[str, object]:
    return {**payload, "record_id": canonical_digest(payload)}


def _record_id(record: dict[str, object], location: str) -> str:
    supplied = require_sha256(record.get("record_id"), f"{location}.record_id")
    payload = {key: value for key, value in record.items() if key != "record_id"}
    if canonical_digest(payload) != supplied:
        raise PopulationError(f"{location}.record_id does not match its content")
    return supplied


def _new_state(header: dict[str, object]) -> PopulationState:
    require_exact_keys(
        header,
        {"configuration", "kind", "record_id", "schema_version", "sequence"},
        "population header",
    )
    if header["kind"] != "population":
        raise ProtocolError("population header.kind must be population")
    _schema(header["schema_version"], "population header.schema_version")
    if header["sequence"] != 0 or type(header["sequence"]) is not int:
        raise ProtocolError("population header.sequence must be 0")
    configuration = _configuration(
        header["configuration"], "population header.configuration"
    )
    normalized = _with_record_id(
        {
            "configuration": configuration,
            "kind": "population",
            "schema_version": POPULATION_SCHEMA_VERSION,
            "sequence": 0,
        }
    )
    if canonical_json(header) != canonical_json(normalized):
        raise ProtocolError("population header does not match its normalized content")
    return PopulationState(configuration=configuration, records=[header])


def _apply_record(
    state: PopulationState, record: dict[str, object], index: int
) -> None:
    require_exact_keys(
        record,
        {
            "body",
            "kind",
            "parent_record_id",
            "record_id",
            "schema_version",
            "sequence",
        },
        f"population record {index}",
    )
    _schema(record["schema_version"], f"population record {index}.schema_version")
    if record["sequence"] != index or type(record["sequence"]) is not int:
        raise PopulationError(f"population record {index} is out of sequence")
    if record["parent_record_id"] != state.head_id:
        raise PopulationError(f"population record {index} has a broken parent link")
    record_id = _record_id(record, f"population record {index}")
    kind = record["kind"]
    body = record["body"]
    if state.final_evaluation_started and kind in {
        "allocation",
        "archive",
        "candidate",
        "experiment",
    }:
        raise PopulationError(
            "population search is sealed after final evaluation starts"
        )
    if kind == "candidate":
        normalized = _candidate_body(body, state)
        candidate = cast(dict[str, object], normalized["candidate"])
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in state.candidates:
            raise PopulationError(f"duplicate candidate: {candidate_id}")
        state.candidates[candidate_id] = candidate
        state.candidate_record_ids[candidate_id] = record_id
        state.candidate_parents[candidate_id] = cast(list[str], normalized["parents"])
    elif kind == "experiment":
        normalized = _experiment_body(body)
        experiment_id = str(normalized["experiment_id"])
        if experiment_id in state.experiments:
            raise PopulationError(f"duplicate experiment: {experiment_id}")
        state.experiments[experiment_id] = cast(
            dict[str, object], normalized["experiment"]
        )
        state.experiment_record_ids[experiment_id] = record_id
    elif kind == "run":
        normalized = _run_body(body, state)
        run = cast(dict[str, object], normalized["run"])
        key = (
            str(run["candidate_id"]),
            str(run["experiment_id"]),
            str(run["replicate_id"]),
        )
        if key in state.run_keys:
            raise PopulationError(
                "duplicate candidate/experiment/replicate run identity"
            )
        run_id = str(run["run_id"])
        if run_id in state.run_record_ids:
            raise PopulationError(f"duplicate run: {run_id}")
        experiment_id = str(run["experiment_id"])
        role = state.experiments[experiment_id]["role"]
        if state.final_evaluation_started and role != "final":
            raise PopulationError(
                "development runs are forbidden after final evaluation starts"
            )
        state.run_keys.add(key)
        state.runs.append(normalized)
        state.run_record_ids[run_id] = record_id
        state.last_run_sequence_by_experiment[experiment_id] = index
        if role == "final":
            state.final_evaluation_started = True
    elif kind == "archive":
        if type(body) is not dict or "experiment_id" not in body:
            raise ProtocolError("archive record body is malformed")
        experiment_id = require_sha256(
            body["experiment_id"], "archive body.experiment_id"
        )
        normalized = _archive_body(experiment_id, state)
        if canonical_json(body) != canonical_json(normalized):
            raise PopulationError("archive record does not replay from prior evidence")
        state.archives[record_id] = normalized
        state.archive_sequences[record_id] = index
        state.latest_archive_by_experiment[experiment_id] = record_id
    elif kind == "allocation":
        normalized = _allocation_body(body, state)
        state.allocations.append((record_id, normalized))
    else:
        raise ProtocolError(
            f"population record {index}.kind must be candidate, experiment, run, archive, or allocation"
        )
    if canonical_json(body) != canonical_json(normalized):
        raise ProtocolError(f"population record {index}.body is not normalized")
    state.records.append(record)


def _read_records(ledger: Path) -> list[dict[str, object]]:
    if ledger.is_symlink():
        raise PopulationError(f"population ledger may not be a symlink: {ledger}")
    if not ledger.is_file():
        raise PopulationError(f"population ledger does not exist: {ledger}")
    try:
        text = ledger.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PopulationError(f"cannot read population ledger: {exc}") from exc
    if not text or not text.endswith("\n"):
        raise PopulationError(
            "population ledger must contain complete newline-terminated records"
        )
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise PopulationError(f"population ledger line {line_number} is empty")
        record = decode_json_object(line, PopulationError)
        if canonical_json(record) != line:
            raise PopulationError(
                f"population ledger line {line_number} is not canonical JSON"
            )
        records.append(record)
    return records


def load_state(root: Path) -> PopulationState:
    if root.is_symlink():
        raise PopulationError(f"population state may not be a symlink: {root}")
    if not root.is_dir():
        raise PopulationError(f"population state is not a directory: {root}")
    ledger, _ = state_paths(root)
    records = _read_records(ledger)
    try:
        state = _new_state(records[0])
        for index, record in enumerate(records[1:], start=1):
            _apply_record(state, record, index)
    except ProtocolError as exc:
        raise PopulationError(str(exc)) from exc
    return state


def _append(ledger: Path, record: dict[str, object]) -> None:
    flags = os.O_WRONLY | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(ledger, flags)
        with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(record) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise PopulationError(f"cannot append population ledger: {exc}") from exc


@contextmanager
def locked_state(root: Path, *, create_parent: bool = False) -> Iterator[None]:
    parent = root.parent
    if create_parent:
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PopulationError(
                f"cannot create population parent directory: {exc}"
            ) from exc
    lock = Path(f"{root}.lock")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise PopulationError(f"population state is locked: {lock}") from exc
    except OSError as exc:
        raise PopulationError(f"cannot lock population state: {exc}") from exc
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError as exc:
            raise PopulationError(
                f"cannot remove population state lock: {exc}"
            ) from exc


def initialize(root: Path, configuration: dict[str, object]) -> dict[str, object]:
    with locked_state(root, create_parent=True):
        if root.is_symlink():
            raise PopulationError(f"population state may not be a symlink: {root}")
        if root.exists():
            if not root.is_dir():
                raise PopulationError(f"population state is not a directory: {root}")
            try:
                if any(root.iterdir()):
                    raise PopulationError(f"population state is not empty: {root}")
            except OSError as exc:
                raise PopulationError(
                    f"cannot inspect population state: {exc}"
                ) from exc
        else:
            try:
                root.mkdir()
            except OSError as exc:
                raise PopulationError(f"cannot create population state: {exc}") from exc
        header = _with_record_id(
            {
                "configuration": configuration,
                "kind": "population",
                "schema_version": POPULATION_SCHEMA_VERSION,
                "sequence": 0,
            }
        )
        ledger, _ = state_paths(root)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(ledger, flags, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(canonical_json(header) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise PopulationError(
                f"cannot initialize population ledger: {exc}"
            ) from exc
    return {
        "population_id": header["record_id"],
        "record_count": 1,
        "schema_version": POPULATION_SCHEMA_VERSION,
        "state_path": str(root),
    }


def append_validated_record(
    root: Path,
    state: PopulationState,
    kind: str,
    body: dict[str, object],
) -> dict[str, object]:
    """Append one body while the caller holds the population-state lock."""

    sequence = len(state.records)
    record = _with_record_id(
        {
            "body": body,
            "kind": kind,
            "parent_record_id": state.head_id,
            "schema_version": POPULATION_SCHEMA_VERSION,
            "sequence": sequence,
        }
    )
    try:
        _apply_record(state, record, sequence)
    except ProtocolError as exc:
        raise PopulationError(str(exc)) from exc
    ledger, _ = state_paths(root)
    _append(ledger, record)
    response: dict[str, object] = {
        "kind": kind,
        "record_id": record["record_id"],
        "schema_version": POPULATION_SCHEMA_VERSION,
        "sequence": sequence,
    }
    if kind == "candidate":
        candidate = cast(dict[str, object], body["candidate"])
        response["candidate_id"] = candidate["candidate_id"]
    elif kind == "experiment":
        response["experiment_id"] = body["experiment_id"]
    elif kind == "run":
        run = cast(dict[str, object], body["run"])
        response["run_id"] = run["run_id"]
    elif kind == "archive":
        members = cast(list[dict[str, object]], body["members"])
        response["member_candidate_ids"] = [
            member["candidate_id"] for member in members
        ]
    elif kind == "allocation":
        result = cast(dict[str, object], body["result"])
        response["selected_candidate_id"] = result["selected_candidate_id"]
    return response


def verify_summary(state: PopulationState, root: Path) -> dict[str, object]:
    return {
        "allocation_count": len(state.allocations),
        "archive_count": len(state.archives),
        "candidate_count": len(state.candidates),
        "experiment_count": len(state.experiments),
        "final_evaluation_started": state.final_evaluation_started,
        "head_record_id": state.head_id,
        "record_count": len(state.records),
        "run_count": len(state.runs),
        "schema_version": POPULATION_SCHEMA_VERSION,
        "state_path": str(root),
    }
