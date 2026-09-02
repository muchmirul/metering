"""Canonical content-addressed JSONL primitives with no domain policy."""

from __future__ import annotations

import os
from pathlib import Path

from .wire import canonical_digest, canonical_json, decode_json_object


def content_record(
    body: dict[str, object],
    error_type: type[Exception],
    *,
    identity_key: str = "record_id",
) -> dict[str, object]:
    """Attach one content identity to an otherwise complete record body."""

    if identity_key in body:
        raise error_type(f"record body must not contain {identity_key}")
    return {**body, identity_key: canonical_digest(body)}


def validate_content_record(
    record: dict[str, object],
    error_type: type[Exception],
    location: str,
    *,
    identity_key: str = "record_id",
) -> str:
    """Validate and return the lowercase SHA-256 content identity."""

    supplied = record.get(identity_key)
    if (
        type(supplied) is not str
        or len(supplied) != 64
        or any(character not in "0123456789abcdef" for character in supplied)
    ):
        raise error_type(f"{location}.{identity_key} is invalid")
    body = {key: value for key, value in record.items() if key != identity_key}
    if canonical_digest(body) != supplied:
        raise error_type(f"{location}.{identity_key} does not match its content")
    return supplied


def read_complete_lines(
    path: Path,
    error_type: type[Exception],
    *,
    label: str,
    allow_missing: bool = False,
) -> list[str]:
    """Read complete nonempty UTF-8 lines, excluding newline terminators."""

    if path.is_symlink():
        raise error_type(f"{label} may not be a symlink: {path}")
    if not path.exists():
        if allow_missing:
            return []
        raise error_type(f"{label} does not exist: {path}")
    if not path.is_file():
        raise error_type(f"{label} is not a file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise error_type(f"cannot read {label}: {exc}") from exc
    if not text or not text.endswith("\n"):
        raise error_type(f"{label} must contain complete newline-terminated records")
    lines = text.splitlines()
    for line_number, line in enumerate(lines, start=1):
        if not line:
            raise error_type(f"{label} line {line_number} is empty")
    return lines


def decode_canonical_records(
    lines: list[str],
    error_type: type[Exception],
    *,
    label: str,
) -> list[dict[str, object]]:
    """Decode strict canonical JSON objects from complete journal lines."""

    records: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        record = decode_json_object(line, error_type)
        if line != canonical_json(record):
            raise error_type(f"{label} line {line_number} is not canonical JSON")
        records.append(record)
    return records


def append_fsynced(
    path: Path,
    document: dict[str, object],
    *,
    create: bool = False,
    create_if_missing: bool = False,
    mode: int = 0o600,
) -> None:
    """Write one canonical newline-terminated record and fsync it."""

    if create and create_if_missing:
        raise ValueError("create and create_if_missing are mutually exclusive")
    flags = os.O_WRONLY | os.O_APPEND
    if create:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    elif create_if_missing:
        flags |= os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    file_mode = "w" if create else "a"
    with os.fdopen(descriptor, file_mode, encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(document) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
