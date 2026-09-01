"""Canonical durable state for bounded Population Driver execution."""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, unquote, urlparse

from apps._support.durable import (
    atomic_write,
    fsync_directory,
    reject_symlink,
)
from apps._support.journal import (
    append_fsynced,
    content_record,
    decode_canonical_records,
    read_complete_lines,
    validate_content_record,
)
from apps.population_driver.population_driver_protocol import (
    DRIVER_SCHEMA_VERSION,
    PopulationDriverError,
)
from apps.stdio_connector import canonical_digest, canonical_json

DRIVER_LEDGER = "driver.jsonl"
PENDING_FILE = "pending/round-intent.json"
RECEIPT_DIRECTORY = "receipts"
LOCK_SUFFIX = ".lock"


def _reject_symlink(path: Path, location: str) -> None:
    reject_symlink(path, location, PopulationDriverError)


@contextmanager
def locked_driver(state_root: Path) -> Iterator[None]:
    """Hold the state-adjacent exclusive lock for one driver transition."""

    state_root = state_root.expanduser().absolute()
    _reject_symlink(state_root, "driver state")
    state_root.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_root.with_name(state_root.name + LOCK_SUFFIX)
    _reject_symlink(lock_path, "driver lock")
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PopulationDriverError(
            f"Population Driver state is locked: {lock_path}"
        ) from exc
    try:
        payload = f"pid={os.getpid()} started_unix_ns={time.time_ns()}\n".encode()
        os.write(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _record_with_id(body: dict[str, object]) -> dict[str, object]:
    if "record_id" in body:
        raise PopulationDriverError("driver record body must not contain record_id")
    return content_record(body, PopulationDriverError)


def create_driver_ledger(
    state_root: Path, header: dict[str, object]
) -> dict[str, object]:
    state_root.mkdir(parents=True, exist_ok=True)
    ledger = state_root / DRIVER_LEDGER
    record = _record_with_id(header)
    append_fsynced(ledger, record, create=True)
    fsync_directory(state_root)
    return record


def append_driver_record(
    state_root: Path, body: dict[str, object]
) -> dict[str, object]:
    ledger = state_root / DRIVER_LEDGER
    _reject_symlink(ledger, "driver ledger")
    record = _record_with_id(body)
    append_fsynced(ledger, record)
    return record


def read_driver_records(state_root: Path) -> list[dict[str, object]]:
    ledger = state_root / DRIVER_LEDGER
    lines = read_complete_lines(
        ledger,
        PopulationDriverError,
        label="driver ledger",
    )
    records = decode_canonical_records(
        lines,
        PopulationDriverError,
        label="driver ledger",
    )
    for line_number, record in enumerate(records, start=1):
        try:
            validate_content_record(
                record,
                PopulationDriverError,
                f"driver ledger line {line_number}",
            )
        except PopulationDriverError as exc:
            raise PopulationDriverError(
                f"driver ledger line {line_number} has an invalid record_id"
            ) from exc
    if not records:
        raise PopulationDriverError("driver ledger must contain a header")
    return records


def _unique_object(pairs: list[tuple[str, object]], location: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PopulationDriverError(f"{location} contains duplicate key: {key}")
        result[key] = value
    return result


def _non_finite(token: str, location: str) -> object:
    raise PopulationDriverError(f"{location} contains non-finite number: {token}")


def _atomic_write(path: Path, payload: bytes) -> None:
    _reject_symlink(path, str(path))
    atomic_write(path, payload)


def _pending_with_id(body: dict[str, object]) -> dict[str, object]:
    if "pending_id" in body:
        raise PopulationDriverError("pending body must not contain pending_id")
    document = dict(body)
    document["pending_id"] = canonical_digest(body)
    return document


def write_pending(state_root: Path, body: dict[str, object]) -> dict[str, object]:
    document = _pending_with_id(body)
    path = state_root / PENDING_FILE
    _atomic_write(path, (canonical_json(document) + "\n").encode("utf-8"))
    return document


def read_pending(state_root: Path) -> dict[str, object] | None:
    path = state_root / PENDING_FILE
    _reject_symlink(path, "pending round intent")
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PopulationDriverError(f"cannot read pending round intent: {exc}") from exc
    try:
        source = payload.decode("utf-8")
    except UnicodeError as exc:
        raise PopulationDriverError("pending round intent is not UTF-8") from exc
    if not source.endswith("\n") or source.count("\n") != 1:
        raise PopulationDriverError(
            "pending round intent must be one newline-terminated JSON object"
        )
    raw = source[:-1]
    try:
        document = json.loads(
            raw,
            object_pairs_hook=lambda pairs: _unique_object(
                pairs, "pending round intent"
            ),
            parse_constant=lambda token: _non_finite(token, "pending round intent"),
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise PopulationDriverError(
            f"pending round intent is invalid JSON: {exc}"
        ) from exc
    if type(document) is not dict or canonical_json(document) != raw:
        raise PopulationDriverError("pending round intent is not canonical JSON")
    pending_id = document.get("pending_id")
    body = {key: value for key, value in document.items() if key != "pending_id"}
    if type(pending_id) is not str or pending_id != canonical_digest(body):
        raise PopulationDriverError("pending round intent has an invalid pending_id")
    return document


def remove_pending(state_root: Path) -> None:
    path = state_root / PENDING_FILE
    _reject_symlink(path, "pending round intent")
    try:
        path.unlink()
    except FileNotFoundError:
        return
    fsync_directory(path.parent)


def _receipt_uri(name: str) -> str:
    return f"population-driver-receipt:///{quote(name, safe='')}"


def _receipt_name(reference: dict[str, object]) -> str:
    uri = reference.get("uri")
    name = reference.get("name")
    if type(uri) is not str or type(name) is not str:
        raise PopulationDriverError("receipt reference is malformed")
    parsed = urlparse(uri)
    if (
        parsed.scheme != "population-driver-receipt"
        or parsed.netloc
        or parsed.params
        or parsed.query
        or parsed.fragment
        or unquote(parsed.path.removeprefix("/")) != name
    ):
        raise PopulationDriverError("receipt reference URI is malformed")
    if not name or name != Path(name).name or "/" in name or "\\" in name:
        raise PopulationDriverError("receipt reference name is unsafe")
    return name


def receipt_path(state_root: Path, name: str) -> Path:
    if not name or name != Path(name).name or "/" in name or "\\" in name:
        raise PopulationDriverError("receipt name is unsafe")
    return state_root / RECEIPT_DIRECTORY / name


def write_receipt(
    state_root: Path, name: str, document: dict[str, object]
) -> dict[str, object]:
    path = receipt_path(state_root, name)
    payload = (canonical_json(document) + "\n").encode("utf-8")
    if path.exists():
        _reject_symlink(path, "receipt")
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise PopulationDriverError(f"cannot read existing receipt: {exc}") from exc
        if existing != payload:
            raise PopulationDriverError(
                f"receipt already exists with different bytes: {name}"
            )
    else:
        _atomic_write(path, payload)
    return {
        "name": name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "uri": _receipt_uri(name),
    }


def read_receipt(state_root: Path, reference: dict[str, object]) -> dict[str, object]:
    if set(reference) != {"name", "sha256", "uri"}:
        raise PopulationDriverError("receipt reference has the wrong keys")
    name = _receipt_name(reference)
    sha256 = reference.get("sha256")
    if (
        type(sha256) is not str
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
    ):
        raise PopulationDriverError("receipt reference sha256 is malformed")
    path = receipt_path(state_root, name)
    _reject_symlink(path, "receipt")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise PopulationDriverError(f"cannot read receipt {name}: {exc}") from exc
    if hashlib.sha256(payload).hexdigest() != sha256:
        raise PopulationDriverError(f"receipt digest mismatch: {name}")
    try:
        source = payload.decode("utf-8")
    except UnicodeError as exc:
        raise PopulationDriverError(f"receipt is not UTF-8: {name}") from exc
    if not source.endswith("\n") or source.count("\n") != 1:
        raise PopulationDriverError(
            f"receipt must be one newline-terminated JSON object: {name}"
        )
    raw = source[:-1]
    try:
        document = json.loads(
            raw,
            object_pairs_hook=lambda pairs: _unique_object(pairs, f"receipt {name}"),
            parse_constant=lambda token: _non_finite(token, f"receipt {name}"),
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise PopulationDriverError(f"receipt is invalid JSON: {name}: {exc}") from exc
    if type(document) is not dict or canonical_json(document) != raw:
        raise PopulationDriverError(f"receipt is not canonical JSON: {name}")
    return document


def receipt_reference_for_existing(
    state_root: Path, name: str
) -> dict[str, object] | None:
    path = receipt_path(state_root, name)
    _reject_symlink(path, "receipt")
    if not path.exists():
        return None
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise PopulationDriverError(f"cannot read receipt {name}: {exc}") from exc
    return {
        "name": name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "uri": _receipt_uri(name),
    }


def validate_record_chain(records: list[dict[str, object]]) -> None:
    previous: str | None = None
    for sequence, record in enumerate(records):
        expected_kind = "population-driver" if sequence == 0 else "round"
        if (
            record.get("schema_version") != DRIVER_SCHEMA_VERSION
            or type(record.get("schema_version")) is not int
        ):
            raise PopulationDriverError(
                f"driver record {sequence} has the wrong schema_version"
            )
        if record.get("kind") != expected_kind:
            raise PopulationDriverError(f"driver record {sequence} has the wrong kind")
        if (
            record.get("sequence") != sequence
            or type(record.get("sequence")) is not int
        ):
            raise PopulationDriverError(
                f"driver record {sequence} has the wrong sequence"
            )
        if record.get("parent_record_id") != previous:
            raise PopulationDriverError(
                f"driver record {sequence} has the wrong parent_record_id"
            )
        previous = str(record["record_id"])
