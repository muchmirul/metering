"""Strict caller-owned task profile for Darwinian solution evolution."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import cast

from apps._support.wire import canonical_digest, canonical_json, decode_json_object
from apps.agent_protocol import ProtocolError, require_exact_keys
from apps.harness.workspace import WorkspaceError, normalized_path
from apps.population.contract import PopulationError, normalize_draw
from apps.population_driver.population_driver_protocol import normalize_stopping_policy

TASK_SCHEMA = "darwinian-coding-task-v1"
FINAL_SCHEMA = "darwinian-coding-final-v1"
TASK_SCHEMA_VERSION = 1
MAX_PROFILE_BYTES = 2_097_152


class CodingTaskError(ValueError):
    """Raised when a coding task does not bind a usable independent assay."""


def _bounded_regular_file(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CodingTaskError(f"cannot open {label}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_PROFILE_BYTES:
            raise CodingTaskError(f"{label} must be a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            source = stream.read(MAX_PROFILE_BYTES + 1)
    except OSError as exc:
        raise CodingTaskError(f"cannot read {label}: {exc}") from exc
    finally:
        os.close(descriptor)
    if len(source) > MAX_PROFILE_BYTES:
        raise CodingTaskError(f"{label} exceeds {MAX_PROFILE_BYTES} bytes")
    return source


def _text(value: object, location: str, *, maximum: int = 65_536) -> str:
    if type(value) is not str or not value or "\x00" in value or len(value) > maximum:
        raise CodingTaskError(f"{location} must be non-empty bounded text without NUL")
    return value


def _integer(value: object, location: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CodingTaskError(
            f"{location} must be an integer from {minimum} through {maximum}"
        )
    return value


def _absolute_path(value: object, location: str) -> str:
    path_text = _text(value, location)
    path = Path(path_text)
    if (
        not path.is_absolute()
        or path.as_posix() != path_text
        or any(part in {"", ".", ".."} for part in path.parts[1:])
    ):
        raise CodingTaskError(f"{location} must be a normalized absolute POSIX path")
    return path_text


def _repository(value: object) -> dict[str, str]:
    location = "coding task.repository"
    if type(value) is not dict:
        raise CodingTaskError(f"{location} must be a JSON object")
    try:
        require_exact_keys(value, {"base_commit", "entrypoint", "path"}, location)
    except ProtocolError as exc:
        raise CodingTaskError(str(exc)) from exc
    path = _absolute_path(value["path"], f"{location}.path")
    commit = _text(value["base_commit"], f"{location}.base_commit", maximum=128)
    try:
        entrypoint = normalized_path(value["entrypoint"], f"{location}.entrypoint")
    except WorkspaceError as exc:
        raise CodingTaskError(str(exc)) from exc
    return {"base_commit": commit, "entrypoint": entrypoint, "path": path}


def _checks(value: object, location: str) -> list[dict[str, object]]:
    if type(value) is not list or not value or len(value) > 256:
        raise CodingTaskError(f"{location} must be a non-empty bounded array")
    checks: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        item_location = f"{location}[{index}]"
        if type(raw) is not dict:
            raise CodingTaskError(f"{item_location} must be a JSON object")
        try:
            require_exact_keys(raw, {"argv", "case_id", "timeout_ms"}, item_location)
        except ProtocolError as exc:
            raise CodingTaskError(str(exc)) from exc
        case_id = _text(raw["case_id"], f"{item_location}.case_id", maximum=256)
        if case_id in seen:
            raise CodingTaskError(f"{location} contains duplicate case_id: {case_id}")
        argv = raw["argv"]
        if (
            type(argv) is not list
            or not argv
            or len(argv) > 256
            or any(
                type(item) is not str or not item or "\x00" in item or len(item) > 4096
                for item in argv
            )
        ):
            raise CodingTaskError(f"{item_location}.argv is malformed")
        checks.append(
            {
                "argv": cast(list[str], argv),
                "case_id": case_id,
                "timeout_ms": _integer(
                    raw["timeout_ms"], f"{item_location}.timeout_ms", 10, 3_600_000
                ),
            }
        )
        seen.add(case_id)
    return checks


def _final_assay(value: object) -> dict[str, str]:
    location = "coding task.final_assay"
    if type(value) is not dict:
        raise CodingTaskError(f"{location} must be a JSON object")
    try:
        require_exact_keys(value, {"path", "sha256"}, location)
    except ProtocolError as exc:
        raise CodingTaskError(str(exc)) from exc
    path = _absolute_path(value["path"], f"{location}.path")
    digest = value["sha256"]
    if (
        type(digest) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise CodingTaskError(f"{location}.sha256 must be lowercase SHA-256")
    return {"path": path, "sha256": digest}


def _paths(value: object) -> list[str]:
    if type(value) is not list or not value or len(value) > 2_000:
        raise CodingTaskError("coding task.allowed_paths must be non-empty")
    paths: list[str] = []
    for index, raw in enumerate(value):
        try:
            path = normalized_path(raw, f"coding task.allowed_paths[{index}]")
        except WorkspaceError as exc:
            raise CodingTaskError(str(exc)) from exc
        if path in paths:
            raise CodingTaskError("coding task.allowed_paths contains a duplicate")
        paths.append(path)
    if paths != sorted(paths):
        raise CodingTaskError("coding task.allowed_paths must be sorted")
    return paths


def load_task_profile(
    path: Path, *, allow_legacy_inline_final: bool = False
) -> dict[str, object]:
    path = path.expanduser().absolute()
    source_bytes = _bounded_regular_file(path, "coding task profile")
    try:
        source = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodingTaskError("coding task profile must be UTF-8") from exc
    document = decode_json_object(source, CodingTaskError)
    if source != canonical_json(document) + "\n":
        raise CodingTaskError(
            "coding task profile must be canonical JSON followed by newline"
        )
    common_keys = {
        "allocation_draws",
        "allowed_paths",
        "development_checks",
        "final_draw",
        "goal",
        "limits",
        "repository",
        "schema_version",
        "task_schema",
    }
    keys = set(document)
    current_keys = {*common_keys, "final_assay"}
    legacy_keys = {*common_keys, "final_checks"}
    stopping_keys = {"stopping"}
    if keys in (legacy_keys, legacy_keys | stopping_keys):
        if not allow_legacy_inline_final:
            raise CodingTaskError(
                "inline final_checks are legacy-only; use a SHA-256-bound final_assay"
            )
        legacy = True
    elif keys in (current_keys, current_keys | stopping_keys):
        legacy = False
    else:
        raise CodingTaskError("coding task has the wrong keys")
    if document["task_schema"] != TASK_SCHEMA or document["schema_version"] != 1:
        raise CodingTaskError("coding task schema is unsupported")
    limits = document["limits"]
    if type(limits) is not dict:
        raise CodingTaskError("coding task.limits must be a JSON object")
    try:
        require_exact_keys(
            limits,
            {"max_proposal_calls", "max_rounds", "max_wall_seconds"},
            "coding task.limits",
        )
    except ProtocolError as exc:
        raise CodingTaskError(str(exc)) from exc
    normalized_limits = {
        "max_proposal_calls": _integer(
            limits["max_proposal_calls"],
            "coding task.limits.max_proposal_calls",
            1,
            1_024,
        ),
        "max_rounds": _integer(
            limits["max_rounds"], "coding task.limits.max_rounds", 1, 256
        ),
        "max_wall_seconds": _integer(
            limits["max_wall_seconds"],
            "coding task.limits.max_wall_seconds",
            1,
            10**9,
        ),
    }
    if normalized_limits["max_proposal_calls"] < normalized_limits["max_rounds"]:
        raise CodingTaskError("coding task proposal calls cannot be below rounds")
    draws = document["allocation_draws"]
    if type(draws) is not list or len(draws) != normalized_limits["max_rounds"] - 1:
        raise CodingTaskError(
            "coding task allocation_draws must contain max_rounds minus one draws"
        )
    try:
        normalized_draws = [
            normalize_draw(raw, f"coding task.allocation_draws[{index}]")
            for index, raw in enumerate(draws)
        ]
        final_draw = normalize_draw(document["final_draw"], "coding task.final_draw")
        stopping = (
            normalize_stopping_policy(document["stopping"], "coding task.stopping")
            if "stopping" in document
            else None
        )
    except (PopulationError, ValueError) as exc:
        raise CodingTaskError(str(exc)) from exc
    if (
        stopping is not None
        and int(stopping["minimum_replicates"])
        > normalized_limits["max_rounds"]
    ):
        raise CodingTaskError(
            "coding task stopping.minimum_replicates cannot exceed max_rounds"
        )
    repository = _repository(document["repository"])
    normalized = {
        "allocation_draws": normalized_draws,
        "allowed_paths": _paths(document["allowed_paths"]),
        "development_checks": _checks(
            document["development_checks"], "coding task.development_checks"
        ),
        "final_draw": final_draw,
        "goal": _text(document["goal"], "coding task.goal"),
        "limits": normalized_limits,
        "repository": repository,
        "schema_version": TASK_SCHEMA_VERSION,
        "task_schema": TASK_SCHEMA,
    }
    if stopping is not None:
        normalized["stopping"] = stopping
    if legacy:
        normalized["final_checks"] = _checks(
            document["final_checks"], "coding task.final_checks"
        )
    else:
        final_assay = _final_assay(document["final_assay"])
        if Path(final_assay["path"]).is_relative_to(Path(repository["path"])):
            raise CodingTaskError(
                "coding task.final_assay.path must be outside the repository"
            )
        normalized["final_assay"] = final_assay
    if document != normalized:
        raise CodingTaskError("coding task profile is not normalized")
    return {**normalized, "task_id": canonical_digest(normalized)}


def load_final_profile(
    profile: dict[str, object], source_override: Path | None = None
) -> tuple[bytes, list[dict[str, object]]]:
    reference = cast(dict[str, str], profile["final_assay"])
    path = (
        source_override.expanduser().absolute()
        if source_override is not None
        else Path(reference["path"]).expanduser().absolute()
    )
    source = _bounded_regular_file(path, "protected coding final profile")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodingTaskError("protected coding final profile must be UTF-8") from exc
    if hashlib.sha256(source).hexdigest() != reference["sha256"]:
        raise CodingTaskError("protected coding final profile digest does not match")
    document = decode_json_object(text, CodingTaskError)
    if text != canonical_json(document) + "\n":
        raise CodingTaskError("protected coding final profile must be canonical JSON")
    try:
        require_exact_keys(
            document,
            {"checks", "final_schema", "schema_version"},
            "protected coding final profile",
        )
    except ProtocolError as exc:
        raise CodingTaskError(str(exc)) from exc
    normalized = {
        "checks": _checks(document["checks"], "protected coding final checks"),
        "final_schema": FINAL_SCHEMA,
        "schema_version": TASK_SCHEMA_VERSION,
    }
    if document != normalized:
        raise CodingTaskError("protected coding final profile is not normalized")
    return source, cast(list[dict[str, object]], normalized["checks"])


def load_final_checks(
    profile: dict[str, object], source_override: Path | None = None
) -> list[dict[str, object]]:
    return load_final_profile(profile, source_override)[1]


def task_documents(
    profile: dict[str, object],
    role: str,
    *,
    final_checks: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    if role == "development":
        checks = cast(list[dict[str, object]], profile["development_checks"])
    elif role == "final" and final_checks is not None:
        checks = final_checks
    else:
        raise CodingTaskError("final task documents require protected checks")
    goal = str(profile["goal"])
    return [
        {
            "case_id": str(check["case_id"]),
            "input": {
                "assay": {
                    "argv": check["argv"],
                    "timeout_ms": check["timeout_ms"],
                },
                "outcomes": ["fail", "pass"],
                "prompt": goal,
            },
        }
        for check in checks
    ]
