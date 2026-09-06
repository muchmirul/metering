"""Durable, non-authoritative diagnostics for failed Controller attempts."""

from __future__ import annotations

import hashlib
from pathlib import Path

from apps._support.diagnostics import exception_document
from apps._support.durable import atomic_write, reject_symlink
from apps._support.wire import canonical_digest, canonical_json
from apps.population_driver.population_driver_protocol import PopulationDriverError


def record_controller_failure(
    state_root: Path,
    *,
    attempt_id: str,
    intent_id: str,
    command: list[str],
    elapsed_milliseconds: int,
    error: BaseException,
) -> str:
    document = {
        "diagnostic_schema": "population-driver-failure-v1",
        "authority": "diagnostic-only",
        "attempt_id": attempt_id,
        "intent_id": intent_id,
        "command_sha256": canonical_digest({"command": command}),
        "operation": "controller",
        "elapsed_milliseconds": elapsed_milliseconds,
        "error": exception_document(error),
    }
    directory = state_root / "diagnostics"
    reject_symlink(directory, "diagnostic directory", PopulationDriverError)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    source = (canonical_json(document) + "\n").encode("ascii")
    digest = hashlib.sha256(source).hexdigest()
    path = directory / f"{digest}.json"
    reject_symlink(path, "diagnostic receipt", PopulationDriverError)
    if path.exists():
        if path.read_bytes() != source:
            raise PopulationDriverError("diagnostic receipt identity conflicts")
    else:
        atomic_write(path, source)
        path.chmod(0o600)
    return digest
