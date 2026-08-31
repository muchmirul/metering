"""Deterministically recombine two verified git-candidate-v1 artifacts.

The caller supplies every conflicting path choice. This tool creates a two-parent
Git commit and publishes it, but it does not evaluate, retain, install, or deploy
the child. Path-level recombination is mechanical inheritance, not evidence that
the resulting program is valid or useful.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = ROOT / "apps"
HERE = Path(__file__).resolve().parent
for import_root in (APPS_ROOT, HERE):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from agent_protocol import (  # noqa: E402
    GIT_ARTIFACT_SCHEMA,
    ProtocolError,
    candidate_record,
    decode_agent_artifact,
    decode_candidate,
    require_exact_keys,
    require_nonempty_string,
)
from stdio_connector import canonical_digest, canonical_json, decode_json_object  # noqa: E402

from git_repository import (  # noqa: E402
    GitCandidateError,
    clone_verified,
    content_sha256,
    replace_worktree,
    run_git,
    validate_workspace,
)

SCHEMA_VERSION = 1


class RecombinationError(RuntimeError):
    """Raised when two Git candidates cannot be recombined exactly."""


def _normalized_path(value: object, location: str) -> str:
    path = require_nonempty_string(value, location)
    candidate = PurePosixPath(path)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != path
        or "\\" in path
        or any(part in {"", ".", "..", ".git"} for part in candidate.parts)
    ):
        raise RecombinationError(f"{location} must be a normalized relative POSIX path")
    return path


def _file_map(root: Path) -> dict[str, tuple[bytes, bool]]:
    result: dict[str, tuple[bytes, bool]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise RecombinationError(f"candidate contains unsupported entry: {relative}")
        normalized = relative.as_posix()
        result[normalized] = (
            path.read_bytes(),
            bool(path.stat().st_mode & stat.S_IXUSR),
        )
    if not result:
        raise RecombinationError("candidate tree must not be empty")
    return result


def _path_sources(value: object) -> dict[str, int]:
    if type(value) is not dict:
        raise RecombinationError("path_sources must be a JSON object")
    result: dict[str, int] = {}
    for raw_path, raw_source in value.items():
        path = _normalized_path(raw_path, f"path_sources.{raw_path}")
        if type(raw_source) is not int or raw_source not in {0, 1}:
            raise RecombinationError(
                f"path_sources.{path} must be parent index 0 or 1"
            )
        result[path] = raw_source
    return result


def _decode_request(source: str) -> tuple[
    list[dict[str, object]], int, dict[str, int], str, object
]:
    request = decode_json_object(source, RecombinationError)
    try:
        require_exact_keys(
            request,
            {
                "entrypoint",
                "generation",
                "outputs",
                "parents",
                "path_sources",
                "schema_version",
            },
            "request",
        )
        if type(request["schema_version"]) is not int or request["schema_version"] != 1:
            raise ProtocolError("schema_version must be 1")
        if type(request["parents"]) is not list or len(request["parents"]) != 2:
            raise ProtocolError("parents must contain exactly two candidates")
        parents = [
            decode_candidate(parent, f"parents[{index}]")
            for index, parent in enumerate(request["parents"])
        ]
        if parents[0]["candidate_id"] == parents[1]["candidate_id"]:
            raise ProtocolError("parents must be distinct candidates")
        generation = request["generation"]
        if type(generation) is not int or generation < 1:
            raise ProtocolError("generation must be a positive integer")
        entrypoint = _normalized_path(request["entrypoint"], "entrypoint")
    except ProtocolError as exc:
        raise RecombinationError(str(exc)) from exc
    artifacts = [cast(dict[str, object], parent["artifact"]) for parent in parents]
    for index, artifact in enumerate(artifacts):
        if artifact["artifact_schema"] != GIT_ARTIFACT_SCHEMA:
            raise RecombinationError(
                f"parents[{index}] must contain a git-candidate-v1 artifact"
            )
    if artifacts[0]["repository"] != artifacts[1]["repository"]:
        raise RecombinationError("Git parents must use the same repository")
    return (
        parents,
        generation,
        _path_sources(request["path_sources"]),
        entrypoint,
        request["outputs"],
    )


def _write_workspace(
    workspace: Path,
    parents: list[dict[str, object]],
    maps: list[dict[str, tuple[bytes, bool]]],
    requested_sources: dict[str, int],
) -> dict[str, str]:
    all_paths = sorted(set(maps[0]) | set(maps[1]))
    unknown = sorted(set(requested_sources) - set(all_paths))
    if unknown:
        raise RecombinationError(
            "path_sources contains paths absent from both parents: " + ", ".join(unknown)
        )
    workspace.mkdir()
    provenance: dict[str, str] = {}
    for path in all_paths:
        left = maps[0].get(path)
        right = maps[1].get(path)
        requested = requested_sources.get(path)
        if requested is not None:
            source_index = requested
            if maps[source_index].get(path) is None:
                raise RecombinationError(
                    f"path_sources selects parent {source_index} without path: {path}"
                )
        elif left is None:
            source_index = 1
        elif right is None or left == right:
            source_index = 0
        else:
            raise RecombinationError(
                f"path_sources must choose parent 0 or 1 for conflicting path: {path}"
            )
        content, executable = maps[source_index][path]
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(0o755 if executable else 0o644)
        provenance[path] = str(parents[source_index]["candidate_id"])
    validate_workspace(workspace)
    return provenance


def _commit_child(
    repository: Path,
    parents: list[dict[str, object]],
    workspace: Path,
    generation: int,
    entrypoint: str,
    outputs: object,
) -> dict[str, object]:
    artifacts = [cast(dict[str, object], parent["artifact"]) for parent in parents]
    commits = [str(artifact["commit"]) for artifact in artifacts]
    run_git(["fetch", "--quiet", "origin", commits[1]], cwd=repository)
    replace_worktree(repository, workspace)
    run_git(["add", "--all"], cwd=repository)
    tree = run_git(["write-tree"], cwd=repository).strip()
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_AUTHOR_EMAIL": "metering-evolution@example.invalid",
        "GIT_AUTHOR_NAME": "Metering Evolution",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_EMAIL": "metering-evolution@example.invalid",
        "GIT_COMMITTER_NAME": "Metering Evolution",
    }
    message = (
        f"Recombine generation {generation}\n\n"
        f"parent-0 {parents[0]['candidate_id']}\n"
        f"parent-1 {parents[1]['candidate_id']}\n"
    )
    commit = run_git(
        ["commit-tree", tree, "-p", commits[0], "-p", commits[1]],
        cwd=repository,
        input_text=message,
        environment=environment,
    ).strip()
    artifact = {
        "artifact_schema": GIT_ARTIFACT_SCHEMA,
        "commit": commit,
        "content_sha256": content_sha256(repository, commit),
        "entrypoint": entrypoint,
        "git_tree": tree,
        "outputs": outputs,
        "repository": artifacts[0]["repository"],
    }
    try:
        normalized = decode_agent_artifact(artifact, "child artifact")
    except ProtocolError as exc:
        raise RecombinationError(str(exc)) from exc
    ref_prefix = os.environ.get("METERING_GIT_REF_PREFIX")
    if not ref_prefix:
        raise RecombinationError("METERING_GIT_REF_PREFIX must name a branch prefix")
    published_ref = (
        f"{ref_prefix.rstrip('/')}/recombination-{generation:06d}-{commit[:12]}"
    )
    run_git(["check-ref-format", published_ref], cwd=repository)
    run_git(["push", "--quiet", "origin", f"{commit}:{published_ref}"], cwd=repository)
    return {"artifact": normalized, "published_ref": published_ref}


def recombine(source: str) -> dict[str, object]:
    parents, generation, requested_sources, entrypoint, outputs = _decode_request(source)
    with tempfile.TemporaryDirectory(prefix="metering-git-recombine-") as temporary:
        root = Path(temporary)
        checkouts = [root / "parent-0", root / "parent-1"]
        for parent, checkout in zip(parents, checkouts):
            clone_verified(cast(dict[str, object], parent["artifact"]), checkout)
        maps = [_file_map(checkout) for checkout in checkouts]
        workspace = root / "workspace"
        provenance = _write_workspace(
            workspace, parents, maps, requested_sources
        )
        if entrypoint not in provenance:
            raise RecombinationError("entrypoint is absent from the recombined tree")
        committed = _commit_child(
            checkouts[0], parents, workspace, generation, entrypoint, outputs
        )
    child = candidate_record(committed["artifact"], "child artifact")
    record = {
        "child_candidate_id": child["candidate_id"],
        "generation": generation,
        "parent_candidate_ids": [
            parents[0]["candidate_id"],
            parents[1]["candidate_id"],
        ],
        "path_provenance": provenance,
        "recombination_schema": "git-path-recombination-v1",
    }
    return {
        "child": child,
        "published_ref": committed["published_ref"],
        "recombination": {
            **record,
            "recombination_id": canonical_digest(record),
        },
        "schema_version": SCHEMA_VERSION,
    }


def main() -> int:
    try:
        response = recombine(sys.stdin.read())
    except (
        GitCandidateError,
        RecombinationError,
        ProtocolError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
