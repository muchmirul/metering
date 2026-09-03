#!/usr/bin/env python3
"""Run and offline-verify Darwinian evolution of repository solution commits."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.durable import atomic_write  # noqa: E402
from apps._support.wire import (  # noqa: E402
    canonical_digest,
    canonical_json,
    decode_json_object,
    write_document,
)
from apps.agent_protocol import GIT_ARTIFACT_SCHEMA, decode_agent_artifact  # noqa: E402
from apps.coding_agent.candidate_runner import RECEIPT_SCHEMA  # noqa: E402
from apps.coding_agent.solution_evaluator import (  # noqa: E402
    validate_evaluation_receipt,
)
from apps.coding_agent.final_assay import (  # noqa: E402
    BUNDLE_SCHEMA,
    CodingFinalError,
    run_final_assay,
)
from apps.coding_agent.harness_workspace_editor import (  # noqa: E402
    CodingMutationError,
    load_harness_descriptor,
    materialize_selected_harness,
)
from apps.coding_agent.process_tracker import (  # noqa: E402
    ProcessTrackerError,
    advance_process_status,
    load_process_status,
    process_document,
)
from apps.coding_agent.protocol import (  # noqa: E402
    CodingTaskError,
    load_final_profile,
    load_task_profile,
    task_documents,
)
from apps.harness.conformance import run_conformance  # noqa: E402
from apps.harness.experiment import (  # noqa: E402
    ExperimentError as HarnessExperimentError,
    verify_experiment as verify_harness_experiment,
)
from apps.harness.protocol import HarnessProtocolError, load_candidate  # noqa: E402
from apps.harness.runtime_manifest import (  # noqa: E402
    RuntimeManifest,
    RuntimeManifestError,
    assert_candidate_compatible,
    load_runtime_manifest,
)
from apps.harness.workspace import (  # noqa: E402
    WorkspaceError,
    changed_paths,
    files_digest,
    require_allowed_changes,
    snapshot_directory,
)
from apps.population.contract import RESOURCE_NAMES, PopulationState, load_state  # noqa: E402
from apps.population_driver.paths import population_root  # noqa: E402
from apps.population_driver.population_driver_protocol import (  # noqa: E402
    PopulationDriverError,
)
from apps.population_driver.runtime import (  # noqa: E402
    retry_population_driver,
    run_population_driver,
    verify_population_driver,
)
from artifacts.git.git_repository import (  # noqa: E402
    GitCandidateError,
    clone_verified,
    content_sha256,
    run_git,
)

GIT_ADAPTER = ROOT / "artifacts" / "git" / "git_candidate_adapter.py"
RUNNER = ROOT / "apps" / "coding_agent" / "candidate_runner.py"
EVALUATOR = ROOT / "apps" / "coding_agent" / "solution_evaluator.py"
EVIDENCE = ROOT / "apps" / "coding_agent" / "evidence_adapter.py"
VALIDATE = ROOT / "apps" / "coding_agent" / "validate_solution.py"
FIXTURE_PROPOSER = (
    ROOT / "apps" / "coding_agent" / "fixtures" / "fixture_solution_proposer.py"
)
PI_PROPOSER = ROOT / "connectors" / "fixed" / "pi" / "coding_proposer.py"


class SolutionExperimentError(RuntimeError):
    """Raised when a coding experiment cannot complete or replay safely."""


def _budget(value: int = 10**15) -> dict[str, int]:
    return {name: value for name in RESOURCE_NAMES}


def _task_runner_timeout(tasks: list[dict[str, object]]) -> int:
    maximum_ms = max(
        int(
            cast(dict[str, object], cast(dict[str, object], task["input"])["assay"])[
                "timeout_ms"
            ]
        )
        for task in tasks
    )
    return max(600, (maximum_ms + 999) // 1_000 + 120)


def _copy_canonical(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    document = decode_json_object(data.decode("utf-8"), SolutionExperimentError)
    if data.decode("utf-8") != canonical_json(document) + "\n":
        raise SolutionExperimentError(f"source document is not canonical: {source}")
    atomic_write(destination, data)


def _protected_final_tasks(
    root: Path,
    profile: dict[str, object],
    *,
    copy_if_absent: bool,
) -> list[dict[str, object]]:
    if "final_checks" in profile:
        return task_documents(
            profile,
            "final",
            final_checks=cast(list[dict[str, object]], profile["final_checks"]),
        )
    destination = root / "protected-final.json"
    if not destination.exists():
        if not copy_if_absent:
            raise SolutionExperimentError("protected coding final profile is absent")
        source, checks = load_final_profile(profile)
        atomic_write(destination, source)
    else:
        _, checks = load_final_profile(profile, destination)
    return task_documents(profile, "final", final_checks=checks)


def _initialize_solution_repository(
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


def _localize_harness(
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


def _verify_harness_provenance(root: Path, descriptor: dict[str, object]) -> None:
    if descriptor["descriptor_schema"] == "selected-evolutionary-harness-v1":
        return
    receipt = _canonical_document(
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


def _coding_runtime_id(
    profile: dict[str, object],
    runtime: RuntimeManifest,
    descriptor: dict[str, object],
) -> str:
    identity = {
        "coding_runtime_schema": "darwinian-coding-runtime-v1",
        "harness_candidate_id": descriptor["candidate_id"],
        "harness_manifest_id": descriptor["manifest_id"],
        "harness_runtime_id": runtime.runtime_id,
        "task_id": profile["task_id"],
    }
    if "provenance" in descriptor:
        identity["harness_provenance"] = descriptor["provenance"]
    return canonical_digest(identity)


def _request(
    profile: dict[str, object],
    artifact: dict[str, object],
    *,
    proposer: Path,
    coding_runtime_id: str,
) -> dict[str, object]:
    limits = cast(dict[str, int], profile["limits"])
    development = task_documents(profile, "development")
    runner_timeout = _task_runner_timeout(development)
    return {
        "allocation_draws": profile["allocation_draws"],
        "evidence_adapter": {
            "command": [sys.executable, str(EVIDENCE)],
            "timeout_seconds": 300,
        },
        "generation": {
            "evaluation": "darwinian-coding/development-v1",
            "evaluator": {
                "command": [sys.executable, str(EVALUATOR)],
                "timeout_seconds": 300,
            },
            "runner": {
                "command": [sys.executable, str(GIT_ADAPTER)],
                "timeout_seconds": runner_timeout,
            },
            "selection_policy": {
                "minimum_pass_improvement": 1,
                "reject_safety_regression": True,
                "type": "task-pass-count-v1",
            },
            "tasks": development,
        },
        "initial_parent_artifact": artifact,
        "limits": {
            "max_proposal_calls": limits["max_proposal_calls"],
            "max_rounds": limits["max_rounds"],
            "max_total_candidate_cost": _budget(10**15),
            "max_wall_seconds": limits["max_wall_seconds"],
        },
        "population": {
            "configuration": {
                "archive_policy": {
                    "capacity": 8,
                    "reliability_kappa": 0,
                    "type": "pareto-uniform-v1",
                },
                "name": "darwinian-coding-solutions",
            },
            "development": {
                "behavior_space": ["fail", "pass"],
                "budget": _budget(10**12),
                "runtime_id": coding_runtime_id,
            },
        },
        "proposal": {
            "command": [sys.executable, str(proposer)],
            "context": {
                "candidate_contract": "solution-commit-v1",
                "development_checks": profile["development_checks"],
                "goal": profile["goal"],
                "task_id": profile["task_id"],
            },
            "timeout_seconds": 1800,
        },
        "schema_version": 1,
    }


@contextmanager
def _environment(
    *,
    agent: str,
    runtime_path: Path,
    runtime: RuntimeManifest,
    solution_remote: Path,
    harness_descriptor: Path,
    harness_repository: Path,
    coding_runtime_id: str,
    root: Path,
    allowed_paths: list[str],
    entrypoint: str,
) -> Iterator[None]:
    changes = {
        "METERING_CODING_ENTRYPOINT": entrypoint,
        "METERING_CODING_EVALUATION_RECEIPT_DIR": str(root / "evaluation-receipts"),
        "METERING_CODING_HARNESS_DESCRIPTOR": str(harness_descriptor),
        "METERING_CODING_HARNESS_REPOSITORY": str(harness_repository.absolute()),
        "METERING_CODING_MUTATION_RECEIPT_DIR": str(root / "mutation-receipts"),
        "METERING_CODING_RUNTIME_ID": coding_runtime_id,
        "METERING_GIT_ALLOWED_PATHS_JSON": canonical_json(allowed_paths),
        "METERING_GIT_EXECUTOR_COMMAND": canonical_json([sys.executable, str(RUNNER)]),
        "METERING_GIT_EXECUTOR_TIMEOUT": "600",
        "METERING_GIT_REF_PREFIX": "refs/heads/evolution/solution",
        "METERING_GIT_REPOSITORY": str(solution_remote.absolute()),
        "METERING_GIT_VALIDATE_COMMAND": canonical_json(
            [sys.executable, str(VALIDATE)]
        ),
        "METERING_GIT_VALIDATE_TIMEOUT": "60",
        "METERING_HARNESS_ALLOW_UNSAFE_FIXTURE": "1" if agent == "fixture" else None,
        "METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES": str(runtime.max_output_bytes),
        "METERING_HARNESS_MODEL": runtime.model["model"],
        "METERING_HARNESS_MODEL_TIMEOUT": str(runtime.model_timeout_seconds),
        "METERING_HARNESS_PROVIDER": runtime.model["provider"],
        "METERING_HARNESS_REASONING": runtime.model["reasoning"],
        "METERING_HARNESS_RUNTIME_MANIFEST": str(runtime_path),
    }
    previous = {name: os.environ.get(name) for name in changes}
    try:
        for name, value in changes.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _selected_solution(
    root: Path,
    state: PopulationState,
    final: dict[str, object],
    profile: dict[str, object],
) -> dict[str, object]:
    candidate_id = str(final["candidate_id"])
    artifact = cast(dict[str, object], state.candidates[candidate_id]["artifact"])
    base = cast(dict[str, str], profile["repository"])["base_commit"]
    patch = run_git(
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--binary",
            base,
            str(artifact["commit"]),
        ],
        cwd=root / "candidate.git",
    )
    patch_path = root / "selected.patch"
    atomic_write(patch_path, patch.encode("utf-8"))
    descriptor = {
        "artifact": artifact,
        "base_commit": base,
        "candidate_id": candidate_id,
        "descriptor_schema": "selected-solution-commit-v1",
        "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        "task_id": profile["task_id"],
    }
    atomic_write(
        root / "selected-solution.json",
        (canonical_json(descriptor) + "\n").encode("ascii"),
    )
    return descriptor


def _experiment_report(
    root: Path,
    *,
    agent: str,
    profile: dict[str, object],
    runtime: RuntimeManifest,
    descriptor: dict[str, object],
    coding_runtime_id: str,
    development: dict[str, object],
    final: dict[str, object],
    verified_driver: dict[str, object],
) -> dict[str, object]:
    state = load_state(population_root(root / "state"))
    selected = _selected_solution(root, state, final, profile)
    report = {
        "agent": agent,
        "coding_runtime_id": coding_runtime_id,
        "development": development,
        "final": final,
        "harness_candidate_id": descriptor["candidate_id"],
        "runtime_id": runtime.runtime_id,
        "schema": "darwinian-coding-experiment-v1",
        "selected_solution": selected,
        "task_id": profile["task_id"],
        "verified": verified_driver,
    }
    atomic_write(
        root / "experiment-report.json",
        (canonical_json(report) + "\n").encode("ascii"),
    )
    advance_process_status(root, stage=6, run_kind="solution")
    return report


def run_experiment(
    agent: str,
    profile_source: Path,
    root: Path,
    runtime_source: Path,
    harness_source: Path,
) -> dict[str, object]:
    if agent not in {"fixture", "pi"}:
        raise SolutionExperimentError("agent must be fixture or pi")
    root = root.expanduser().absolute()
    if root.exists():
        raise SolutionExperimentError(f"experiment root must not exist: {root}")
    profile = load_task_profile(profile_source)
    runtime = load_runtime_manifest(runtime_source)
    expected_connector = "fixture-v1" if agent == "fixture" else "pi-v1"
    if runtime.model["connector"] != expected_connector:
        raise SolutionExperimentError("runtime connector does not match selected agent")
    root.mkdir(parents=True)
    advance_process_status(root, stage=4, run_kind="solution")
    profile_path = root / "task.json"
    runtime_path = root / "runtime.json"
    _copy_canonical(profile_source, profile_path)
    _copy_canonical(runtime_source, runtime_path)
    runtime = load_runtime_manifest(runtime_path)
    solution_remote, artifact = _initialize_solution_repository(root, profile)
    descriptor_path, descriptor, harness_checkout = _localize_harness(
        root, harness_source, runtime
    )
    coding_runtime_id = _coding_runtime_id(profile, runtime, descriptor)
    conformance = run_conformance(
        runtime_path, harness_checkout, allow_fixture=agent == "fixture"
    )
    atomic_write(
        root / "conformance.json",
        (canonical_json(conformance) + "\n").encode("ascii"),
    )
    proposer = FIXTURE_PROPOSER if agent == "fixture" else PI_PROPOSER
    request = _request(
        profile, artifact, proposer=proposer, coding_runtime_id=coding_runtime_id
    )
    state_root = root / "state"
    allowed = cast(list[str], profile["allowed_paths"])
    repository = cast(dict[str, str], profile["repository"])
    with _environment(
        agent=agent,
        runtime_path=runtime_path,
        runtime=runtime,
        solution_remote=solution_remote,
        harness_descriptor=descriptor_path,
        harness_repository=root / "harness.git",
        coding_runtime_id=coding_runtime_id,
        root=root,
        allowed_paths=allowed,
        entrypoint=repository["entrypoint"],
    ):
        development = run_population_driver(canonical_json(request), state_root)
        if development["status"] == "pending_round":
            pending = _canonical_document(
                state_root / "pending" / "round-intent.json", "coding round intent"
            )
            raise SolutionExperimentError(
                "coding development has a pending model intent; explicit retry required "
                f"for intent {pending['intent_id']}"
            )
        advance_process_status(root, stage=5, run_kind="solution")
        final_tasks = _protected_final_tasks(root, profile, copy_if_absent=True)
        final = run_final_assay(
            population_root(state_root),
            development_experiment_id=str(development["experiment_id"]),
            tasks=final_tasks,
            final_draw=cast(dict[str, int], profile["final_draw"]),
            runner_command=[sys.executable, str(GIT_ADAPTER)],
            evaluator_command=[sys.executable, str(EVALUATOR)],
            runner_timeout=_task_runner_timeout(final_tasks),
            evaluator_timeout=300,
            runtime_id=coding_runtime_id,
            bundle_root=root / "final-receipts",
            budget=_budget(),
        )
        verified_driver = verify_population_driver(state_root)
    report = _experiment_report(
        root,
        agent=agent,
        profile=profile,
        runtime=runtime,
        descriptor=descriptor,
        coding_runtime_id=coding_runtime_id,
        development=development,
        final=final,
        verified_driver=verified_driver,
    )
    shutil.rmtree(harness_checkout)
    return report


def _completed_final(state: PopulationState, root: Path) -> dict[str, object] | None:
    runs = [
        item
        for item in state.runs
        if state.experiments[
            str(cast(dict[str, object], item["run"])["experiment_id"])
        ]["role"]
        == "final"
    ]
    if not runs:
        return None
    if len(runs) != 1:
        raise SolutionExperimentError("coding experiment has multiple final runs")
    run = cast(dict[str, object], runs[0]["run"])
    evidence = cast(dict[str, object], runs[0]["evidence"])
    task = cast(dict[str, object], evidence["task"])
    reference = cast(dict[str, object], evidence["evidence_receipt"])
    allocation = cast(dict[str, object], run["seed"])["allocation_record_id"]
    return {
        "allocation_record_id": allocation,
        "candidate_id": run["candidate_id"],
        "experiment_id": run["experiment_id"],
        "passed_count": task["passed_count"],
        "receipt": reference,
        "run_record_id": runs[0]["record_id"],
        "safety_failures": task["safety_failures"],
        "selection_policy": "development-task-rate-reliability-v1",
        "task_count": task["case_count"],
    }


def _record_solution_retry_effects(root: Path, pending: dict[str, object]) -> str:
    attempts = pending.get("attempts")
    if type(attempts) is not list or not attempts or type(attempts[-1]) is not dict:
        raise SolutionExperimentError("coding pending attempts are malformed")
    attempt_id = cast(dict[str, object], attempts[-1]).get("attempt_id")
    intent_id = pending.get("intent_id")
    if type(attempt_id) is not str or type(intent_id) is not str:
        raise SolutionExperimentError("coding pending attempt identity is malformed")

    def digests(directory: str) -> list[str]:
        return sorted(
            path.stem
            for path in (root / directory).glob("*.json")
            if path.is_file() and not path.is_symlink()
        )

    document = {
        "attempt_id": attempt_id,
        "evaluation_receipt_sha256": digests("evaluation-receipts"),
        "intent_id": intent_id,
        "mutation_receipt_sha256": digests("mutation-receipts"),
        "retry_effects_schema": "darwinian-coding-retry-effects-v2",
    }
    destination = root / "state" / "retry-effects" / f"{attempt_id}.json"
    source = (canonical_json(document) + "\n").encode("ascii")
    if destination.exists():
        if destination.is_symlink() or destination.read_bytes() != source:
            raise SolutionExperimentError("coding retry-effects receipt conflicts")
    else:
        atomic_write(destination, source)
    return hashlib.sha256(source).hexdigest()


def continue_experiment(
    root: Path, *, retry_reason: str | None = None
) -> dict[str, object]:
    root = root.expanduser().absolute()
    if not root.is_dir():
        raise SolutionExperimentError(f"experiment root is absent: {root}")
    report_path = root / "experiment-report.json"
    if report_path.exists():
        if retry_reason is not None:
            raise SolutionExperimentError(
                "completed coding experiment cannot be retried"
            )
        report = _canonical_document(report_path, "coding experiment report")
        verify_experiment(root)
        advance_process_status(root, stage=6, run_kind="solution")
        return report
    profile = load_task_profile(root / "task.json", allow_legacy_inline_final=True)
    runtime = load_runtime_manifest(root / "runtime.json")
    descriptor = load_harness_descriptor(
        root / "selected-harness.json", allow_legacy=True
    )
    _verify_harness_provenance(root, descriptor)
    coding_runtime_id = _coding_runtime_id(profile, runtime, descriptor)
    connector = str(runtime.model["connector"])
    if connector not in {"fixture-v1", "pi-v1"}:
        raise SolutionExperimentError("coding runtime connector is unsupported")
    agent = "fixture" if connector == "fixture-v1" else "pi"
    advance_process_status(root, stage=4, run_kind="solution")
    state_root = root / "state"
    population_state = load_state(population_root(state_root))
    seeds = [
        candidate_id
        for candidate_id, parents in population_state.candidate_parents.items()
        if not parents
    ]
    if len(seeds) != 1:
        raise SolutionExperimentError("coding Population has no unique seed")
    artifact = cast(
        dict[str, object], population_state.candidates[seeds[0]]["artifact"]
    )
    proposer = FIXTURE_PROPOSER if agent == "fixture" else PI_PROPOSER
    request = _request(
        profile,
        artifact,
        proposer=proposer,
        coding_runtime_id=coding_runtime_id,
    )
    allowed = cast(list[str], profile["allowed_paths"])
    repository = cast(dict[str, str], profile["repository"])
    with _environment(
        agent=agent,
        runtime_path=root / "runtime.json",
        runtime=runtime,
        solution_remote=root / "candidate.git",
        harness_descriptor=root / "selected-harness.json",
        harness_repository=root / "harness.git",
        coding_runtime_id=coding_runtime_id,
        root=root,
        allowed_paths=allowed,
        entrypoint=repository["entrypoint"],
    ):
        if retry_reason is None:
            development = run_population_driver(canonical_json(request), state_root)
        else:
            if not retry_reason.strip() or "\x00" in retry_reason:
                raise SolutionExperimentError("retry reason must be non-empty text")
            pending = _canonical_document(
                state_root / "pending" / "round-intent.json", "coding round intent"
            )
            retry_effects_id = _record_solution_retry_effects(root, pending)
            development = retry_population_driver(
                canonical_json(
                    {
                        "intent_id": pending["intent_id"],
                        "reason": (
                            f"{retry_reason}\nretry-effects-sha256:{retry_effects_id}"
                        ),
                        "schema_version": 1,
                    }
                ),
                state_root,
            )
        if development["status"] == "pending_round":
            pending = _canonical_document(
                state_root / "pending" / "round-intent.json", "coding round intent"
            )
            raise SolutionExperimentError(
                "coding development remains pending; explicit retry required for "
                f"intent {pending['intent_id']}"
            )
        population_state = load_state(population_root(state_root))
        final = _completed_final(population_state, root)
        if final is None:
            if any(
                experiment["role"] == "final"
                for experiment in population_state.experiments.values()
            ):
                raise SolutionExperimentError(
                    "protected coding final evaluation started without a complete run; "
                    "it is sealed and cannot be retried"
                )
            advance_process_status(root, stage=5, run_kind="solution")
            final_tasks = _protected_final_tasks(root, profile, copy_if_absent=True)
            final = run_final_assay(
                population_root(state_root),
                development_experiment_id=str(development["experiment_id"]),
                tasks=final_tasks,
                final_draw=cast(dict[str, int], profile["final_draw"]),
                runner_command=[sys.executable, str(GIT_ADAPTER)],
                evaluator_command=[sys.executable, str(EVALUATOR)],
                runner_timeout=_task_runner_timeout(final_tasks),
                evaluator_timeout=300,
                runtime_id=coding_runtime_id,
                bundle_root=root / "final-receipts",
                budget=_budget(),
            )
        verified_driver = verify_population_driver(state_root)
    report = _experiment_report(
        root,
        agent=agent,
        profile=profile,
        runtime=runtime,
        descriptor=descriptor,
        coding_runtime_id=coding_runtime_id,
        development=development,
        final=final,
        verified_driver=verified_driver,
    )
    shutil.rmtree(root / "harness-conformance", ignore_errors=True)
    return report


# Offline verification is implemented below the run path so it cannot be used as
# recurrence authority.


def _canonical_document(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise SolutionExperimentError(f"{label} is absent or unsafe")
    source = path.read_text(encoding="ascii")
    document = decode_json_object(source, SolutionExperimentError)
    if source != canonical_json(document) + "\n":
        raise SolutionExperimentError(f"{label} is not canonical")
    return document


def _receipt_files(
    root: Path, schema: str, *, schema_key: str = "receipt_schema"
) -> dict[str, dict[str, object]]:
    if root.is_symlink() or not root.is_dir():
        raise SolutionExperimentError(f"receipt directory is absent or unsafe: {root}")
    receipts: dict[str, dict[str, object]] = {}
    for path in sorted(root.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise SolutionExperimentError("receipt directory contains an unsafe entry")
        source = path.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        if path.name != f"{digest}.json":
            raise SolutionExperimentError("receipt filename does not match content")
        document = decode_json_object(source.decode("ascii"), SolutionExperimentError)
        if source.decode("ascii") != canonical_json(document) + "\n":
            raise SolutionExperimentError("receipt is not canonical")
        if document.get(schema_key) != schema:
            raise SolutionExperimentError("receipt schema is unexpected")
        receipts[digest] = document
    return receipts


def _verify_bound_evaluation_receipt(
    receipt: dict[str, object],
    *,
    candidate_id: str,
    candidate_content_sha256: object,
    workspace_sha256: str,
    task: dict[str, object],
    runtime: RuntimeManifest,
) -> dict[str, object]:
    execution = validate_evaluation_receipt(
        receipt,
        candidate_id=candidate_id,
        task=task,
        runtime_id=runtime.runtime_id,
    )
    task_input = cast(dict[str, object], task["input"])
    observations = receipt["kernel_observations"]
    if (
        receipt["candidate_content_sha256"] != candidate_content_sha256
        or receipt["workspace_sha256"] != workspace_sha256
        or receipt["assay"] != task_input["assay"]
        or receipt["isolation_enforced"] is not runtime.isolation_enforced
        or type(observations) is not list
        or not observations
    ):
        raise SolutionExperimentError("coding evaluation receipt changed execution")
    observation_keys = {
        "cpu_microseconds",
        "memory_peak_bytes",
        "processes_peak",
        "source",
        "storage_write_bytes",
        "wall_milliseconds",
    }
    normalized_observations: list[dict[str, object]] = []
    for raw in observations:
        if type(raw) is not dict or set(raw) != observation_keys:
            raise SolutionExperimentError("coding kernel observation is malformed")
        for name in (
            "cpu_microseconds",
            "memory_peak_bytes",
            "processes_peak",
            "storage_write_bytes",
        ):
            value = raw[name]
            if value is not None and (type(value) is not int or value < 0):
                raise SolutionExperimentError("coding kernel observation is malformed")
        if (
            type(raw["wall_milliseconds"]) is not int
            or raw["wall_milliseconds"] < 0
            or type(raw["source"]) is not str
            or not raw["source"]
        ):
            raise SolutionExperimentError("coding kernel observation is malformed")
        if runtime.isolation_enforced:
            required = {
                "cpu": "cpu_microseconds",
                "memory": "memory_peak_bytes",
                "processes": "processes_peak",
                "storage": "storage_write_bytes",
                "wall": "wall_milliseconds",
            }
            if raw["source"] != "cgroup-v2" or any(
                raw[required[name]] is None for name in runtime.required_observations
            ):
                raise SolutionExperimentError(
                    "coding kernel observation omitted required isolation evidence"
                )
        normalized_observations.append(raw)
    if runtime.cost_mode == "deterministic-fixture-v1":
        expected_cost = {name: 0 for name in RESOURCE_NAMES}
    else:
        expected_cost = {
            "actions": 1,
            "energy_millijoules": 0,
            "gpu_milliseconds": 0,
            "memory_bytes": max(
                int(item["memory_peak_bytes"] or 0) for item in normalized_observations
            ),
            "storage_bytes": sum(
                int(item["storage_write_bytes"] or 0)
                for item in normalized_observations
            ),
            "tokens": 0,
            "wall_milliseconds": sum(
                int(item["wall_milliseconds"]) for item in normalized_observations
            ),
        }
    if receipt["cost"] != expected_cost:
        raise SolutionExperimentError("coding evaluation receipt cost does not replay")
    return execution


def _expected_final_selection(
    state: PopulationState,
    development_experiment_id: str,
    tie_draw: dict[str, int],
) -> tuple[str, dict[str, int], list[str], str]:
    archive_id = state.latest_archive_by_experiment.get(development_experiment_id)
    if archive_id is None:
        raise SolutionExperimentError("coding development archive is absent")
    archive = cast(dict[str, object], state.record(archive_id)["body"])
    members = cast(list[dict[str, object]], archive["members"])
    if not members:
        raise SolutionExperimentError("coding development archive is empty")
    best_rate = max(
        float(cast(dict[str, object], member["task"])["rate"]) for member in members
    )
    best_reliability = max(
        float(member["reliability"])
        for member in members
        if float(cast(dict[str, object], member["task"])["rate"]) == best_rate
    )
    eligible = sorted(
        str(member["candidate_id"])
        for member in members
        if float(cast(dict[str, object], member["task"])["rate"]) == best_rate
        and float(member["reliability"]) == best_reliability
    )
    tie_index = (int(tie_draw["numerator"]) * len(eligible)) // int(
        tie_draw["denominator"]
    )
    selected = eligible[tie_index]
    all_candidates = sorted(str(member["candidate_id"]) for member in members)
    allocation_draw = {
        "denominator": len(all_candidates),
        "numerator": all_candidates.index(selected),
    }
    return selected, allocation_draw, eligible, archive_id


def _retry_effect_receipts(
    root: Path, driver_lines: list[str]
) -> tuple[set[str], set[str]]:
    expected: dict[str, tuple[str, str]] = {}
    for line in driver_lines[1:]:
        record = decode_json_object(line, SolutionExperimentError)
        attempts = record.get("attempts")
        intent_id = record.get("intent_id")
        if type(attempts) is not list or type(intent_id) is not str:
            raise SolutionExperimentError("coding Driver retry attempts are malformed")
        for index, attempt in enumerate(attempts[:-1]):
            next_attempt = attempts[index + 1]
            if (
                type(attempt) is not dict
                or type(attempt.get("attempt_id")) is not str
                or type(next_attempt) is not dict
                or type(next_attempt.get("reason")) is not str
            ):
                raise SolutionExperimentError(
                    "coding Driver retry attempt is malformed"
                )
            expected[str(attempt["attempt_id"])] = (
                intent_id,
                str(next_attempt["reason"]),
            )
    retry_root = root / "state" / "retry-effects"
    actual: set[str] = set()
    mutation: set[str] = set()
    evaluation: set[str] = set()
    if retry_root.exists():
        if retry_root.is_symlink() or not retry_root.is_dir():
            raise SolutionExperimentError("coding retry-effects directory is unsafe")
        for path in sorted(retry_root.iterdir()):
            document = _canonical_document(path, "coding retry-effects receipt")
            if set(document) != {
                "attempt_id",
                "evaluation_receipt_sha256",
                "intent_id",
                "mutation_receipt_sha256",
                "retry_effects_schema",
            }:
                raise SolutionExperimentError(
                    "coding retry-effects receipt is malformed"
                )
            attempt_id = document["attempt_id"]
            mutation_values = document["mutation_receipt_sha256"]
            evaluation_values = document["evaluation_receipt_sha256"]
            schema = document["retry_effects_schema"]
            lists = (mutation_values, evaluation_values)
            expected_identity = expected.get(cast(str, attempt_id))
            if (
                type(schema) is not str
                or schema
                not in {
                    "darwinian-coding-retry-effects-v1",
                    "darwinian-coding-retry-effects-v2",
                }
                or type(attempt_id) is not str
                or path.name != f"{attempt_id}.json"
                or expected_identity is None
                or expected_identity[0] != document["intent_id"]
                or any(
                    type(values) is not list
                    or values != sorted(set(values))
                    or any(
                        type(digest) is not str
                        or len(digest) != 64
                        or any(
                            character not in "0123456789abcdef" for character in digest
                        )
                        for digest in values
                    )
                    for values in lists
                )
            ):
                raise SolutionExperimentError(
                    "coding retry-effects identity is malformed"
                )
            marker = "\nretry-effects-sha256:"
            if schema == "darwinian-coding-retry-effects-v2":
                source = path.read_bytes()
                receipt_id = hashlib.sha256(source).hexdigest()
                suffix = f"{marker}{receipt_id}"
                if (
                    not expected_identity[1].endswith(suffix)
                    or not expected_identity[1][: -len(suffix)].strip()
                ):
                    raise SolutionExperimentError(
                        "coding retry-effects receipt is not bound to retry"
                    )
            elif marker in expected_identity[1]:
                raise SolutionExperimentError(
                    "coding retry-effects schema was downgraded"
                )
            actual.add(attempt_id)
            mutation.update(cast(list[str], mutation_values))
            evaluation.update(cast(list[str], evaluation_values))
    if actual != set(expected):
        raise SolutionExperimentError("coding retry-effects receipt set is incomplete")
    return mutation, evaluation


def verify_experiment(root: Path) -> dict[str, object]:
    root = root.expanduser().absolute()
    profile = load_task_profile(root / "task.json", allow_legacy_inline_final=True)
    final_tasks = _protected_final_tasks(root, profile, copy_if_absent=False)
    runtime = load_runtime_manifest(root / "runtime.json")
    descriptor = load_harness_descriptor(
        root / "selected-harness.json", allow_legacy=True
    )
    _verify_harness_provenance(root, descriptor)
    coding_runtime_id = _coding_runtime_id(profile, runtime, descriptor)
    driver = verify_population_driver(root / "state")
    state = load_state(population_root(root / "state"))
    if not state.final_evaluation_started:
        raise SolutionExperimentError("coding Population is not final-sealed")
    driver_lines = (
        (root / "state" / "driver.jsonl").read_text(encoding="utf-8").splitlines()
    )
    if not driver_lines:
        raise SolutionExperimentError("coding driver ledger is empty")
    retry_mutations, retry_evaluations = _retry_effect_receipts(root, driver_lines)
    driver_header = decode_json_object(driver_lines[0], SolutionExperimentError)
    configuration = driver_header.get("configuration")
    if type(configuration) is not dict:
        raise SolutionExperimentError("coding driver configuration is malformed")
    generation = configuration.get("generation")
    population_configuration = configuration.get("population")
    if (
        type(generation) is not dict
        or generation.get("tasks") != task_documents(profile, "development")
        or type(population_configuration) is not dict
        or type(population_configuration.get("experiment")) is not dict
        or cast(dict[str, object], population_configuration["experiment"]).get(
            "runtime_id"
        )
        != coding_runtime_id
    ):
        raise SolutionExperimentError("coding task profile does not match driver state")
    expected_harness_repository = str((root / "harness.git").absolute())
    harness_artifact = cast(dict[str, object], descriptor["artifact"])
    if (
        descriptor["descriptor_schema"] == "selected-evolutionary-harness-v1"
        and harness_artifact.get("repository") != expected_harness_repository
    ):
        raise SolutionExperimentError(
            "legacy selected harness identifies another repository"
        )
    localized_harness_artifact = decode_agent_artifact(
        {**harness_artifact, "repository": expected_harness_repository}
    )
    previous_harness_repository = os.environ.get("METERING_GIT_REPOSITORY")
    try:
        os.environ["METERING_GIT_REPOSITORY"] = expected_harness_repository
        with tempfile.TemporaryDirectory(
            prefix="metering-harness-descriptor-verify-"
        ) as temporary:
            harness_checkout = Path(temporary) / "checkout"
            clone_verified(localized_harness_artifact, harness_checkout)
            harness_candidate = load_candidate(harness_checkout)
            assert_candidate_compatible(
                runtime,
                (
                    harness_checkout / harness_candidate.paths["dependency_lock"]
                ).read_bytes(),
            )
    finally:
        if previous_harness_repository is None:
            os.environ.pop("METERING_GIT_REPOSITORY", None)
        else:
            os.environ["METERING_GIT_REPOSITORY"] = previous_harness_repository
    if (
        harness_candidate.manifest_id != descriptor["manifest_id"]
        or descriptor["runtime_id"] != runtime.runtime_id
    ):
        raise SolutionExperimentError("selected harness identity does not replay")
    conformance = _canonical_document(root / "conformance.json", "kernel conformance")
    conformance_body = {
        name: value for name, value in conformance.items() if name != "conformance_id"
    }
    if (
        conformance.get("schema") != "evolutionary-harness-conformance-v1"
        or conformance.get("conformance_id") != canonical_digest(conformance_body)
        or conformance.get("runtime_id") != runtime.runtime_id
        or conformance.get("candidate_manifest_id") != descriptor["manifest_id"]
        or conformance.get("isolation_enforced") is not runtime.isolation_enforced
    ):
        raise SolutionExperimentError("kernel conformance identity does not replay")
    expected_solution_repository = str((root / "candidate.git").absolute())
    previous = os.environ.get("METERING_GIT_REPOSITORY")
    candidate_files: dict[str, str] = {}
    candidate_snapshots: dict[str, list[dict[str, object]]] = {}
    try:
        os.environ["METERING_GIT_REPOSITORY"] = expected_solution_repository
        with tempfile.TemporaryDirectory(prefix="metering-coding-verify-") as temporary:
            temporary_root = Path(temporary)
            for index, candidate in enumerate(state.candidates.values()):
                artifact = cast(dict[str, object], candidate["artifact"])
                if artifact.get("repository") != expected_solution_repository:
                    raise SolutionExperimentError(
                        "solution candidate identifies another repository"
                    )
                checkout = temporary_root / str(index)
                clone_verified(artifact, checkout)
                snapshot = snapshot_directory(checkout)
                candidate_id = str(candidate["candidate_id"])
                candidate_snapshots[candidate_id] = snapshot
                candidate_files[candidate_id] = files_digest(snapshot)
    finally:
        if previous is None:
            os.environ.pop("METERING_GIT_REPOSITORY", None)
        else:
            os.environ["METERING_GIT_REPOSITORY"] = previous
    for candidate_id, parents in state.candidate_parents.items():
        artifact = cast(dict[str, object], state.candidates[candidate_id]["artifact"])
        commit = str(artifact["commit"])
        actual_parents = (
            run_git(["show", "-s", "--format=%P", commit], cwd=root / "candidate.git")
            .strip()
            .split()
        )
        if not parents:
            expected = cast(dict[str, str], profile["repository"])["base_commit"]
            if (
                commit != expected
                or actual_parents
                != run_git(
                    ["show", "-s", "--format=%P", expected], cwd=root / "candidate.git"
                )
                .strip()
                .split()
            ):
                raise SolutionExperimentError("solution seed identity changed")
        else:
            if len(parents) != 1:
                raise SolutionExperimentError("solution mutation must have one parent")
            parent_artifact = cast(
                dict[str, object], state.candidates[parents[0]]["artifact"]
            )
            if actual_parents != [parent_artifact["commit"]]:
                raise SolutionExperimentError("solution Git lineage does not replay")
    mutation_schema = (
        "darwinian-coding-mutation-receipt-v2"
        if descriptor["descriptor_schema"] == "selected-evolutionary-harness-v2"
        else "darwinian-coding-mutation-receipt-v1"
    )
    mutation_receipts = _receipt_files(root / "mutation-receipts", mutation_schema)
    child_ids = [
        candidate_id
        for candidate_id, parents in state.candidate_parents.items()
        if parents
    ]
    mutation_matches: set[str] = set()
    expected_mutation_keys = {
        "base_files_sha256",
        "changed_paths",
        "completion",
        "goal_sha256",
        "harness_candidate_id",
        "harness_manifest_id",
        "receipt_schema",
        "result_files_sha256",
        "runtime_id",
    }
    if descriptor["descriptor_schema"] == "selected-evolutionary-harness-v2":
        expected_mutation_keys.add("coding_runtime_id")
    for digest, receipt in mutation_receipts.items():
        if set(receipt) != expected_mutation_keys:
            raise SolutionExperimentError("coding mutation receipt is malformed")
        if (
            receipt["runtime_id"] != runtime.runtime_id
            or receipt["harness_candidate_id"] != descriptor["candidate_id"]
            or receipt["harness_manifest_id"] != descriptor["manifest_id"]
            or (
                descriptor["descriptor_schema"] == "selected-evolutionary-harness-v2"
                and receipt["coding_runtime_id"] != coding_runtime_id
            )
        ):
            raise SolutionExperimentError("coding mutation receipt changed harness")
        completion = receipt["completion"]
        if type(completion) is not dict or set(completion) != {
            "actions",
            "input_tokens",
            "model_calls",
            "output_tokens",
            "population_cost",
            "transcript_sha256",
        }:
            raise SolutionExperimentError("coding mutation completion is malformed")
        for name in ("actions", "input_tokens", "model_calls", "output_tokens"):
            if type(completion[name]) is not int or int(completion[name]) < 0:
                raise SolutionExperimentError(
                    "coding mutation completion count is malformed"
                )
        if int(completion["model_calls"]) > runtime.max_model_calls:
            raise SolutionExperimentError("coding mutation exceeded model call limit")
        population_cost = completion["population_cost"]
        if type(population_cost) is not dict or set(population_cost) != set(
            RESOURCE_NAMES
        ):
            raise SolutionExperimentError("coding mutation cost is malformed")
        if any(
            type(value) is not int or value < 0 for value in population_cost.values()
        ):
            raise SolutionExperimentError("coding mutation cost is malformed")
        if (
            type(completion["transcript_sha256"]) is not str
            or len(str(completion["transcript_sha256"])) != 64
        ):
            raise SolutionExperimentError("coding mutation transcript is malformed")
        mutation_matches.add(digest)
    matched_mutations: set[str] = set()
    for child_id in child_ids:
        parent_id = state.candidate_parents[child_id][0]
        actual_changes = changed_paths(
            candidate_snapshots[parent_id], candidate_snapshots[child_id]
        )
        try:
            require_allowed_changes(
                actual_changes, cast(list[str], profile["allowed_paths"])
            )
        except WorkspaceError as exc:
            raise SolutionExperimentError(str(exc)) from exc
        matches = [
            (digest, receipt)
            for digest, receipt in mutation_receipts.items()
            if receipt.get("base_files_sha256") == candidate_files[parent_id]
            and receipt.get("result_files_sha256") == candidate_files[child_id]
            and receipt.get("changed_paths") == actual_changes
            and receipt.get("runtime_id") == runtime.runtime_id
            and receipt.get("harness_candidate_id") == descriptor["candidate_id"]
            and (
                descriptor["descriptor_schema"] == "selected-evolutionary-harness-v1"
                or receipt.get("coding_runtime_id") == coding_runtime_id
            )
        ]
        authoritative = [item for item in matches if item[0] not in retry_mutations]
        if len(authoritative) == 1:
            matched = authoritative[0]
        elif not authoritative and matches:
            matched = sorted(matches, key=lambda item: item[0])[0]
        else:
            raise SolutionExperimentError(
                "solution child does not have one bound mutation receipt"
            )
        matched_mutations.add(matched[0])
    if (
        not retry_mutations <= mutation_matches
        or not (mutation_matches - matched_mutations) <= retry_mutations
    ):
        raise SolutionExperimentError(
            "coding mutation receipt set does not match solution lineage or retry effects"
        )
    evaluation_receipts = _receipt_files(root / "evaluation-receipts", RECEIPT_SCHEMA)
    development_tasks = task_documents(profile, "development")
    development_task_ids = {canonical_digest(task): task for task in development_tasks}
    final_tasks_by_case = {str(task["case_id"]): task for task in final_tasks}
    expected_development: set[str] = set()
    final_runs: list[dict[str, object]] = []
    for run in state.runs:
        run_record = cast(dict[str, object], run["run"])
        experiment = state.experiments[str(run_record["experiment_id"])]
        if experiment["runtime_id"] != coding_runtime_id:
            raise SolutionExperimentError("Population run changed coding runtime")
        if experiment["role"] == "development":
            seed = run_record["seed"]
            if type(seed) is not dict or type(seed.get("receipt_sha256")) is not list:
                raise SolutionExperimentError(
                    "development run omitted receipt identities"
                )
            digests = cast(list[str], seed["receipt_sha256"])
            candidate_id = str(run_record["candidate_id"])
            observed_tasks: set[str] = set()
            actual_passed = 0
            actual_safety_failures = 0
            actual_cost = {name: 0 for name in RESOURCE_NAMES}
            for digest in digests:
                receipt = evaluation_receipts.get(digest)
                if receipt is None:
                    raise SolutionExperimentError(
                        "development coding receipt is absent"
                    )
                task_id = str(receipt.get("task_id"))
                task = development_task_ids.get(task_id)
                if task is None or task_id in observed_tasks:
                    raise SolutionExperimentError(
                        "development coding receipt changed task coverage"
                    )
                artifact = cast(
                    dict[str, object], state.candidates[candidate_id]["artifact"]
                )
                execution = _verify_bound_evaluation_receipt(
                    receipt,
                    candidate_id=candidate_id,
                    candidate_content_sha256=artifact["content_sha256"],
                    workspace_sha256=candidate_files[candidate_id],
                    task=task,
                    runtime=runtime,
                )
                actual_passed += int(
                    execution["returncode"] == 0 and execution["timed_out"] is False
                )
                actual_safety_failures += int(
                    runtime.isolation_enforced
                    and receipt["isolation_enforced"] is not True
                )
                receipt_cost = cast(dict[str, int], receipt["cost"])
                for name in RESOURCE_NAMES:
                    actual_cost[name] += receipt_cost[name]
                observed_tasks.add(task_id)
            if observed_tasks != set(development_task_ids):
                raise SolutionExperimentError(
                    "development coding receipt set is incomplete"
                )
            run_evidence = cast(dict[str, object], run["evidence"])
            task_evidence = cast(dict[str, object], run_evidence["task"])
            if (
                task_evidence.get("case_count") != len(development_tasks)
                or task_evidence.get("passed_count") != actual_passed
                or task_evidence.get("safety_failures") != actual_safety_failures
                or run_evidence.get("protected_passed")
                is not (actual_safety_failures == 0)
                or run_evidence.get("cost") != actual_cost
                or run_evidence.get("behavior_distribution")
                != [
                    1.0 - actual_passed / len(development_tasks),
                    actual_passed / len(development_tasks),
                ]
            ):
                raise SolutionExperimentError(
                    "development Population evidence does not match execution receipts"
                )
            expected_development.update(digests)
        else:
            final_runs.append(run)
    if len(final_runs) != 1:
        raise SolutionExperimentError("coding experiment must have one final run")
    final_bundles = _receipt_files(
        root / "final-receipts", BUNDLE_SCHEMA, schema_key="final_assay_schema"
    )
    if len(final_bundles) != 1:
        raise SolutionExperimentError("coding experiment must have one final bundle")
    bundle_digest, bundle = next(iter(final_bundles.items()))
    final_evidence = cast(dict[str, object], final_runs[0]["evidence"])
    reference = final_evidence["evidence_receipt"]
    if type(reference) is not dict or reference.get("sha256") != bundle_digest:
        raise SolutionExperimentError("final Population run changed bundle identity")
    cases = bundle.get("cases")
    if type(cases) is not list:
        raise SolutionExperimentError("final coding bundle cases are malformed")
    expected_final: set[str] = set()
    final_candidate_id = str(
        cast(dict[str, object], final_runs[0]["run"])["candidate_id"]
    )
    observed_final_cases: set[str] = set()
    final_passed = 0
    final_safety_failures = 0
    final_cost = {name: 0 for name in RESOURCE_NAMES}
    for raw_case in cases:
        if type(raw_case) is not dict or set(raw_case) != {
            "case_id",
            "evidence",
            "forecast",
            "outcome",
            "passed",
            "receipt",
            "receipt_sha256",
            "result_sha256",
            "safety_passed",
            "target_probability",
        }:
            raise SolutionExperimentError("final coding case is malformed")
        case_id = raw_case.get("case_id")
        digest = raw_case.get("receipt_sha256")
        if (
            type(case_id) is not str
            or case_id in observed_final_cases
            or type(digest) is not str
            or digest not in evaluation_receipts
            or case_id not in final_tasks_by_case
        ):
            raise SolutionExperimentError("final coding case identity is malformed")
        receipt = evaluation_receipts[digest]
        artifact = cast(
            dict[str, object], state.candidates[final_candidate_id]["artifact"]
        )
        execution = _verify_bound_evaluation_receipt(
            receipt,
            candidate_id=final_candidate_id,
            candidate_content_sha256=artifact["content_sha256"],
            workspace_sha256=candidate_files[final_candidate_id],
            task=final_tasks_by_case[case_id],
            runtime=runtime,
        )
        passed = execution["returncode"] == 0 and execution["timed_out"] is False
        safety_passed = (
            receipt["isolation_enforced"] is True
            if runtime.isolation_enforced
            else True
        )
        reference = {
            "sha256": digest,
            "uri": (root / "evaluation-receipts" / f"{digest}.json").as_uri(),
        }
        forecast = {
            "outcomes": [
                {"outcome": "fail", "probability": 0.5},
                {"outcome": "pass", "probability": 0.5},
            ]
        }
        submission = {
            "_metering_coding_candidate": {
                "receipt": reference,
                "runtime_id": runtime.runtime_id,
            },
            "execution": {
                "returncode": execution["returncode"],
                "stderr_sha256": hashlib.sha256(
                    str(execution["stderr"]).encode("utf-8")
                ).hexdigest(),
                "stdout_sha256": hashlib.sha256(
                    str(execution["stdout"]).encode("utf-8")
                ).hexdigest(),
                "timed_out": execution["timed_out"],
            },
        }
        expected_case = {
            "case_id": case_id,
            "evidence": {"receipt_sha256": digest},
            "forecast": forecast,
            "outcome": "pass" if passed else "fail",
            "passed": passed,
            "receipt": reference,
            "receipt_sha256": digest,
            "result_sha256": canonical_digest(
                {"forecast": forecast, "submission": submission}
            ),
            "safety_passed": safety_passed,
            "target_probability": 0.5,
        }
        if raw_case != expected_case:
            raise SolutionExperimentError("final coding case does not replay")
        final_passed += int(passed)
        final_safety_failures += int(not safety_passed)
        cost = cast(dict[str, int], receipt["cost"])
        for name in RESOURCE_NAMES:
            final_cost[name] += cost[name]
        expected_final.add(digest)
        observed_final_cases.add(case_id)
    if observed_final_cases != set(final_tasks_by_case):
        raise SolutionExperimentError("final coding task set is incomplete")
    final_task_evidence = cast(dict[str, object], final_evidence["task"])
    if (
        final_task_evidence
        != {
            "case_count": len(final_tasks),
            "passed_count": final_passed,
            "safety_failures": final_safety_failures,
        }
        or final_evidence.get("cost") != final_cost
        or final_evidence.get("protected_passed") is not (final_safety_failures == 0)
        or final_evidence.get("behavior_distribution")
        != [
            1.0 - final_passed / len(final_tasks),
            final_passed / len(final_tasks),
        ]
    ):
        raise SolutionExperimentError(
            "final Population evidence does not match execution receipts"
        )
    if (
        not retry_evaluations <= set(evaluation_receipts)
        or set(evaluation_receipts)
        != expected_development | expected_final | retry_evaluations
    ):
        raise SolutionExperimentError(
            "coding evaluation receipt set does not match authenticated runs or retry effects"
        )
    development_experiment_id = str(driver["experiment_id"])
    expected_candidate, allocation_draw, finalists, archive_id = (
        _expected_final_selection(
            state,
            development_experiment_id,
            cast(dict[str, int], profile["final_draw"]),
        )
    )
    final_run_record = cast(dict[str, object], final_runs[0]["run"])
    final_seed = final_run_record["seed"]
    expected_seed = {
        "allocation_record_id": bundle.get("allocation_record_id"),
        "allocation_draw": allocation_draw,
        "selection_policy": "development-task-rate-reliability-v1",
        "tie_draw": profile["final_draw"],
    }
    expected_selection = {
        "allocation_draw": allocation_draw,
        "eligible_candidate_ids": finalists,
        "policy": "development-task-rate-reliability-v1",
        "tie_draw": profile["final_draw"],
    }
    if (
        final_candidate_id != expected_candidate
        or final_seed != expected_seed
        or bundle.get("candidate_id") != expected_candidate
        or bundle.get("runtime_id") != coding_runtime_id
        or bundle.get("evaluator_id")
        != canonical_digest({"command": [sys.executable, str(EVALUATOR)]})
        or bundle.get("selection") != expected_selection
    ):
        raise SolutionExperimentError("coding final selection policy does not replay")
    allocation_id = expected_seed["allocation_record_id"]
    if type(allocation_id) is not str:
        raise SolutionExperimentError("coding final allocation identity is malformed")
    allocation_record = state.record(allocation_id)
    if allocation_record is None:
        raise SolutionExperimentError("coding final allocation record is absent")
    allocation_body = cast(dict[str, object], allocation_record["body"])
    allocation_request = cast(dict[str, object], allocation_body["request"])
    allocation_result = cast(dict[str, object], allocation_body["result"])
    if (
        allocation_request.get("archive_record_id") != archive_id
        or allocation_request.get("draw") != allocation_draw
        or allocation_result.get("selected_candidate_id") != expected_candidate
    ):
        raise SolutionExperimentError("coding final allocation record does not replay")
    archive_record = state.record(archive_id)
    assert archive_record is not None
    trailing_allocations = [
        record_id
        for record_id, _ in state.allocations
        if int(cast(dict[str, object], state.record(record_id))["sequence"])
        > int(archive_record["sequence"])
    ]
    if trailing_allocations != [allocation_id]:
        raise SolutionExperimentError(
            "coding final allocation is not the unique sealed allocation"
        )
    final_experiment = state.experiments[str(final_run_record["experiment_id"])]
    if (
        final_experiment["task_set_id"]
        != canonical_digest(
            {
                "task_set_schema": "protected-darwinian-coding-final-v1",
                "tasks": final_tasks,
            }
        )
        or final_experiment["case_count"] != len(final_tasks)
        or final_experiment["runtime_id"] != coding_runtime_id
    ):
        raise SolutionExperimentError("coding final experiment identity changed")
    selected = _canonical_document(root / "selected-solution.json", "selected solution")
    selected_id = selected.get("candidate_id")
    final_candidate = cast(dict[str, object], final_runs[0]["run"])["candidate_id"]
    if (
        selected.get("descriptor_schema") != "selected-solution-commit-v1"
        or selected_id != final_candidate
        or selected.get("artifact") != state.candidates[str(selected_id)]["artifact"]
        or selected.get("task_id") != profile["task_id"]
        or selected.get("base_commit")
        != cast(dict[str, str], profile["repository"])["base_commit"]
    ):
        raise SolutionExperimentError("selected solution descriptor changed identity")
    patch = (root / "selected.patch").read_bytes()
    expected_patch = run_git(
        [
            "diff",
            "--binary",
            str(selected["base_commit"]),
            str(cast(dict[str, object], selected["artifact"])["commit"]),
        ],
        cwd=root / "candidate.git",
    ).encode("utf-8")
    if patch != expected_patch or hashlib.sha256(patch).hexdigest() != selected.get(
        "patch_sha256"
    ):
        raise SolutionExperimentError("selected solution patch does not replay")
    return {
        "candidate_count": len(state.candidates),
        "coding_runtime_id": coding_runtime_id,
        "driver": driver,
        "evaluation_receipt_count": len(evaluation_receipts),
        "final_run_count": 1,
        "mutation_receipt_count": len(mutation_receipts),
        "schema": "darwinian-coding-verification-v1",
        "selected_candidate_id": selected_id,
        "status": "verified",
        "task_id": profile["task_id"],
    }


def solution_process_status(root: Path) -> dict[str, object]:
    root = root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise SolutionExperimentError(f"experiment root is absent or unsafe: {root}")
    status = load_process_status(root, expected_run_kind="solution")
    if status is not None:
        return status
    if (root / "selected-solution.json").is_file():
        return process_document(6, "solution")
    if (root / "protected-final.json").is_file():
        return process_document(5, "solution")
    if (root / "state" / "driver.jsonl").is_file():
        return process_document(4, "solution")
    raise SolutionExperimentError("coding solution process has not started")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(arguments) == 2 and arguments[0] == "verify":
            result = verify_experiment(Path(arguments[1]))
        elif len(arguments) == 2 and arguments[0] == "status":
            result = solution_process_status(Path(arguments[1]))
        elif len(arguments) == 2 and arguments[0] == "resume":
            result = continue_experiment(Path(arguments[1]))
        elif len(arguments) == 3 and arguments[0] == "retry":
            result = continue_experiment(Path(arguments[1]), retry_reason=arguments[2])
        elif len(arguments) == 5 and arguments[0] in {"fixture", "pi"}:
            result = run_experiment(
                arguments[0],
                Path(arguments[1]),
                Path(arguments[2]),
                Path(arguments[3]),
                Path(arguments[4]),
            )
        else:
            raise SolutionExperimentError(
                "usage: solution_experiment.py {fixture|pi} TASK.json NEW_ROOT "
                "RUNTIME.json SELECTED-HARNESS.json | status ROOT | resume ROOT | "
                "retry ROOT REASON | verify ROOT"
            )
    except (
        CodingFinalError,
        CodingMutationError,
        CodingTaskError,
        GitCandidateError,
        HarnessProtocolError,
        OSError,
        PopulationDriverError,
        ProcessTrackerError,
        RuntimeManifestError,
        SolutionExperimentError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    write_document(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
