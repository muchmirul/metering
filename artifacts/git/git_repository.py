"""Resolve and verify immutable git-candidate-v1 source trees."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from apps.agent_protocol import (
    GIT_ARTIFACT_SCHEMA,
    ProtocolError,
    decode_agent_artifact,
)

MAX_FILES = 2_000
MAX_CONTENT_BYTES = 50 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 300


class GitCandidateError(RuntimeError):
    """Raised when a Git candidate cannot be resolved or verified."""


def run_git(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    environment: dict[str, str] | None = None,
    timeout_seconds: int = GIT_TIMEOUT_SECONDS,
) -> str:
    command = ["git", "-c", "core.hooksPath=/dev/null", *arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise GitCandidateError(f"cannot run Git: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"Git exited with {completed.returncode}"
        raise GitCandidateError(detail)
    return completed.stdout


def _tree_entries(repository: Path, commit: str) -> list[tuple[str, str, str]]:
    source = run_git(["ls-tree", "-r", "-z", commit], cwd=repository)
    if not source:
        raise GitCandidateError("candidate Git tree must not be empty")
    entries: list[tuple[str, str, str]] = []
    for raw_entry in source.split("\x00"):
        if not raw_entry:
            continue
        try:
            metadata, path = raw_entry.split("\t", 1)
            mode, object_type, object_id = metadata.split(" ", 2)
        except ValueError as exc:
            raise GitCandidateError("candidate Git tree entry is malformed") from exc
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise GitCandidateError(
                f"candidate Git tree contains unsupported entry: {path}"
            )
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or "\x00" in path
            or any(part in {"", ".", "..", ".git"} for part in path.split("/"))
        ):
            raise GitCandidateError(f"candidate Git path is unsafe: {path}")
        entries.append((mode, object_id, path))
    if len(entries) > MAX_FILES:
        raise GitCandidateError(f"candidate Git tree exceeds {MAX_FILES} files")
    return entries


def content_sha256(repository: Path, commit: str) -> str:
    digest = hashlib.sha256(b"metering-git-candidate-content-v1\x00")
    total_bytes = 0
    for mode, object_id, path in _tree_entries(repository, commit):
        try:
            completed = subprocess.run(
                ["git", "cat-file", "blob", object_id],
                cwd=repository,
                capture_output=True,
                check=False,
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitCandidateError(f"cannot read candidate Git blob: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise GitCandidateError(detail or "cannot read candidate Git blob")
        content = completed.stdout
        total_bytes += len(content)
        if total_bytes > MAX_CONTENT_BYTES:
            raise GitCandidateError(
                f"candidate Git content exceeds {MAX_CONTENT_BYTES} bytes"
            )
        encoded_path = path.encode("utf-8")
        digest.update(mode.encode("ascii") + b"\x00")
        digest.update(str(len(encoded_path)).encode("ascii") + b":" + encoded_path)
        digest.update(str(len(content)).encode("ascii") + b":" + content)
    return digest.hexdigest()


def clone_commit(repository: str, commit: str, destination: Path) -> tuple[str, str]:
    allowed_repository = os.environ.get("METERING_GIT_REPOSITORY")
    if not allowed_repository or repository != allowed_repository:
        raise GitCandidateError(
            "artifact repository does not match METERING_GIT_REPOSITORY"
        )
    if destination.exists():
        raise GitCandidateError(f"clone destination already exists: {destination}")
    run_git(
        [
            "-c",
            "protocol.file.allow=always",
            "clone",
            "--quiet",
            "--no-checkout",
            "--no-local",
            repository,
            str(destination),
        ]
    )
    run_git(["checkout", "--quiet", "--detach", commit], cwd=destination)
    actual_commit = run_git(["rev-parse", "HEAD"], cwd=destination).strip()
    actual_tree = run_git(["rev-parse", "HEAD^{tree}"], cwd=destination).strip()
    if actual_commit != commit:
        raise GitCandidateError("checked-out commit does not match requested commit")
    return actual_commit, actual_tree


def clone_verified(artifact_value: object, destination: Path) -> dict[str, object]:
    try:
        artifact = decode_agent_artifact(artifact_value, "Git candidate artifact")
    except ProtocolError as exc:
        raise GitCandidateError(str(exc)) from exc
    if artifact["artifact_schema"] != GIT_ARTIFACT_SCHEMA:
        raise GitCandidateError("candidate artifact must use git-candidate-v1")
    repository = str(artifact["repository"])
    commit = str(artifact["commit"])
    _, actual_tree = clone_commit(repository, commit, destination)
    if actual_tree != artifact["git_tree"]:
        raise GitCandidateError("checked-out Git tree does not match artifact")
    if content_sha256(destination, commit) != artifact["content_sha256"]:
        raise GitCandidateError("checked-out content SHA-256 does not match artifact")
    entries = {path for _, _, path in _tree_entries(destination, commit)}
    if artifact["entrypoint"] not in entries:
        raise GitCandidateError("artifact entrypoint is not a regular Git file")
    return artifact


def copy_candidate_files(repository: Path, destination: Path) -> None:
    destination.mkdir()
    for mode, _, relative in _tree_entries(repository, "HEAD"):
        source = repository / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if mode == "100755" else 0o644)


def validate_workspace(workspace: Path) -> None:
    file_count = 0
    total_bytes = 0
    for path in workspace.rglob("*"):
        relative = path.relative_to(workspace)
        if ".git" in relative.parts or path.is_symlink():
            raise GitCandidateError(f"workspace contains forbidden entry: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise GitCandidateError(f"workspace contains unsupported entry: {relative}")
        file_count += 1
        total_bytes += path.stat().st_size
        if file_count > MAX_FILES or total_bytes > MAX_CONTENT_BYTES:
            raise GitCandidateError("workspace exceeds the Git candidate size limit")


def replace_worktree(repository: Path, source: Path) -> None:
    validate_workspace(source)
    for item in repository.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()
    for item in source.iterdir():
        target = repository / item.name
        if item.is_dir() and not item.is_symlink():
            shutil.copytree(item, target)
        elif item.is_file() and not item.is_symlink():
            shutil.copy2(item, target)
        else:
            raise GitCandidateError(f"workspace contains unsupported entry: {item}")


def changed_paths(repository: Path) -> list[str]:
    source = run_git(
        ["diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB", "-z"],
        cwd=repository,
    )
    return sorted(path for path in source.split("\x00") if path)
