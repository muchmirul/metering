"""Projection-only six-stage status for the Darwinian coding workflow."""

from __future__ import annotations

from pathlib import Path

from apps._support.durable import atomic_write, reject_symlink
from apps._support.wire import canonical_json, decode_json_object

PROCESS_SCHEMA = "darwinian-coding-process-v1"
PROCESS_AUTHORITY = "projection-only"
TOTAL_STAGES = 6
STAGE_LABELS = {
    1: "Task and runtime configured",
    2: "Evolving harness",
    3: "Harness sealed",
    4: "Evolving solution",
    5: "Protected final assay",
    6: "Result ready for review",
}
RUN_STAGES = {
    "harness": {1, 2, 3},
    "solution": {4, 5, 6},
}


class ProcessTrackerError(RuntimeError):
    """Raised when a process-status projection is malformed or unsafe."""


def process_document(stage: int, run_kind: str) -> dict[str, object]:
    if run_kind not in RUN_STAGES or stage not in RUN_STAGES[run_kind]:
        raise ProcessTrackerError("process stage does not match its run kind")
    label = STAGE_LABELS[stage]
    return {
        "authority": PROCESS_AUTHORITY,
        "display": f"[{stage}/{TOTAL_STAGES}] {label}",
        "process_schema": PROCESS_SCHEMA,
        "run_kind": run_kind,
        "stage": stage,
        "stage_label": label,
        "total_stages": TOTAL_STAGES,
    }


def load_process_status(
    root: Path, *, expected_run_kind: str | None = None
) -> dict[str, object] | None:
    path = root.expanduser().absolute() / "process-status.json"
    reject_symlink(path, "coding process status", ProcessTrackerError)
    if not path.exists():
        return None
    if not path.is_file():
        raise ProcessTrackerError("coding process status must be a regular file")
    try:
        source = path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise ProcessTrackerError(f"cannot read coding process status: {exc}") from exc
    document = decode_json_object(source, ProcessTrackerError)
    if source != canonical_json(document) + "\n" or set(document) != {
        "authority",
        "display",
        "process_schema",
        "run_kind",
        "stage",
        "stage_label",
        "total_stages",
    }:
        raise ProcessTrackerError("coding process status is not canonical")
    stage = document["stage"]
    run_kind = document["run_kind"]
    if type(stage) is not int or type(run_kind) is not str:
        raise ProcessTrackerError("coding process status identity is malformed")
    expected = process_document(stage, run_kind)
    if document != expected or (
        expected_run_kind is not None and run_kind != expected_run_kind
    ):
        raise ProcessTrackerError("coding process status does not replay")
    return document


def advance_process_status(
    root: Path, *, stage: int, run_kind: str
) -> dict[str, object]:
    root = root.expanduser().absolute()
    reject_symlink(root, "coding process root", ProcessTrackerError)
    if not root.is_dir():
        raise ProcessTrackerError("coding process root must be a directory")
    current = load_process_status(root, expected_run_kind=run_kind)
    if current is not None and int(current["stage"]) > stage:
        return current
    document = process_document(stage, run_kind)
    path = root / "process-status.json"
    source = (canonical_json(document) + "\n").encode("ascii")
    if current != document:
        atomic_write(path, source)
    return document


__all__ = [
    "PROCESS_SCHEMA",
    "ProcessTrackerError",
    "STAGE_LABELS",
    "TOTAL_STAGES",
    "advance_process_status",
    "load_process_status",
    "process_document",
]
