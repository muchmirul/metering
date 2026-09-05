"""Solution experiment document and immutable Git-artifact operations."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import cast

from apps._support.durable import atomic_write
from apps._support.wire import canonical_json, decode_json_object
from apps.agent_protocol import GIT_ARTIFACT_SCHEMA, decode_agent_artifact
from apps.coding_agent.experiment_config import SolutionExperimentError
from apps.coding_agent.harness_workspace_editor import (
    load_harness_descriptor,
    materialize_selected_harness,
)
from apps.coding_agent.protocol import load_final_profile, task_documents
from apps.harness.experiment_config import ExperimentError as HarnessExperimentError
from apps.harness.experiment_replay import (
    verify_experiment as verify_harness_experiment,
)
from apps.harness.runtime_manifest import RuntimeManifest, assert_candidate_compatible
from apps.harness.workspace import snapshot_directory
from artifacts.git.git_repository import clone_verified, content_sha256, run_git


def copy_canonical(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    document = decode_json_object(data.decode("utf-8"), SolutionExperimentError)
    if data.decode("utf-8") != canonical_json(document) + "\n":
        raise SolutionExperimentError(f"source document is not canonical: {source}")
    atomic_write(destination, data)


def load_protected_final_tasks(
    root: Path, profile: dict[str, object]
) -> list[dict[str, object]]:
    """Read only the run's existing final profile; never reveal or copy it."""
    if "final_checks" in profile:
        return task_documents(
            profile,
            "final",
            final_checks=cast(list[dict[str, object]], profile["final_checks"]),
        )
    destination = root / "protected-final.json"
    if not destination.exists():
        raise SolutionExperimentError("protected coding final profile is absent")
    _, checks = load_final_profile(profile, destination)
    return task_documents(profile, "final", final_checks=checks)


def copy_protected_final_tasks(
    root: Path, profile: dict[str, object]
) -> list[dict[str, object]]:
    """Reveal final checks at the runtime's existing post-development boundary."""
    destination = root / "protected-final.json"
    if "final_checks" in profile or destination.exists():
        return load_protected_final_tasks(root, profile)
    source, checks = load_final_profile(profile)
    atomic_write(destination, source)
    return task_documents(profile, "final", final_checks=checks)


def initialize_solution_repository(
    root: Path, profile: dict[str, object]
) -> tuple[Path, dict[str, object]]:
    repository = cast(dict[str, str], profile["repository"])
    source = Path(repository["path"])
    if source.is_symlink() or not source.is_dir():
        raise SolutionExperimentError("coding task repository is absent or unsafe")
    requested = repository["base_commit"]
    actual = run_git(["rev-parse", f"{requested}^{{commit}}"], cwd=source).strip()
    if requested != actual:
        raise SolutionExperimentError(
            "coding task base_commit must be one full immutable commit ID"
        )
    remote = root / "candidate.git"
    run_git(
        [
            "-c",
            "protocol.file.allow=always",
            "clone",
            "--bare",
            "--no-local",
            str(source),
            str(remote),
        ]
    )
    if run_git(["rev-parse", f"{actual}^{{commit}}"], cwd=remote).strip() != actual:
        raise SolutionExperimentError("copied repository changed its base commit")
    tree = run_git(["rev-parse", f"{actual}^{{tree}}"], cwd=remote).strip()
    artifact = decode_agent_artifact(
        {
            "artifact_schema": GIT_ARTIFACT_SCHEMA,
            "commit": actual,
            "content_sha256": content_sha256(remote, actual),
            "entrypoint": repository["entrypoint"],
            "git_tree": tree,
            "outputs": [],
            "repository": str(remote.absolute()),
        }
    )
    previous = os.environ.get("METERING_GIT_REPOSITORY")
    try:
        os.environ["METERING_GIT_REPOSITORY"] = str(remote.absolute())
        with tempfile.TemporaryDirectory(prefix="metering-coding-seed-") as temporary:
            checkout = Path(temporary) / "checkout"
            clone_verified(artifact, checkout)
            snapshot_directory(checkout)
    finally:
        if previous is None:
            os.environ.pop("METERING_GIT_REPOSITORY", None)
        else:
            os.environ["METERING_GIT_REPOSITORY"] = previous
    return remote, artifact


def localize_harness(
    root: Path, descriptor_source: Path, runtime: RuntimeManifest
) -> tuple[Path, dict[str, object], Path]:
    try:
        provenance = verify_harness_experiment(descriptor_source.parent)
    except (HarnessExperimentError, OSError, ValueError) as exc:
        raise SolutionExperimentError(
            f"selected harness provenance does not verify: {exc}"
        ) from exc
    if provenance.get("assay") != "coding-agent-v1":
        raise SolutionExperimentError(
            "selected harness must come from a sealed coding-harness assay"
        )
    canonical_descriptor = descriptor_source.parent / "selected-harness.json"
    if (
        descriptor_source.absolute() != canonical_descriptor.absolute()
        or descriptor_source.read_bytes() != canonical_descriptor.read_bytes()
    ):
        raise SolutionExperimentError(
            "selected harness descriptor is not the verified run descriptor"
        )
    descriptor = load_harness_descriptor(descriptor_source)
    harness_provenance = cast(dict[str, object], descriptor["provenance"])
    if (
        harness_provenance["final_passed_count"]
        != harness_provenance["final_task_count"]
        or harness_provenance["final_safety_failures"] != 0
    ):
        raise SolutionExperimentError(
            "selected harness did not pass its protected Level-2 assay"
        )
    if descriptor["runtime_id"] != runtime.runtime_id:
        raise SolutionExperimentError(
            "selected harness and requested runtime identities differ"
        )
    artifact = cast(dict[str, object], descriptor["artifact"])
    repository = artifact.get("repository")
    if type(repository) is not str:
        raise SolutionExperimentError("selected harness repository is malformed")
    remote = root / "harness.git"
    run_git(
        [
            "-c",
            "protocol.file.allow=always",
            "clone",
            "--bare",
            "--no-local",
            repository,
            str(remote),
        ]
    )
    descriptor_path = root / "selected-harness.json"
    descriptor_bytes = (canonical_json(descriptor) + "\n").encode("ascii")
    atomic_write(descriptor_path, descriptor_bytes)
    provenance_receipt = {
        "descriptor_sha256": hashlib.sha256(descriptor_bytes).hexdigest(),
        "receipt_schema": "darwinian-coding-harness-provenance-v1",
        "source_root": str(descriptor_source.parent.absolute()),
        "verification": provenance,
    }
    atomic_write(
        root / "harness-provenance.json",
        (canonical_json(provenance_receipt) + "\n").encode("ascii"),
    )
    checkout = root / "harness-conformance"
    _, candidate = materialize_selected_harness(
        descriptor,
        checkout,
        repository_override=str(remote.absolute()),
    )
    assert_candidate_compatible(
        runtime, (checkout / candidate.paths["dependency_lock"]).read_bytes()
    )
    return descriptor_path, descriptor, checkout


def verify_harness_provenance(root: Path, descriptor: dict[str, object]) -> None:
    if descriptor["descriptor_schema"] == "selected-evolutionary-harness-v1":
        return
    receipt = canonical_document(
        root / "harness-provenance.json", "selected harness provenance receipt"
    )
    if (
        set(receipt)
        != {
            "descriptor_sha256",
            "receipt_schema",
            "source_root",
            "verification",
        }
        or receipt["receipt_schema"] != "darwinian-coding-harness-provenance-v1"
    ):
        raise SolutionExperimentError(
            "selected harness provenance receipt is malformed"
        )
    descriptor_bytes = (canonical_json(descriptor) + "\n").encode("ascii")
    source_root_value = receipt["source_root"]
    if type(source_root_value) is not str:
        raise SolutionExperimentError("selected harness provenance root is malformed")
    source_root = Path(source_root_value)
    if (
        not source_root.is_absolute()
        or source_root.is_symlink()
        or not source_root.is_dir()
        or receipt["descriptor_sha256"] != hashlib.sha256(descriptor_bytes).hexdigest()
        or (source_root / "selected-harness.json").read_bytes() != descriptor_bytes
    ):
        raise SolutionExperimentError("selected harness provenance changed identity")
    try:
        verification = verify_harness_experiment(source_root)
    except (HarnessExperimentError, OSError, ValueError) as exc:
        raise SolutionExperimentError(
            f"selected harness provenance does not verify: {exc}"
        ) from exc
    if (
        verification != receipt["verification"]
        or verification.get("assay") != "coding-agent-v1"
    ):
        raise SolutionExperimentError(
            "selected harness provenance receipt does not replay"
        )


def canonical_document(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise SolutionExperimentError(f"{label} is absent or unsafe")
    source = path.read_text(encoding="ascii")
    document = decode_json_object(source, SolutionExperimentError)
    if source != canonical_json(document) + "\n":
        raise SolutionExperimentError(f"{label} is not canonical")
    return document
