"""Content-addressed history for explicit Metering request/response pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from . import __version__


SCHEMA_VERSION = 1
_RECORD_KEYS = frozenset(
    {
        "metering_version",
        "pair_id",
        "parent_record_id",
        "request",
        "response",
        "schema_version",
    }
)
_RESPONSE_KEYS = frozenset({"base", "infinite", "measure", "value"})
_OBJECT_ID = re.compile(r"[0-9a-f]{64}").fullmatch


class CommandError(ValueError):
    """Raised when command-line arguments are malformed."""


class HistoryError(RuntimeError):
    """Raised when a measurement history is malformed or unavailable."""


class MeasurementRejected(RuntimeError):
    """Carries a normal rejection from the public Metering command."""

    def __init__(self, stderr: str) -> None:
        super().__init__(stderr)
        self.stderr = stderr


class _StrictArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CommandError(f"invalid command line: {message}")


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = _StrictArgumentParser(
        prog="metering-history",
        description=(
            "Record and inspect a linear, content-addressed history of "
            "Metering requests and responses."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser(
        "record",
        help="measure one JSON request from stdin and append its pair",
        allow_abbrev=False,
    )
    record.add_argument("history", type=Path, help="history directory")

    log = subparsers.add_parser(
        "log",
        help="print the reachable records newest first",
        allow_abbrev=False,
    )
    log.add_argument("history", type=Path, help="history directory")

    verify = subparsers.add_parser(
        "verify",
        help="verify object hashes, parent links, and reachability",
        allow_abbrev=False,
    )
    verify.add_argument("history", type=Path, help="history directory")
    return parser


def _write_json(stream: Any, value: dict[str, Any]) -> None:
    stream.write(canonical_json(value) + "\n")


def _write_error(code: str, message: str) -> None:
    _write_json(sys.stderr, {"error": {"code": code, "message": message}})


def _decode_successful_request(text: str) -> dict[str, Any]:
    value = json.loads(text, parse_float=float, parse_int=float)
    if type(value) is not dict:
        raise HistoryError("Metering accepted a request that is not an object")
    return value


def _measure(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    completed = subprocess.run(
        [sys.executable, "-m", "metering"],
        input=text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 2 and not completed.stdout and completed.stderr:
        raise MeasurementRejected(completed.stderr)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit status {completed.returncode}"
        raise HistoryError(f"Metering failed: {detail}")
    if completed.stderr:
        raise HistoryError("Metering wrote to stderr for a successful request")

    try:
        request = _decode_successful_request(text)
        response = json.loads(completed.stdout)
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise HistoryError("Metering returned or accepted invalid JSON") from exc
    if type(response) is not dict:
        raise HistoryError("Metering returned a response that is not an object")
    if completed.stdout != canonical_json(response) + "\n":
        raise HistoryError("Metering returned non-canonical JSON")
    return request, response


def _prepare_history(root: Path, *, create: bool) -> Path:
    root = root.absolute()
    if root.is_symlink():
        raise HistoryError(f"history directory may not be a symlink: {root}")
    if root.exists():
        if not root.is_dir():
            raise HistoryError(f"history path is not a directory: {root}")
    elif create:
        try:
            root.mkdir(parents=True)
        except OSError as exc:
            raise HistoryError(
                f"cannot create history directory {root}: {exc}"
            ) from exc
    else:
        raise HistoryError(f"history directory does not exist: {root}")

    objects = root / "objects"
    if objects.is_symlink():
        raise HistoryError(f"history objects may not be a symlink: {objects}")
    if objects.exists():
        if not objects.is_dir():
            raise HistoryError(
                f"history objects path is not a directory: {objects}"
            )
    elif create:
        try:
            objects.mkdir()
        except OSError as exc:
            raise HistoryError(
                f"cannot create history objects {objects}: {exc}"
            ) from exc
    else:
        raise HistoryError(f"history objects directory does not exist: {objects}")
    return root


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    lock = root / "LOCK"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise HistoryError(f"history is locked: {lock}") from exc
    except OSError as exc:
        raise HistoryError(f"cannot lock history {root}: {exc}") from exc
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError as exc:
            raise HistoryError(f"cannot remove history lock {lock}: {exc}") from exc


def _validate_id(value: object, *, field: str) -> str:
    if type(value) is not str or _OBJECT_ID(value) is None:
        raise HistoryError(f"{field} must be a lowercase SHA-256 identifier")
    return value


def _read_head(root: Path) -> str | None:
    head = root / "HEAD"
    if head.is_symlink():
        raise HistoryError(f"history HEAD may not be a symlink: {head}")
    if not head.exists():
        return None
    if not head.is_file():
        raise HistoryError(f"history HEAD is not a file: {head}")
    try:
        text = head.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise HistoryError(f"cannot read history HEAD: {exc}") from exc
    if not text.endswith("\n") or text.count("\n") != 1:
        raise HistoryError("history HEAD must contain one record identifier")
    return _validate_id(text[:-1], field="history HEAD")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HistoryError(f"duplicate record key {key!r}")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise HistoryError(f"non-finite record number {token!r} is not allowed")


def _validate_record(record_id: str, payload: object) -> dict[str, Any]:
    if type(payload) is not dict or set(payload) != _RECORD_KEYS:
        raise HistoryError(f"record {record_id} has the wrong keys")
    if payload["schema_version"] != SCHEMA_VERSION or type(
        payload["schema_version"]
    ) is not int:
        raise HistoryError(f"record {record_id} has an unsupported schema version")
    if (
        type(payload["metering_version"]) is not str
        or not payload["metering_version"]
    ):
        raise HistoryError(f"record {record_id} has an invalid Metering version")
    pair_id = _validate_id(payload["pair_id"], field=f"record {record_id} pair_id")
    parent = payload["parent_record_id"]
    if parent is not None:
        _validate_id(parent, field=f"record {record_id} parent_record_id")
    request = payload["request"]
    response = payload["response"]
    if type(request) is not dict or type(response) is not dict:
        raise HistoryError(
            f"record {record_id} must contain object request and response"
        )
    if set(response) != _RESPONSE_KEYS:
        raise HistoryError(f"record {record_id} has an invalid Metering response")
    if response.get("measure") != request.get("measure"):
        raise HistoryError(f"record {record_id} request and response measures differ")
    expected_pair_id = digest({"request": request, "response": response})
    if pair_id != expected_pair_id:
        raise HistoryError(f"record {record_id} pair hash does not match its content")
    if digest(payload) != record_id:
        raise HistoryError(f"record {record_id} hash does not match its content")
    return payload


def _read_record(root: Path, record_id: str) -> dict[str, Any]:
    _validate_id(record_id, field="record identifier")
    path = root / "objects" / f"{record_id}.json"
    if path.is_symlink():
        raise HistoryError(f"record object may not be a symlink: {path}")
    if not path.is_file():
        raise HistoryError(f"missing record object: {record_id}")
    try:
        text = path.read_text(encoding="utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except HistoryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise HistoryError(f"cannot read record {record_id}: {exc}") from exc
    payload = _validate_record(record_id, payload)
    if text != canonical_json(payload) + "\n":
        raise HistoryError(f"record {record_id} is not canonical JSON")
    return {"record_id": record_id, **payload}


def _write_file_atomically(path: Path, text: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise HistoryError(f"cannot write {path}: {exc}") from exc
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _store_record(root: Path, record_id: str, payload: dict[str, Any]) -> None:
    path = root / "objects" / f"{record_id}.json"
    if path.is_symlink():
        raise HistoryError(f"record object may not be a symlink: {path}")
    if path.exists():
        existing = _read_record(root, record_id)
        if {key: existing[key] for key in _RECORD_KEYS} != payload:
            raise HistoryError(f"record identifier collision: {record_id}")
        return
    _write_file_atomically(path, canonical_json(payload) + "\n")


def _write_head(root: Path, record_id: str) -> None:
    head = root / "HEAD"
    if head.is_symlink():
        raise HistoryError(f"history HEAD may not be a symlink: {head}")
    if head.exists() and not head.is_file():
        raise HistoryError(f"history HEAD is not a file: {head}")
    _write_file_atomically(head, record_id + "\n")


def record_measurement(
    root: Path, request: dict[str, Any], response: dict[str, Any]
) -> dict[str, Any]:
    root = _prepare_history(root, create=True)
    with _locked(root):
        parent_record_id = _read_head(root)
        pair_id = digest({"request": request, "response": response})
        payload = {
            "metering_version": __version__,
            "pair_id": pair_id,
            "parent_record_id": parent_record_id,
            "request": request,
            "response": response,
            "schema_version": SCHEMA_VERSION,
        }
        record_id = digest(payload)
        _store_record(root, record_id, payload)
        _write_head(root, record_id)
    return {"record_id": record_id, **payload}


def history_log(root: Path) -> tuple[str | None, list[dict[str, Any]]]:
    root = _prepare_history(root, create=False)
    head = _read_head(root)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = head
    while current is not None:
        if current in seen:
            raise HistoryError(f"record parent cycle at {current}")
        seen.add(current)
        record = _read_record(root, current)
        records.append(record)
        current = record["parent_record_id"]
    return head, records


def verify_history(root: Path) -> dict[str, Any]:
    root = _prepare_history(root, create=False)
    if (root / "LOCK").exists():
        raise HistoryError(f"history is locked: {root / 'LOCK'}")
    head, records = history_log(root)
    reachable = {record["record_id"] for record in records}
    try:
        entries = list((root / "objects").iterdir())
    except OSError as exc:
        raise HistoryError(f"cannot list history objects: {exc}") from exc
    object_ids: set[str] = set()
    for entry in entries:
        if (
            entry.is_symlink()
            or not entry.is_file()
            or not entry.name.endswith(".json")
        ):
            raise HistoryError(f"unexpected history object entry: {entry.name}")
        object_ids.add(_validate_id(entry.name[:-5], field="object filename"))
    unreachable = sorted(object_ids - reachable)
    if unreachable:
        raise HistoryError(f"unreachable record object: {unreachable[0]}")
    return {"head": head, "records": len(records), "valid": True}


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command == "record":
            request, response = _measure(sys.stdin.read())
            result = record_measurement(arguments.history, request, response)
        elif arguments.command == "log":
            head, records = history_log(arguments.history)
            result = {"head": head, "records": records}
        else:
            result = verify_history(arguments.history)
    except CommandError as exc:
        _write_error("invalid_request", str(exc))
        return 2
    except MeasurementRejected as exc:
        sys.stderr.write(exc.stderr)
        return 2
    except HistoryError as exc:
        _write_error("invalid_history", str(exc))
        return 2

    _write_json(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
