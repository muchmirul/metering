#!/usr/bin/env python3
"""Create a reviewed Agentvolve task profile from a session-derived draft."""

from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
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
from apps.coding_agent.experiment_config import development_reservation
from apps.coding_agent.harness_workspace_editor import CodingMutationError
from apps.coding_agent.protocol import CodingTaskError, load_task_profile, normalize_task_profile
from apps.coding_agent.preflight import preflight_task
from apps.coding_agent.task_context import normalize_task_context, require_read_only_paths
from apps.harness.runtime_manifest import load_runtime_manifest
from apps.harness.workspace import normalized_path
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


def _draft(path: Path, *, workspace: bool = False) -> dict[str, object]:
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
                *({"requirements", "assumptions"} if workspace else set()),
                *({"context"} if "context" in document else set()),
                *({"reviewed_base_commit"} if "reviewed_base_commit" in document and not workspace else set()),
            },
            "session task draft",
        )
    except ProtocolError as exc:
        raise TaskRegistrationError(str(exc)) from exc
    if document["draft_schema"] != DRAFT_SCHEMA or type(document["schema_version"]) is not int or document["schema_version"] != 1:
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
    if "context" in document:
        try:
            context = normalize_task_context(document["context"])
            require_read_only_paths(context, document["allowed_paths"])
        except (TypeError, ValueError) as exc:
            raise TaskRegistrationError(str(exc)) from exc
    return document


def _head(repository: Path) -> str:
    status = run_git(["-c", "core.fsmonitor=false", "status", "--porcelain"], cwd=repository)
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
        atomic_write(task_path, (canonical_json(profile) + "\n").encode("ascii"))
        normalized = load_task_profile(task_path)
        preflight_task(normalized)
    except Exception:
        task_path.unlink(missing_ok=True)
        raise
    return normalized


def _task_document(
    draft: dict[str, object], commit: str, final_path: Path, final_digest: str
) -> dict[str, object]:
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

    profile: dict[str, object] = {
        "allocation_draws": [
            {"denominator": 1, "numerator": 0} for _ in range(max_rounds - 1)
        ],
        "allowed_paths": draft["allowed_paths"],
        "development_checks": draft["development_checks"],
        "final_assay": {
            "path": str(final_path),
            "sha256": final_digest,
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
            "entrypoint": draft["entrypoint"],
            "path": draft["repository_path"],
        },
        "schema_version": 1,
        "stopping": draft["stopping"],
        "task_schema": "darwinian-coding-task-v1",
    }
    if "context" in draft:
        profile["context"] = draft["context"]
    return profile


def validate_draft(draft_path: Path, *, workspace: bool = False) -> dict[str, object]:
    """Use the registration validators before approval, without creating any artifact."""
    draft = _draft(draft_path, workspace=workspace)
    if workspace:
        _workspace_inputs(draft)
    repository = draft["repository_path"]
    if type(repository) is not str:
        raise TaskRegistrationError("repository_path must be a string")
    # Structural placeholders only: never read, persisted, or returned as identities.
    normalize_task_profile(_task_document(
        draft, "unregistered", Path(repository).parent / "unregistered-final.json", "0" * 64,
    ))
    return {"authority": "diagnostic-only", "draft_validation_schema": "agentvolve-task-draft-validation-v1"}


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
    if "reviewed_base_commit" in draft and draft["reviewed_base_commit"] != commit:
        raise TaskRegistrationError("Repository HEAD changed during task review; prepare and approve a fresh draft")
    _require_entrypoint(repository, commit, draft["entrypoint"])
    task_path = _new_profile_path(output_directory, str(draft["name"]))
    stem = task_path.name.removesuffix(".task.json")
    final_path = output_directory / f"{stem}.final.json"
    if final_path.exists() or task_path.exists():
        raise TaskRegistrationError("generated task profile destination already exists")
    final_document = {
        "checks": draft["development_checks"], "final_schema": "darwinian-coding-final-v1", "schema_version": 1,
    }
    final_payload = (canonical_json(final_document) + "\n").encode("ascii")
    profile = _task_document(draft, commit, final_path, hashlib.sha256(final_payload).hexdigest())
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


def _workspace_inputs(draft: dict[str, object]) -> tuple[dict[str, list[str]], list[str]]:
    goal = draft["goal"]
    if type(goal) is not str or not goal.strip() or len(goal) > 65_536 or "\x00" in goal:
        raise TaskRegistrationError("workspace goal must be bounded non-empty text")
    brief: dict[str, list[str]] = {}
    for key in ("requirements", "assumptions"):
        items = draft[key]
        if (
            type(items) is not list or len(items) > 32
            or (key == "requirements" and not items)
            or any(type(item) is not str or not item.strip() or len(item) > 1000 or "\x00" in item for item in items)
        ):
            raise TaskRegistrationError(f"workspace {key} must be a bounded array of non-empty statements")
        brief[key] = items
    raw_paths = draft["allowed_paths"]
    if type(raw_paths) is not list or not 1 <= len(raw_paths) <= 64:
        raise TaskRegistrationError("workspace allowed_paths must contain 1 through 64 output files")
    paths = [normalized_path(path, "workspace output file") for path in raw_paths]
    if paths != sorted(set(paths)) or draft["entrypoint"] not in paths:
        raise TaskRegistrationError("workspace output files must be sorted and unique and include the entrypoint")
    if any(
        len(path) > 1024 or path == "TASK.md" or path.startswith("TASK.md/")
        or any(other.startswith(path + "/") for other in paths)
        for path in paths
    ):
        raise TaskRegistrationError("workspace paths conflict or include the fixed TASK.md brief")
    return brief, paths


def create_workspace_profile(draft_path: Path, output_directory: Path) -> dict[str, object]:
    """Create an approved empty seed, never a solution or a host-executed check."""
    draft = _draft(draft_path, workspace=True)
    output_directory = output_directory.expanduser()
    if not output_directory.is_absolute() or output_directory.resolve() != output_directory:
        raise TaskRegistrationError("workspace task directory must be an absolute path without symlink ancestors")
    root_text = draft["repository_path"]
    if type(root_text) is not str:
        raise TaskRegistrationError("workspace repository path must be a string")
    root = Path(root_text)
    workspace_parent = output_directory / "workspaces"
    if (
        root.as_posix() != root_text or root.parent != workspace_parent
        or not re.fullmatch(r"task-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", root.name)
        or workspace_parent.is_symlink() or root.exists() or root.is_symlink()
    ):
        raise TaskRegistrationError("workspace must be a new task-UUID directory under TASK-DIRECTORY/workspaces")
    brief, paths = _workspace_inputs(draft)
    goal = cast(str, draft["goal"])
    for key in brief:
        del draft[key]
    # No model-authored file contents, shell commands, Git hooks, or checks run here.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        workspace_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.mkdir(mode=0o700)  # Exclusive: never overwrite/reinitialize a target.
        text = "# Reviewed task\n\n## Original request\n\n" + goal + "\n\n## Requirements\n\n"
        text += "\n".join(f"- {item}" for item in brief["requirements"])
        text += "\n\n## Inferred assumptions\n\n" + ("\n".join(f"- {item}" for item in brief["assumptions"]) or "None.")
        text += "\n\nOutput files start empty. Completion requires the separately reviewed independent checks.\n"
        (root / "TASK.md").write_text(text, encoding="utf-8")
        for path in paths:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=False)
        run_git(["init", "-q", "-b", "main", "--template="], cwd=root, environment=environment, timeout_seconds=10)
        run_git(["add", "--", "TASK.md", *paths], cwd=root, environment=environment, timeout_seconds=10)
        run_git([
            "-c", "user.name=Agentvolve workspace", "-c", "user.email=agentvolve@localhost",
            "-c", "commit.gpgSign=false", "commit", "-qm", "Prepare reviewed empty task workspace",
        ], cwd=root, environment=environment, timeout_seconds=10)
        with tempfile.TemporaryDirectory(prefix="workspace-registration-", dir=output_directory) as temporary:
            prepared = Path(temporary) / "draft.json"
            prepared.write_text(canonical_json(draft) + "\n", encoding="ascii")
            result = create_profile(prepared, output_directory)
    except (OSError, ValueError, GitCandidateError) as exc:
        raise TaskRegistrationError(f"Workspace preparation failed; any created files are retained at {root}: {exc}") from exc
    return {**result, "workspace_created": True, "workspace_repository": str(root)}


def derive_profile(
    template_path: Path,
    goal_path: Path,
    max_rounds: int,
    output_directory: Path,
    *,
    max_wall_seconds: int | None = None,
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
    entrypoint = _require_entrypoint(repository, commit, repository_value["entrypoint"])
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
            "max_wall_seconds": template_limits["max_wall_seconds"] if max_wall_seconds is None else _integer(
                max_wall_seconds, "max_wall_seconds", 1, 10**9
            ),
        },
        "repository": {
            "base_commit": commit,
            "entrypoint": entrypoint,
            "path": str(repository),
        },
        "schema_version": 1,
        "task_schema": "darwinian-coding-task-v1",
    }
    if "context" in template:
        if commit != repository_value["base_commit"]:
            raise TaskRegistrationError("Grounded template HEAD changed; prepare and review a fresh source-grounded draft")
        profile["context"] = template["context"]
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


def budget_review(path: Path) -> dict[str, object]:
    """Read only public timeout/limit numbers; never profiles, checks or candidates."""
    if path.is_symlink() or not path.is_file():
        raise TaskRegistrationError("budget review must be a regular file")
    with path.open("rb") as stream:
        source = stream.read(16_385)
    if len(source) > 16_384:
        raise TaskRegistrationError("budget review exceeds 16384 bytes")
    document = decode_json_object(source.decode("utf-8"), TaskRegistrationError)
    try:
        require_exact_keys(document, {"check_timeouts_ms", "max_rounds", "max_wall_seconds"}, "budget review")
    except ProtocolError as exc:
        raise TaskRegistrationError(str(exc)) from exc
    return development_reservation(
        cast(list[int], document["check_timeouts_ms"]),
        cast(int, document["max_rounds"]), cast(int, document["max_wall_seconds"]),
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(arguments) == 2 and arguments[0] == "budget":
            result = budget_review(Path(arguments[1]))
        elif len(arguments) in {2, 4} and arguments[0] == "preflight":
            result = preflight_task(
                load_task_profile(Path(arguments[1])),
                runtime=load_runtime_manifest(Path(arguments[2]))
                if len(arguments) == 4
                else None,
                harness_source=Path(arguments[3]) if len(arguments) == 4 else None,
            )
        elif len(arguments) == 3 and arguments[0] == "validate-draft" and arguments[1] in {"existing", "workspace"}:
            result = validate_draft(Path(arguments[2]), workspace=arguments[1] == "workspace")
        elif len(arguments) == 3 and arguments[0] == "create":
            result = create_profile(Path(arguments[1]), Path(arguments[2]))
        elif len(arguments) == 3 and arguments[0] == "workspace":
            result = create_workspace_profile(Path(arguments[1]), Path(arguments[2]))
        elif len(arguments) in {5, 6} and arguments[0] == "derive":
            try:
                max_rounds = int(arguments[3])
                max_wall_seconds = int(arguments[5]) if len(arguments) == 6 else None
            except ValueError as exc:
                raise TaskRegistrationError(
                    "generation limit and optional wall budget must be integers"
                ) from exc
            result = derive_profile(
                Path(arguments[1]),
                Path(arguments[2]),
                max_rounds,
                Path(arguments[4]),
                max_wall_seconds=max_wall_seconds,
            )
        else:
            raise TaskRegistrationError(
                "usage: task_profile_tool.py create SESSION-DRAFT.json TASK-DIRECTORY | "
                "workspace REVIEWED-WORKSPACE-DRAFT.json TASK-DIRECTORY | "
                "derive TEMPLATE.task.json GOAL.txt MAX_ROUNDS TASK-DIRECTORY [MAX_WALL_SECONDS] | "
                "preflight TASK.json [RUNTIME.json SELECTED-HARNESS.json] | budget REVIEW.json | "
                "validate-draft existing|workspace DRAFT.json"
            )
    except (
        CodingMutationError,
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
