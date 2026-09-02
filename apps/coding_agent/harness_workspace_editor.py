"""Use one immutable evolved harness to edit a solution workspace in isolation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import cast

from apps._support.durable import atomic_write, reject_symlink
from apps._support.wire import canonical_digest, canonical_json, decode_json_object
from apps.agent_protocol import ProtocolError, require_exact_keys, require_sha256
from apps.harness.model_contract import SubprocessModelTransport
from apps.harness.protocol import load_candidate
from apps.harness.runtime import HarnessRuntime
from apps.harness.runtime_manifest import (
    assert_candidate_compatible,
    load_runtime_manifest,
)
from apps.harness.workspace import (
    MAX_WORKSPACE_BYTES,
    MAX_WORKSPACE_FILES,
    WorkspaceError,
    changed_paths,
    files_digest,
    materialize_files,
    normalized_path,
    require_allowed_changes,
    snapshot_directory,
)
from artifacts.git.git_repository import clone_verified

RECEIPT_SCHEMA = "darwinian-coding-mutation-receipt-v2"


class CodingMutationError(RuntimeError):
    """Raised when a selected harness cannot produce one safe solution edit."""


def load_harness_descriptor(
    path: Path, *, allow_legacy: bool = False
) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_097_152:
        raise CodingMutationError(
            "selected harness descriptor must be a bounded regular file"
        )
    try:
        source = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise CodingMutationError(
            f"cannot read selected harness descriptor: {exc}"
        ) from exc
    document = decode_json_object(source, CodingMutationError)
    if source != canonical_json(document) + "\n":
        raise CodingMutationError("selected harness descriptor is not canonical")
    common_keys = {
        "artifact",
        "candidate_id",
        "descriptor_schema",
        "manifest_id",
        "runtime_id",
    }
    schema = document.get("descriptor_schema")
    if schema == "selected-evolutionary-harness-v1" and allow_legacy:
        expected_keys = common_keys
    elif schema == "selected-evolutionary-harness-v2":
        expected_keys = {*common_keys, "provenance"}
    else:
        raise CodingMutationError("selected harness descriptor schema is unsupported")
    try:
        require_exact_keys(
            document,
            expected_keys,
            "selected harness descriptor",
        )
        candidate_id = require_sha256(
            document["candidate_id"], "selected harness descriptor.candidate_id"
        )
        manifest_id = require_sha256(
            document["manifest_id"], "selected harness descriptor.manifest_id"
        )
        runtime_id = require_sha256(
            document["runtime_id"], "selected harness descriptor.runtime_id"
        )
    except ProtocolError as exc:
        raise CodingMutationError(str(exc)) from exc
    if schema == "selected-evolutionary-harness-v2":
        provenance = document["provenance"]
        if type(provenance) is not dict:
            raise CodingMutationError("selected harness provenance must be an object")
        try:
            require_exact_keys(
                provenance,
                {
                    "assay_id",
                    "development_experiment_id",
                    "final_allocation_record_id",
                    "final_passed_count",
                    "final_receipt_sha256",
                    "final_run_record_id",
                    "final_safety_failures",
                    "final_task_count",
                    "population_head_record_id",
                },
                "selected harness provenance",
            )
            digest_names = (
                "assay_id",
                "development_experiment_id",
                "final_allocation_record_id",
                "final_receipt_sha256",
                "final_run_record_id",
                "population_head_record_id",
            )
            normalized_provenance: dict[str, object] = {
                name: require_sha256(
                    provenance[name], f"selected harness provenance.{name}"
                )
                for name in digest_names
            }
            for name in (
                "final_passed_count",
                "final_safety_failures",
                "final_task_count",
            ):
                value = provenance[name]
                if type(value) is not int or value < 0:
                    raise CodingMutationError(
                        f"selected harness provenance.{name} must be nonnegative"
                    )
                normalized_provenance[name] = value
            if (
                normalized_provenance["final_task_count"] < 1
                or normalized_provenance["final_passed_count"]
                > normalized_provenance["final_task_count"]
                or normalized_provenance["final_safety_failures"]
                > normalized_provenance["final_task_count"]
            ):
                raise CodingMutationError("selected harness final counts are malformed")
        except ProtocolError as exc:
            raise CodingMutationError(str(exc)) from exc
        if provenance != normalized_provenance:
            raise CodingMutationError("selected harness provenance is not normalized")
    return {
        **document,
        "candidate_id": candidate_id,
        "manifest_id": manifest_id,
        "runtime_id": runtime_id,
    }


def _allowed_paths() -> list[str]:
    source = os.environ.get("METERING_GIT_ALLOWED_PATHS_JSON")
    if not source:
        raise CodingMutationError(
            "METERING_GIT_ALLOWED_PATHS_JSON must contain approved solution paths"
        )
    try:
        value = json.loads(source)
    except json.JSONDecodeError as exc:
        raise CodingMutationError(
            f"METERING_GIT_ALLOWED_PATHS_JSON is invalid JSON: {exc}"
        ) from exc
    if type(value) is not list or not value:
        raise CodingMutationError(
            "METERING_GIT_ALLOWED_PATHS_JSON must be a non-empty array"
        )
    paths: list[str] = []
    for index, raw in enumerate(value):
        try:
            path = normalized_path(raw, f"allowed solution paths[{index}]")
        except WorkspaceError as exc:
            raise CodingMutationError(str(exc)) from exc
        if path in paths:
            raise CodingMutationError("allowed solution paths contain a duplicate")
        paths.append(path)
    if paths != sorted(paths):
        raise CodingMutationError("allowed solution paths must be sorted")
    return paths


def materialize_selected_harness(
    descriptor: dict[str, object],
    destination: Path,
    *,
    repository_override: str | None = None,
) -> tuple[dict[str, object], object]:
    artifact = descriptor["artifact"]
    if type(artifact) is not dict:
        raise CodingMutationError("selected harness artifact is malformed")
    repository = artifact.get("repository")
    if type(repository) is not str:
        raise CodingMutationError("selected harness repository is malformed")
    clone_artifact = artifact
    if repository_override is not None:
        override = Path(repository_override)
        if not override.is_absolute():
            raise CodingMutationError(
                "selected harness repository override must be absolute"
            )
        clone_artifact = {**artifact, "repository": str(override)}
        repository = str(override)
    previous = os.environ.get("METERING_GIT_REPOSITORY")
    try:
        os.environ["METERING_GIT_REPOSITORY"] = repository
        verified = clone_verified(clone_artifact, destination)
    finally:
        if previous is None:
            os.environ.pop("METERING_GIT_REPOSITORY", None)
        else:
            os.environ["METERING_GIT_REPOSITORY"] = previous
    candidate = load_candidate(destination, entrypoint=str(verified["entrypoint"]))
    if candidate.manifest_id != descriptor["manifest_id"]:
        raise CodingMutationError("selected harness manifest identity changed")
    return verified, candidate


def _write_receipt(root: Path, document: dict[str, object]) -> dict[str, str]:
    root = root.expanduser().absolute()
    reject_symlink(root, "coding mutation receipt directory", CodingMutationError)
    root.mkdir(parents=True, exist_ok=True)
    source = (canonical_json(document) + "\n").encode("ascii")
    digest = hashlib.sha256(source).hexdigest()
    path = root / f"{digest}.json"
    reject_symlink(path, "coding mutation receipt", CodingMutationError)
    if path.exists():
        if path.read_bytes() != source:
            raise CodingMutationError("coding mutation receipt identity conflicts")
    else:
        atomic_write(path, source)
    return {"sha256": digest, "uri": path.as_uri()}


def edit_solution_with_harness(
    workspace: Path,
    objective: str,
    *,
    model_command: list[str],
    expected_connector: str,
) -> dict[str, object]:
    runtime_path = os.environ.get("METERING_HARNESS_RUNTIME_MANIFEST")
    descriptor_path = os.environ.get("METERING_CODING_HARNESS_DESCRIPTOR")
    receipt_path = os.environ.get("METERING_CODING_MUTATION_RECEIPT_DIR")
    harness_repository = os.environ.get("METERING_CODING_HARNESS_REPOSITORY")
    coding_runtime_id = os.environ.get("METERING_CODING_RUNTIME_ID")
    if (
        not runtime_path
        or not descriptor_path
        or not receipt_path
        or not harness_repository
        or not coding_runtime_id
    ):
        raise CodingMutationError(
            "runtime, coding runtime, selected harness, harness repository, and coding mutation receipt directories must be configured"
        )
    runtime = load_runtime_manifest(Path(runtime_path))
    if runtime.model["connector"] != expected_connector:
        raise CodingMutationError(
            f"runtime model connector must be {expected_connector}"
        )
    descriptor = load_harness_descriptor(Path(descriptor_path))
    if descriptor["runtime_id"] != runtime.runtime_id:
        raise CodingMutationError(
            "selected harness was evaluated under another runtime identity"
        )
    allowed = _allowed_paths()
    before = snapshot_directory(workspace)
    policy = {
        "allowed_write_paths": allowed,
        "command_timeout_ms": min(runtime.limits.wall_milliseconds, 300_000),
        "max_bytes": MAX_WORKSPACE_BYTES,
        "max_files": MAX_WORKSPACE_FILES,
        "max_output_characters": 65_536,
    }
    model = SubprocessModelTransport(
        model_command,
        timeout_seconds=runtime.model_timeout_seconds,
        max_response_bytes=runtime.max_output_bytes,
        environment={
            "METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES": str(runtime.max_output_bytes),
            "METERING_HARNESS_MODEL_TIMEOUT": str(runtime.model_timeout_seconds),
        },
    )
    with tempfile.TemporaryDirectory(
        prefix="metering-coding-selected-harness-"
    ) as temporary:
        harness_root = Path(temporary) / "harness"
        _, candidate = materialize_selected_harness(
            descriptor,
            harness_root,
            repository_override=harness_repository,
        )
        assert_candidate_compatible(
            runtime,
            (harness_root / candidate.paths["dependency_lock"]).read_bytes(),
        )
        prompt = (
            "Solve this coding task in the disposable repository. Inspect relevant files, "
            "make the smallest correct change within the declared write paths, run useful "
            "repository checks, and finish only after reviewing their output. If the parent "
            "already satisfies the task, preserve its behavior but make one small useful "
            "readability, typing, or documentation improvement so the child remains a real "
            "immutable variant. A separate "
            "evaluator decides whether the immutable child survives.\n\n" + objective
        )
        completion = HarnessRuntime(
            candidate,
            runtime,
            model,
            allow_fixture=(
                runtime.kind == "process-fixture-v1"
                and os.environ.get("METERING_HARNESS_ALLOW_UNSAFE_FIXTURE") == "1"
            ),
        ).run(
            canonical_digest(
                {
                    "base_workspace": files_digest(before),
                    "coding_task": prompt,
                    "harness_candidate_id": descriptor["candidate_id"],
                }
            ),
            {
                "outcomes": ["fail", "pass"],
                "prompt": prompt,
                "workspace": {"files": before, "policy": policy},
            },
        )
    if completion.workspace is None:
        raise CodingMutationError("selected harness did not return a coding workspace")
    after = cast(list[dict[str, object]], completion.workspace["files"])
    paths = changed_paths(before, after)
    if not paths:
        raise CodingMutationError("selected harness did not change the solution")
    try:
        require_allowed_changes(paths, allowed)
    except WorkspaceError as exc:
        raise CodingMutationError(str(exc)) from exc
    materialize_files(after, workspace)
    receipt = {
        "base_files_sha256": files_digest(before),
        "changed_paths": paths,
        "coding_runtime_id": coding_runtime_id,
        "completion": {
            "actions": completion.actions,
            "input_tokens": completion.input_tokens,
            "model_calls": completion.model_calls,
            "output_tokens": completion.output_tokens,
            "population_cost": completion.population_cost,
            "transcript_sha256": completion.transcript_digest,
        },
        "goal_sha256": canonical_digest({"objective": objective}),
        "harness_candidate_id": descriptor["candidate_id"],
        "harness_manifest_id": descriptor["manifest_id"],
        "receipt_schema": RECEIPT_SCHEMA,
        "result_files_sha256": files_digest(after),
        "runtime_id": runtime.runtime_id,
    }
    reference = _write_receipt(Path(receipt_path), receipt)
    return {"receipt": reference, "workspace_sha256": files_digest(after)}


__all__ = [
    "CodingMutationError",
    "edit_solution_with_harness",
    "load_harness_descriptor",
    "materialize_selected_harness",
]
