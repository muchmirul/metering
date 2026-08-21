"""Append-only JSONL traces and canonical run-artifact I/O.

Every Metering artifact has exactly one valid byte representation.  Keys are
sorted, separators are compact, the encoding is UTF-8, and each document ends
with one newline.  Having a single representation is what makes a SHA-256 hash
a meaningful binding, because two readers of the same values always produce the
same bytes.

Reading is deliberately stricter than the JSON standard.  Duplicate object keys
and non-finite numbers are rejected rather than resolved, since either one
would let two readers disagree about what a file says.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from .events import Event, EventError
from .schema import EVENT_RUN_STARTED, SchemaError


class TraceError(SchemaError):
    """Raised when a trace or artifact is malformed."""


def canonical_json(value: Any) -> str:
    """Encode finite JSON deterministically."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise TraceError("value is not finite canonical JSON") from exc


def canonical_document_bytes(value: Any) -> bytes:
    """Return the exact bytes used for a canonical JSON artifact."""

    return (canonical_json(value) + "\n").encode("utf-8")


def canonical_events_bytes(events: Iterable[Event]) -> bytes:
    """Return the exact canonical JSONL bytes for decoded events."""

    return b"".join(canonical_document_bytes(event.to_dict()) for event in events)


def sha256_hex(data: bytes) -> str:
    if type(data) is not bytes:
        raise TraceError("sha256 input must be bytes")
    return hashlib.sha256(data).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TraceError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise TraceError(f"non-finite JSON number is forbidden: {token}")


def _parse_finite_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise TraceError(f"non-finite JSON number is forbidden: {token}")
    return value


def strict_json_loads(text: str, *, context: str = "JSON") -> Any:
    """Decode RFC-style finite JSON while rejecting every duplicate key."""

    if type(text) is not str:
        raise TraceError(f"{context} input must be text")
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
            parse_float=_parse_finite_float,
        )
    except TraceError:
        raise
    except json.JSONDecodeError as exc:
        raise TraceError(f"invalid {context}: {exc}") from exc


def write_json_atomic(path: str | Path, value: Any, *, private: bool = False) -> Path:
    """Atomically write a canonical JSON document followed by one newline."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_document_bytes(value)
    mode = 0o600 if private else 0o644
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    # The descriptor is closed by exactly one owner.  Until os.fdopen succeeds
    # that owner is this function; afterwards it is the file object, and closing
    # the raw number a second time could reach an unrelated file that reused it.
    try:
        os.fchmod(file_descriptor, mode)
        handle = os.fdopen(file_descriptor, "wb")
    except BaseException:
        os.close(file_descriptor)
        temporary.unlink(missing_ok=True)
        raise
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def read_json_bytes(path: str | Path) -> tuple[dict[str, Any], bytes]:
    """Read one strict JSON object and return it with its exact file bytes."""

    source = Path(path)
    try:
        raw = source.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TraceError(f"cannot read JSON artifact {source}: {exc}") from exc
    value = strict_json_loads(text, context=f"JSON artifact {source}")
    if type(value) is not dict:
        raise TraceError(f"JSON artifact {source} must contain an object")
    return value, raw


def read_json(path: str | Path) -> dict[str, Any]:
    """Read a strict finite JSON artifact whose root is an object."""

    value, _ = read_json_bytes(path)
    return value


@dataclass(frozen=True, slots=True)
class RunPaths:
    """The four Metering artifact paths in one run directory."""

    run_dir: Path

    @classmethod
    def at(cls, run_dir: str | Path) -> "RunPaths":
        return cls(Path(run_dir))

    @property
    def manifest(self) -> Path:
        return self.run_dir / "manifest.json"

    @property
    def events(self) -> Path:
        return self.run_dir / "events.jsonl"

    @property
    def reference(self) -> Path:
        return self.run_dir / "reference.json"

    @property
    def report(self) -> Path:
        return self.run_dir / "report.json"


class TraceWriter:
    """Create and append to a new trace without rewriting earlier events.

    The file is opened with exclusive creation.  One writer owns it for the
    duration of a run, and every append checks both event identity and the next
    monotonic step.
    """

    def __init__(self, path: str | Path, *, sync: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._handle = self.path.open("xb", buffering=0)
        except OSError as exc:
            raise TraceError(f"cannot create trace {self.path}: {exc}") from exc
        self._sync = sync
        self._next_step = 0
        self._identity: tuple[str, str, str, str, str] | None = None
        self._closed = False

    def append(self, event: Event) -> None:
        if self._closed:
            raise TraceError("cannot append to a closed trace")
        if type(event) is not Event:
            raise TraceError("TraceWriter.append requires an exact Event")
        if type(event.step) is not int or event.step != self._next_step:
            raise TraceError(
                f"event step {event.step!r} does not match expected {self._next_step}"
            )
        identity = (
            event.run_id,
            event.world_id,
            event.world_version,
            event.instance_id,
            event.instance_version,
        )
        if self._identity is None:
            self._identity = identity
        elif identity != self._identity:
            raise TraceError("event identity changed within one trace")
        try:
            self._handle.write(canonical_document_bytes(event.to_dict()))
            if self._sync:
                os.fsync(self._handle.fileno())
        except OSError as exc:
            raise TraceError(f"cannot append trace event: {exc}") from exc
        self._next_step += 1

    @property
    def next_step(self) -> int:
        return self._next_step

    def close(self) -> None:
        if not self._closed:
            try:
                if self._sync:
                    os.fsync(self._handle.fileno())
            finally:
                self._handle.close()
                self._closed = True

    def __enter__(self) -> "TraceWriter":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class TraceReader:
    """Decode a trace while validating schemas, identity, and step order."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def __iter__(self) -> Iterator[Event]:
        expected_step = 0
        identity: tuple[str, str, str, str, str] | None = None
        try:
            handle = self.path.open("r", encoding="utf-8", newline="")
        except OSError as exc:
            raise TraceError(f"cannot open trace {self.path}: {exc}") from exc
        with handle:
            try:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        raise TraceError(f"blank line at trace line {line_number}")
                    try:
                        data = strict_json_loads(
                            line, context=f"event at trace line {line_number}"
                        )
                        if type(data) is not dict:
                            raise TraceError(
                                f"event at trace line {line_number} must be an object"
                            )
                        event = Event.from_dict(data)
                    except (TraceError, EventError, TypeError) as exc:
                        raise TraceError(
                            f"invalid event at trace line {line_number}: {exc}"
                        ) from exc
                    if type(event.step) is not int or event.step != expected_step:
                        raise TraceError(
                            f"trace step {event.step!r} at line {line_number}; "
                            f"expected monotonic step {expected_step}"
                        )
                    event_identity = (
                        event.run_id,
                        event.world_id,
                        event.world_version,
                        event.instance_id,
                        event.instance_version,
                    )
                    if identity is None:
                        identity = event_identity
                    elif event_identity != identity:
                        raise TraceError(
                            f"event identity changed at trace line {line_number}"
                        )
                    yield event
                    expected_step += 1
            except UnicodeDecodeError as exc:
                raise TraceError(f"trace is not valid UTF-8: {exc}") from exc

    def load(self, *, require_nonempty: bool = True) -> tuple[Event, ...]:
        events = tuple(self)
        if require_nonempty and not events:
            raise TraceError("trace is empty")
        return events


def read_events(path: str | Path) -> tuple[Event, ...]:
    return TraceReader(path).load()


def interaction_signature(events: Iterable[Event]) -> tuple[str, ...]:
    """Return a deterministic signature of what happened during a run.

    Two runs of the same seeded policy against the same state produce different
    run identifiers and different artifact-set identifiers, because those are
    generated fresh each time.  Masking them leaves the part that determinism
    actually claims: the same actions, observations, and costs in the same
    order.
    """

    signatures: list[str] = []
    for event in events:
        payload = dict(event.payload)
        if event.event_type == EVENT_RUN_STARTED and "artifact_set_id" in payload:
            payload["artifact_set_id"] = "<artifact-set-id>"
        signatures.append(
            canonical_json(
                {
                    "event_type": event.event_type,
                    "payload": payload,
                    "resources": event.resources.to_dict(),
                }
            )
        )
    return tuple(signatures)
