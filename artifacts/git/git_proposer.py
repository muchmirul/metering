"""Trusted Git proposal plumbing shared by concrete fixed agent connectors.

This bridge exposes no protected cases or evaluator results. It is not an OS
sandbox; callers must isolate untrusted models, repositories, and build commands.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

from apps.agent_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    GIT_ARTIFACT_SCHEMA,
    ProtocolError,
    decode_agent_artifact,
    decode_candidate,
    normalize_json_value,
    require_exact_keys,
)
from apps._support.wire import (
    canonical_json,
    decode_json_object,
)

from artifacts.git.git_repository import (
    GitCandidateError,
    changed_paths,
    clone_verified,
    content_sha256,
    copy_candidate_files,
    replace_worktree,
    run_git,
    validate_workspace,
)

ROOT = Path(__file__).resolve().parents[2]

WorkspaceEditor = Callable[[Path, str], None]


class ProposerError(RuntimeError):
    """Raised when an agent does not produce one valid Git challenger."""


def _json_string_array(name: str, *, required: bool) -> list[str] | None:
    source = os.environ.get(name)
    if source is None:
        if required:
            raise ProposerError(f"{name} must contain a non-empty JSON string array")
        return None
    if not source.strip():
        raise ProposerError(f"{name} must contain a non-empty JSON string array")
    try:
        value = json.loads(source)
    except json.JSONDecodeError as exc:
        raise ProposerError(f"{name} is invalid JSON: {exc}") from exc
    if (
        type(value) is not list
        or not value
        or any(type(item) is not str or not item or "\x00" in item for item in value)
    ):
        raise ProposerError(f"{name} must contain a non-empty JSON string array")
    return value


def _decode_request(
    source: str,
) -> tuple[dict[str, object], dict[str, object]]:
    request = decode_json_object(source, ProposerError)
    try:
        require_exact_keys(
            request,
            {"context", "parent", "protocol_version"},
            "request",
        )
        if (
            type(request["protocol_version"]) is not int
            or request["protocol_version"] != ADAPTER_PROTOCOL_VERSION
        ):
            raise ProtocolError("unsupported proposal adapter protocol")
        parent = decode_candidate(request["parent"], "parent")
        artifact = cast(dict[str, object], parent["artifact"])
        if artifact["artifact_schema"] != GIT_ARTIFACT_SCHEMA:
            raise ProtocolError("parent must contain a git-candidate-v1 artifact")
        context = normalize_json_value(request["context"], "context")
        if type(context) is not dict:
            raise ProtocolError("context must be a JSON object")
        generation = context.get("generation")
        if type(generation) is not int or generation < 1:
            raise ProtocolError("context.generation must be a positive integer")
    except ProtocolError as exc:
        raise ProposerError(str(exc)) from exc
    return artifact, cast(dict[str, object], context)


def agent_prompt(context: dict[str, object], artifact: dict[str, object]) -> str:
    """Return the exact bounded workspace-editing prompt for every connector."""

    return (
        "Modify files only inside the current disposable candidate workspace to "
        "make one bounded improvement for the caller-approved objective. Do not "
        "run git, create commits, edit outside the workspace, or claim that the "
        "change improved. Keep the declared entrypoint present. A separate "
        "evaluator decides retention. Finish after editing the files.\n\n"
        f"Parent Git artifact: {canonical_json(artifact)}\n"
        f"Caller-approved context: {canonical_json(context)}"
    )


def _timeout(name: str, default: int) -> int:
    source = os.environ.get(name, str(default))
    try:
        value = int(source)
    except ValueError as exc:
        raise ProposerError(f"{name} must be an integer") from exc
    if not 1 <= value <= 3600:
        raise ProposerError(f"{name} must be from 1 through 3600")
    return value


def _run_workspace_command(
    name: str,
    command: list[str],
    workspace: Path,
    *,
    request: dict[str, object] | None = None,
) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            input=None if request is None else canonical_json(request),
            capture_output=True,
            text=True,
            check=False,
            timeout=_timeout(f"{name}_TIMEOUT", 300),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProposerError(f"{name} could not complete: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ProposerError(detail or f"{name} failed")
    if completed.stderr:
        raise ProposerError(f"{name} wrote unexpected standard error")
    return completed.stdout


def _validate(workspace: Path) -> None:
    validate_workspace(workspace)
    command = cast(
        list[str],
        _json_string_array("METERING_GIT_VALIDATE_COMMAND", required=True),
    )
    _run_workspace_command("METERING_GIT_VALIDATE", command, workspace)
    validate_workspace(workspace)


def _build_outputs(
    workspace: Path,
    parent: dict[str, object],
    context: dict[str, object],
) -> list[dict[str, object]]:
    command = _json_string_array("METERING_GIT_BUILD_COMMAND", required=False)
    if command is None:
        return cast(list[dict[str, object]], parent["outputs"])
    source = _run_workspace_command(
        "METERING_GIT_BUILD",
        command,
        workspace,
        request={
            "context": context,
            "parent_artifact": parent,
            "protocol_version": 1,
        },
    )
    response = decode_json_object(source, ProposerError)
    if set(response) != {"outputs"} or type(response["outputs"]) is not list:
        raise ProposerError("build command must return exactly one outputs array")
    validate_workspace(workspace)
    return cast(list[dict[str, object]], response["outputs"])


def _allowed_paths() -> list[str]:
    paths = cast(
        list[str],
        _json_string_array("METERING_GIT_ALLOWED_PATHS_JSON", required=True),
    )
    for path in paths:
        parts = path.split("/")
        if (
            path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", "..", ".git"} for part in parts)
        ):
            raise ProposerError(
                "METERING_GIT_ALLOWED_PATHS_JSON contains an unsafe path"
            )
    return paths


def _require_allowed_changes(paths: list[str], allowed: list[str]) -> None:
    for path in paths:
        if not any(
            path == prefix or path.startswith(prefix.rstrip("/") + "/")
            for prefix in allowed
        ):
            raise ProposerError(f"candidate changed disallowed path: {path}")


def _commit_challenger(
    repository: Path,
    workspace: Path,
    parent: dict[str, object],
    context: dict[str, object],
    outputs: list[dict[str, object]],
) -> tuple[dict[str, object], str]:
    replace_worktree(repository, workspace)
    run_git(["add", "--all"], cwd=repository)
    paths = changed_paths(repository)
    if not paths:
        raise ProposerError("agent and build command did not change the candidate")
    _require_allowed_changes(paths, _allowed_paths())
    tree = run_git(["write-tree"], cwd=repository).strip()
    generation = cast(int, context["generation"])
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_AUTHOR_EMAIL": "metering-evolution@example.invalid",
        "GIT_AUTHOR_NAME": "Metering Evolution",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_EMAIL": "metering-evolution@example.invalid",
        "GIT_COMMITTER_NAME": "Metering Evolution",
    }
    parent_commit = str(parent["commit"])
    commit = run_git(
        ["commit-tree", tree, "-p", parent_commit],
        cwd=repository,
        input_text=f"Evolution generation {generation}\n",
        environment=environment,
    ).strip()
    candidate = {
        "artifact_schema": GIT_ARTIFACT_SCHEMA,
        "commit": commit,
        "content_sha256": content_sha256(repository, commit),
        "entrypoint": parent["entrypoint"],
        "git_tree": tree,
        "outputs": outputs,
        "repository": parent["repository"],
    }
    try:
        candidate = decode_agent_artifact(candidate, "challenger artifact")
    except ProtocolError as exc:
        raise ProposerError(str(exc)) from exc
    ref_prefix = os.environ.get("METERING_GIT_REF_PREFIX")
    if not ref_prefix:
        raise ProposerError("METERING_GIT_REF_PREFIX must name a branch prefix")
    published_ref = (
        f"{ref_prefix.rstrip('/')}/generation-{generation:06d}-{commit[:12]}"
    )
    run_git(["check-ref-format", published_ref], cwd=repository)
    run_git(
        ["push", "--quiet", "origin", f"{commit}:{published_ref}"],
        cwd=repository,
    )
    return candidate, published_ref


def propose(
    source: str,
    *,
    agent_name: str,
    edit_workspace: WorkspaceEditor,
) -> dict[str, object]:
    parent, context = _decode_request(source)
    with tempfile.TemporaryDirectory(prefix="metering-git-proposer-") as temporary:
        root = Path(temporary)
        repository = root / "repository"
        clone_verified(parent, repository)
        workspace = root / "workspace"
        copy_candidate_files(repository, workspace)
        edit_workspace(workspace, agent_prompt(context, parent))
        _validate(workspace)
        outputs = _build_outputs(workspace, parent, context)
        _validate(workspace)
        challenger, published_ref = _commit_challenger(
            repository, workspace, parent, context, outputs
        )
    return {
        "challenger_artifact": challenger,
        "reason": (
            f"{agent_name} produced immutable Git commit "
            f"{challenger['commit']} at {published_ref}"
        ),
    }


def run_main(*, agent_name: str, edit_workspace: WorkspaceEditor) -> int:
    try:
        response = propose(
            sys.stdin.read(),
            agent_name=agent_name,
            edit_workspace=edit_workspace,
        )
    except (
        GitCandidateError,
        ProposerError,
        ProtocolError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0
