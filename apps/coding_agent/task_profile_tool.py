#!/usr/bin/env python3
"""Create a reviewed Agentvolve task profile from a session-derived draft."""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from apps._support.durable import atomic_write
from apps._support.wire import (
    canonical_json,
    decode_json_object,
    write_document,
)
from apps.agent_protocol import ProtocolError, require_exact_keys
from apps.coding_agent.protocol import CodingTaskError, load_task_profile
from artifacts.git.git_repository import GitCandidateError, run_git

DRAFT_SCHEMA = "agentvolve-session-task-draft-v1"
FINAL_POLICY = "replay-development-checks-v1"
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TaskRegistrationError(ValueError):
    """Raised when a session draft cannot become an approved task profile."""


def _object(value: object, location: str) -> dict[str, object]:
    if type(value) is not dict:
        raise TaskRegistrationError(f"{location} must be a JSON object")
    return cast(dict[str, object], value)


def _integer(value: object, location: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise TaskRegistrationError(
            f"{location} must be an integer from {minimum} through {maximum}"
        )
    return value


def _absolute_directory(value: object, location: str) -> Path:
    if type(value) is not str:
        raise TaskRegistrationError(f"{location} must be a string")
    path = Path(value).expanduser()
    if not path.is_absolute() or path.as_posix() != value:
        raise TaskRegistrationError(f"{location} must be a normalized absolute path")
    if path.is_symlink() or not path.is_dir():
        raise TaskRegistrationError(f"{location} is absent or unsafe")
    return path


def _draft(path: Path) -> dict[str, object]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TaskRegistrationError(f"cannot read session task draft: {exc}") from exc
    try:
        document = decode_json_object(source, TaskRegistrationError)
        require_exact_keys(
            document,
            {
                "allowed_paths",
                "development_checks",
                "draft_schema",
                "entrypoint",
                "final_policy",
                "goal",
                "limits",
                "name",
                "repository_path",
                "schema_version",
                "stopping",
            },
            "session task draft",
        )
    except ProtocolError as exc:
        raise TaskRegistrationError(str(exc)) from exc
    if document["draft_schema"] != DRAFT_SCHEMA or document["schema_version"] != 1:
        raise TaskRegistrationError("session task draft schema is unsupported")
    name = document["name"]
    if type(name) is not str or not _NAME.fullmatch(name) or len(name) > 80:
        raise TaskRegistrationError(
            "session task draft.name must be a lowercase hyphenated name"
        )
    if document["final_policy"] != FINAL_POLICY:
        raise TaskRegistrationError(
            f"session task draft.final_policy must be {FINAL_POLICY}"
        )
    return document


def _head(repository: Path) -> str:
    status = run_git(["status", "--porcelain"], cwd=repository)
    if status:
        raise TaskRegistrationError(
            "session task repository must be clean so the generated profile binds what the operator reviewed"
        )
    commit = run_git(["rev-parse", "HEAD^{commit}"], cwd=repository).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise TaskRegistrationError("session task repository HEAD is not a full commit")
    return commit


def _require_entrypoint(repository: Path, commit: str, entrypoint: object) -> str:
    if type(entrypoint) is not str or not entrypoint:
        raise TaskRegistrationError("session task draft.entrypoint must be a string")
    try:
        run_git(["cat-file", "-e", f"{commit}:{entrypoint}"], cwd=repository)
    except GitCandidateError as exc:
        raise TaskRegistrationError(
            "session task entrypoint must exist in the reviewed base commit"
        ) from exc
    return entrypoint


def _new_profile_path(output_directory: Path, name: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return output_directory / f"{name}-{stamp}.task.json"


def _write_task_profile(
    profile: dict[str, object], task_path: Path
) -> dict[str, object]:
    if task_path.exists():
        raise TaskRegistrationError("generated task profile destination already exists")
    try:
        atomic_write(
            task_path, (canonical_json(profile) + "\n").encode("ascii")
        )
        normalized = load_task_profile(task_path)
    except Exception:
        task_path.unlink(missing_ok=True)
        raise
    return normalized


def create_profile(draft_path: Path, output_directory: Path) -> dict[str, object]:
    draft = _draft(draft_path.expanduser().absolute())
    repository = _absolute_directory(draft["repository_path"], "repository_path")
    output_directory = output_directory.expanduser()
    if not output_directory.is_absolute():
        raise TaskRegistrationError("task output directory must be absolute")
    if output_directory.exists() and (
        output_directory.is_symlink() or not output_directory.is_dir()
    ):
        raise TaskRegistrationError("task output directory is unsafe")
    output_directory.mkdir(parents=True, exist_ok=True)
    output_directory = output_directory.absolute()
    if output_directory.is_relative_to(repository):
        raise TaskRegistrationError(
            "generated task and protected-final profiles must be outside the task repository"
        )

    commit = _head(repository)
    entrypoint = _require_entrypoint(repository, commit, draft["entrypoint"])
    limits = _object(draft["limits"], "session task draft.limits")
    try:
        require_exact_keys(
            limits,
            {"max_proposal_calls", "max_rounds", "max_wall_seconds"},
            "session task draft.limits",
        )
    except ProtocolError as exc:
        raise TaskRegistrationError(str(exc)) from exc
    max_rounds = _integer(limits["max_rounds"], "limits.max_rounds", 1, 256)
    max_proposal_calls = _integer(
        limits["max_proposal_calls"], "limits.max_proposal_calls", 1, 1_024
    )
    if max_proposal_calls < max_rounds:
        raise TaskRegistrationError("proposal calls cannot be below rounds")
    max_wall_seconds = _integer(
        limits["max_wall_seconds"], "limits.max_wall_seconds", 1, 10**9
    )

    task_path = _new_profile_path(output_directory, str(draft["name"]))
    stem = task_path.name.removesuffix(".task.json")
    final_path = output_directory / f"{stem}.final.json"
    if final_path.exists() or task_path.exists():
        raise TaskRegistrationError("generated task profile destination already exists")

    checks = draft["development_checks"]
    final_document = {
        "checks": checks,
        "final_schema": "darwinian-coding-final-v1",
        "schema_version": 1,
    }
    final_payload = (canonical_json(final_document) + "\n").encode("ascii")
    profile: dict[str, object] = {
        "allocation_draws": [
            {"denominator": 1, "numerator": 0} for _ in range(max_rounds - 1)
        ],
        "allowed_paths": draft["allowed_paths"],
        "development_checks": checks,
        "final_assay": {
            "path": str(final_path),
            "sha256": hashlib.sha256(final_payload).hexdigest(),
        },
        "final_draw": {"denominator": 1, "numerator": 0},
        "goal": draft["goal"],
        "limits": {
            "max_proposal_calls": max_proposal_calls,
            "max_rounds": max_rounds,
            "max_wall_seconds": max_wall_seconds,
        },
        "repository": {
            "base_commit": commit,
            "entrypoint": entrypoint,
            "path": str(repository),
        },
        "schema_version": 1,
        "stopping": draft["stopping"],
        "task_schema": "darwinian-coding-task-v1",
    }
    try:
        atomic_write(final_path, final_payload)
        normalized = _write_task_profile(profile, task_path)
    except Exception:
        final_path.unlink(missing_ok=True)
        raise
    return {
        "base_commit": commit,
        "final_policy": FINAL_POLICY,
        "final_profile": str(final_path),
        "profile": str(task_path),
        "registration_schema": "agentvolve-task-registration-v1",
        "task_id": normalized["task_id"],
    }


def derive_profile(
    template_path: Path,
    goal_path: Path,
    max_rounds: int,
    output_directory: Path,
) -> dict[str, object]:
    template_path = template_path.expanduser().absolute()
    template = load_task_profile(template_path)
    try:
        goal = goal_path.expanduser().absolute().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise TaskRegistrationError(f"cannot read Agentvolve goal: {exc}") from exc
    if not goal:
        raise TaskRegistrationError("Agentvolve goal must not be empty")
    max_rounds = _integer(max_rounds, "generation limit", 1, 256)

    repository_value = cast(dict[str, str], template["repository"])
    repository = _absolute_directory(repository_value["path"], "repository path")
    output_directory = output_directory.expanduser()
    if not output_directory.is_absolute():
        raise TaskRegistrationError("task output directory must be absolute")
    if output_directory.exists() and (
        output_directory.is_symlink() or not output_directory.is_dir()
    ):
        raise TaskRegistrationError("task output directory is unsafe")
    output_directory.mkdir(parents=True, exist_ok=True)
    output_directory = output_directory.absolute()
    if output_directory.is_relative_to(repository):
        raise TaskRegistrationError(
            "generated task profile must be outside the task repository"
        )

    commit = _head(repository)
    entrypoint = _require_entrypoint(
        repository, commit, repository_value["entrypoint"]
    )
    template_limits = cast(dict[str, int], template["limits"])
    retry_reservations = max(
        0,
        template_limits["max_proposal_calls"] - template_limits["max_rounds"],
    )
    max_proposal_calls = max_rounds + retry_reservations
    if max_proposal_calls > 1_024:
        raise TaskRegistrationError(
            "derived proposal calls exceed the supported maximum"
        )

    profile: dict[str, object] = {
        "allocation_draws": [
            {"denominator": 1, "numerator": 0} for _ in range(max_rounds - 1)
        ],
        "allowed_paths": template["allowed_paths"],
        "development_checks": template["development_checks"],
        "final_assay": template["final_assay"],
        "final_draw": template["final_draw"],
        "goal": goal,
        "limits": {
            "max_proposal_calls": max_proposal_calls,
            "max_rounds": max_rounds,
            "max_wall_seconds": template_limits["max_wall_seconds"],
        },
        "repository": {
            "base_commit": commit,
            "entrypoint": entrypoint,
            "path": str(repository),
        },
        "schema_version": 1,
        "task_schema": "darwinian-coding-task-v1",
    }
    if "stopping" in template:
        stopping = cast(dict[str, object], template["stopping"])
        if int(cast(int, stopping["minimum_replicates"])) > max_rounds:
            raise TaskRegistrationError(
                "generation limit is below the template minimum replicates"
            )
        profile["stopping"] = stopping

    name = template_path.name.removesuffix(".task.json")
    task_path = _new_profile_path(output_directory, name)
    normalized = _write_task_profile(profile, task_path)
    return {
        "base_commit": commit,
        "profile": str(task_path),
        "registration_schema": "agentvolve-task-derivation-v1",
        "source_profile": str(template_path),
        "task_id": normalized["task_id"],
    }


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(arguments) == 3 and arguments[0] == "create":
            result = create_profile(Path(arguments[1]), Path(arguments[2]))
        elif len(arguments) == 5 and arguments[0] == "derive":
            try:
                max_rounds = int(arguments[3])
            except ValueError as exc:
                raise TaskRegistrationError("generation limit must be an integer") from exc
            result = derive_profile(
                Path(arguments[1]),
                Path(arguments[2]),
                max_rounds,
                Path(arguments[4]),
            )
        else:
            raise TaskRegistrationError(
                "usage: task_profile_tool.py create SESSION-DRAFT.json TASK-DIRECTORY | "
                "derive TEMPLATE.task.json GOAL.txt MAX_ROUNDS TASK-DIRECTORY"
            )
    except (
        CodingTaskError,
        GitCandidateError,
        OSError,
        TaskRegistrationError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    write_document(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
