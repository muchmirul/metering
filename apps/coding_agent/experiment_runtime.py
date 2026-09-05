"""Solution experiment effects: initialization, recurrence, publication, and retry."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, cast

from apps._support.durable import atomic_write
from apps._support.wire import canonical_json
from apps.coding_agent.experiment_artifacts import (
    canonical_document,
    copy_canonical,
    initialize_solution_repository,
    localize_harness,
    copy_protected_final_tasks,
    verify_harness_provenance,
)
from apps.coding_agent.experiment_config import (
    EVALUATOR,
    GIT_ADAPTER,
    ROOT,
    RUNNER,
    VALIDATE,
    SolutionExperimentError,
    coding_runtime_identity,
    control_command,
    resource_budget,
    solution_driver_request,
    task_runner_timeout,
)
from apps.coding_agent.experiment_replay import verify_experiment
from apps.coding_agent.final_assay import run_final_assay
from apps.coding_agent.harness_workspace_editor import load_harness_descriptor
from apps.coding_agent.process_tracker import advance_process_status
from apps.coding_agent.protocol import load_task_profile
from apps.harness.conformance import run_conformance
from apps.harness.runtime_manifest import RuntimeManifest, load_runtime_manifest
from apps.population.contract import PopulationState, load_state
from apps.population_driver.paths import population_root
from apps.population_driver.runtime import (
    retry_population_driver,
    run_population_driver,
    verify_population_driver,
)
from artifacts.git.git_repository import run_git

FIXTURE_PROPOSER = (
    ROOT / "apps" / "coding_agent" / "fixtures" / "fixture_solution_proposer.py"
)


PI_PROPOSER = ROOT / "connectors" / "fixed" / "pi" / "coding_proposer.py"


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
    copy_canonical(profile_source, profile_path)
    copy_canonical(runtime_source, runtime_path)
    runtime = load_runtime_manifest(runtime_path)
    solution_remote, artifact = initialize_solution_repository(root, profile)
    descriptor_path, descriptor, harness_checkout = localize_harness(
        root, harness_source, runtime
    )
    coding_runtime_id = coding_runtime_identity(profile, runtime, descriptor)
    conformance = run_conformance(
        runtime_path, harness_checkout, allow_fixture=agent == "fixture"
    )
    atomic_write(
        root / "conformance.json",
        (canonical_json(conformance) + "\n").encode("ascii"),
    )
    proposer = FIXTURE_PROPOSER if agent == "fixture" else PI_PROPOSER
    request = solution_driver_request(
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
            pending = canonical_document(
                state_root / "pending" / "round-intent.json", "coding round intent"
            )
            raise SolutionExperimentError(
                "coding development has a pending model intent; explicit retry required "
                f"for intent {pending['intent_id']}"
            )
        advance_process_status(root, stage=5, run_kind="solution")
        final_tasks = copy_protected_final_tasks(root, profile)
        final = run_final_assay(
            population_root(state_root),
            development_experiment_id=str(development["experiment_id"]),
            tasks=final_tasks,
            final_draw=cast(dict[str, int], profile["final_draw"]),
            runner_command=control_command(GIT_ADAPTER),
            evaluator_command=control_command(EVALUATOR),
            runner_timeout=task_runner_timeout(final_tasks),
            evaluator_timeout=300,
            runtime_id=coding_runtime_id,
            bundle_root=root / "final-receipts",
            budget=resource_budget(),
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
        report = canonical_document(report_path, "coding experiment report")
        verify_experiment(root)
        advance_process_status(root, stage=6, run_kind="solution")
        return report
    profile = load_task_profile(root / "task.json", allow_legacy_inline_final=True)
    runtime = load_runtime_manifest(root / "runtime.json")
    descriptor = load_harness_descriptor(
        root / "selected-harness.json", allow_legacy=True
    )
    verify_harness_provenance(root, descriptor)
    coding_runtime_id = coding_runtime_identity(profile, runtime, descriptor)
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
    request = solution_driver_request(
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
            pending = canonical_document(
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
            pending = canonical_document(
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
            final_tasks = copy_protected_final_tasks(root, profile)
            final = run_final_assay(
                population_root(state_root),
                development_experiment_id=str(development["experiment_id"]),
                tasks=final_tasks,
                final_draw=cast(dict[str, int], profile["final_draw"]),
                runner_command=control_command(GIT_ADAPTER),
                evaluator_command=control_command(EVALUATOR),
                runner_timeout=task_runner_timeout(final_tasks),
                evaluator_timeout=300,
                runtime_id=coding_runtime_id,
                bundle_root=root / "final-receipts",
                budget=resource_budget(),
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
