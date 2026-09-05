"""Harness experiment effects: initialization, recurrence, publication, and retry."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, cast

from apps._support.durable import atomic_write
from apps._support.wire import canonical_digest, canonical_json, decode_json_object
from apps.agent_protocol import GIT_ARTIFACT_SCHEMA, decode_agent_artifact
from apps.coding_agent.process_tracker import advance_process_status
from apps.harness.conformance import run_conformance
from apps.harness.experiment_config import (
    CODING_EVALUATOR,
    CODING_FIXTURES,
    EVALUATOR,
    FIXTURE_MODEL,
    FIXTURES,
    GIT_ADAPTER,
    PROFILES,
    REFERENCE,
    VALIDATE,
    ExperimentError,
    capability_first_draw,
    expected_connector,
    harness_commands,
    harness_driver_request,
    load_assay_tasks,
    resource_budget,
)
from apps.harness.experiment_replay import verify_experiment
from apps.harness.final_assay import run_final_assay
from apps.harness.protocol import load_candidate
from apps.harness.runtime_manifest import RuntimeManifest, load_runtime_manifest
from apps.population.contract import PopulationState, load_state
from apps.population_driver.paths import population_root
from apps.population_driver.runtime import (
    retry_population_driver,
    run_population_driver,
    verify_population_driver,
)
from artifacts.git.git_repository import clone_verified, content_sha256, run_git


def _git_environment() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_AUTHOR_EMAIL": "harness-seed@example.invalid",
        "GIT_AUTHOR_NAME": "Metering Harness Seed",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_EMAIL": "harness-seed@example.invalid",
        "GIT_COMMITTER_NAME": "Metering Harness Seed",
    }


def _initialize_repository(root: Path) -> tuple[Path, Path, dict[str, object]]:
    seed = root / "seed-checkout"
    remote = root / "candidate.git"
    shutil.copytree(REFERENCE, seed)
    load_candidate(seed)
    run_git(["init", "--quiet"], cwd=seed)
    run_git(["add", "--all"], cwd=seed)
    tree = run_git(["write-tree"], cwd=seed).strip()
    commit = run_git(
        ["commit-tree", tree],
        cwd=seed,
        input_text="Reference evolutionary harness seed\n",
        environment=_git_environment(),
    ).strip()
    run_git(["update-ref", "refs/heads/main", commit], cwd=seed)
    run_git(["init", "--quiet", "--bare", str(remote)], cwd=seed)
    run_git(["remote", "add", "origin", str(remote)], cwd=seed)
    run_git(["push", "--quiet", "origin", "main:refs/heads/main"], cwd=seed)
    artifact = decode_agent_artifact(
        {
            "artifact_schema": GIT_ARTIFACT_SCHEMA,
            "commit": commit,
            "content_sha256": content_sha256(seed, commit),
            "entrypoint": "harness.json",
            "git_tree": tree,
            "outputs": [],
            "repository": str(remote),
        }
    )
    return seed, remote, artifact


@contextmanager
def _configured_environment(
    *,
    agent: str,
    runtime_path: Path,
    runtime: RuntimeManifest,
    remote: Path,
    receipts: Path,
    runner_command: list[str],
    candidate_paths: list[str],
) -> Iterator[None]:
    changes = {
        "METERING_GIT_ALLOWED_PATHS_JSON": canonical_json(candidate_paths),
        "METERING_GIT_EXECUTOR_COMMAND": canonical_json(runner_command),
        "METERING_GIT_EXECUTOR_TIMEOUT": "600",
        "METERING_GIT_REF_PREFIX": "refs/heads/evolution/harness",
        "METERING_GIT_REPOSITORY": str(remote),
        "METERING_GIT_VALIDATE_COMMAND": canonical_json(
            [sys.executable, str(VALIDATE)]
        ),
        "METERING_GIT_VALIDATE_TIMEOUT": "60",
        "METERING_HARNESS_ALLOW_UNSAFE_FIXTURE": "1" if agent == "fixture" else None,
        "METERING_HARNESS_MODEL": runtime.model["model"],
        "METERING_HARNESS_MODEL_COMMAND": (
            canonical_json([sys.executable, str(FIXTURE_MODEL)])
            if agent == "fixture"
            else None
        ),
        "METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES": str(runtime.max_output_bytes),
        "METERING_HARNESS_MODEL_TIMEOUT": str(runtime.model_timeout_seconds),
        "METERING_HARNESS_PROVIDER": runtime.model["provider"],
        "METERING_HARNESS_REASONING": runtime.model["reasoning"],
        "METERING_HARNESS_RECEIPT_DIR": str(receipts),
        "METERING_HARNESS_RUNTIME_MANIFEST": str(runtime_path),
    }
    old = {name: os.environ.get(name) for name in changes}
    try:
        for name, value in changes.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _completed_harness_final(
    state: PopulationState,
) -> dict[str, object] | None:
    final_runs = [
        item
        for item in state.runs
        if state.experiments[
            str(cast(dict[str, object], item["run"])["experiment_id"])
        ]["role"]
        == "final"
    ]
    if not final_runs:
        return None
    if len(final_runs) != 1:
        raise ExperimentError("harness experiment has multiple final runs")
    body = final_runs[0]
    run = cast(dict[str, object], body["run"])
    evidence = cast(dict[str, object], body["evidence"])
    task = cast(dict[str, object], evidence["task"])
    seed = cast(dict[str, object], run["seed"])
    return {
        "allocation_record_id": seed["allocation_record_id"],
        "candidate_id": run["candidate_id"],
        "experiment_id": run["experiment_id"],
        "passed_count": task["passed_count"],
        "receipt": evidence["evidence_receipt"],
        "run_record_id": state.run_record_ids[str(run["run_id"])],
        "safety_failures": task["safety_failures"],
        "task_count": task["case_count"],
    }


def _finish_experiment(
    root: Path,
    *,
    agent: str,
    assay: str,
    runtime: RuntimeManifest,
    development: dict[str, object],
    development_tasks: list[dict[str, object]],
    evaluator_path: Path,
    conformance: dict[str, object],
) -> dict[str, object]:
    if development["status"] == "pending_round":
        pending_path = root / "state" / "pending" / "round-intent.json"
        pending = decode_json_object(
            pending_path.read_text(encoding="ascii"), ExperimentError
        )
        raise ExperimentError(
            "development has an explicit pending intent; inspect and retry before "
            f"final: {pending['intent_id']}"
        )
    state_root = root / "state"
    receipts = root / "receipts"
    if assay == "coding-agent-v1":
        final_tasks = load_assay_tasks(CODING_FIXTURES / "final-tasks.json")
        selection_policy = {
            "policy": "development-task-rate-reliability-v1",
            "tie_draw": {"denominator": 1, "numerator": 0},
        }
        expected_final_candidate, final_draw, finalists, _ = capability_first_draw(
            state_root,
            str(development["experiment_id"]),
            {"denominator": 1, "numerator": 0},
        )
        final_selection = {
            "eligible_candidate_ids": finalists,
            **selection_policy,
        }
        assay_document = {
            "assay_schema": "coding-agent-assay-v1",
            "development_tasks": development_tasks,
            "final_selection": selection_policy,
            "final_tasks": final_tasks,
            "schema_version": 1,
        }
        atomic_write(
            root / "assay.json",
            (canonical_json(assay_document) + "\n").encode("ascii"),
        )
    else:
        final_tasks = load_assay_tasks(FIXTURES / "final-tasks.json")
        expected_final_candidate = None
        final_draw = {"denominator": 1, "numerator": 0}
        final_selection = None
        assay_document = None
    population = load_state(population_root(state_root))
    final = _completed_harness_final(population)
    if final is None:
        if any(
            experiment["role"] == "final"
            for experiment in population.experiments.values()
        ):
            raise ExperimentError(
                "protected harness final evaluation started without a complete run; "
                "it is sealed and cannot be retried"
            )
        final = run_final_assay(
            population_root(state_root),
            development_experiment_id=str(development["experiment_id"]),
            tasks=final_tasks,
            final_draw=final_draw,
            runner_command=[sys.executable, str(GIT_ADAPTER)],
            evaluator_command=[sys.executable, str(evaluator_path)],
            runner_timeout=600,
            evaluator_timeout=30,
            runtime=runtime,
            receipt_root=receipts,
            budget=resource_budget(),
        )
    if (
        expected_final_candidate is not None
        and final["candidate_id"] != expected_final_candidate
    ):
        raise ExperimentError("coding harness final allocation changed policy")
    if assay == "coding-agent-v1":
        population = load_state(population_root(state_root))
        selected_id = str(final["candidate_id"])
        selected = population.candidates[selected_id]
        selected_artifact = cast(dict[str, object], selected["artifact"])
        with tempfile.TemporaryDirectory(
            prefix="metering-selected-harness-"
        ) as temporary:
            checkout = Path(temporary) / "checkout"
            clone_verified(selected_artifact, checkout)
            selected_manifest = load_candidate(checkout).manifest_id
        final_receipt = cast(dict[str, object], final["receipt"])
        assert assay_document is not None
        selected_harness = {
            "artifact": selected_artifact,
            "candidate_id": selected_id,
            "descriptor_schema": "selected-evolutionary-harness-v2",
            "manifest_id": selected_manifest,
            "provenance": {
                "assay_id": canonical_digest(assay_document),
                "development_experiment_id": development["experiment_id"],
                "final_allocation_record_id": final["allocation_record_id"],
                "final_passed_count": final["passed_count"],
                "final_receipt_sha256": final_receipt["sha256"],
                "final_run_record_id": final["run_record_id"],
                "final_safety_failures": final["safety_failures"],
                "final_task_count": final["task_count"],
                "population_head_record_id": population.head_id,
            },
            "runtime_id": runtime.runtime_id,
        }
        atomic_write(
            root / "selected-harness.json",
            (canonical_json(selected_harness) + "\n").encode("ascii"),
        )
    else:
        selected_harness = None
    verified = verify_population_driver(state_root)
    report = {
        "agent": agent,
        "assay": assay,
        "conformance_id": conformance["conformance_id"],
        "development": development,
        "final": final,
        "runtime_id": runtime.runtime_id,
        "schema": "evolutionary-harness-experiment-v1",
        "selected_harness": selected_harness,
        "verified": verified,
    }
    if final_selection is not None:
        report["final_selection"] = final_selection
    atomic_write(
        root / "experiment-report.json",
        (canonical_json(report) + "\n").encode("ascii"),
    )
    if assay == "coding-agent-v1":
        advance_process_status(root, stage=3, run_kind="harness")
    return report


def run_experiment(
    agent: str,
    root: Path,
    runtime_source: Path | None,
    *,
    assay: str = "arithmetic-v1",
) -> dict[str, object]:
    if root.exists():
        raise ExperimentError(f"experiment root must not exist: {root}")
    if agent not in {"fixture", "pi", "prime-agent"}:
        raise ExperimentError("agent must be fixture, pi, or prime-agent")
    if assay not in {"arithmetic-v1", "coding-agent-v1"}:
        raise ExperimentError("assay must be arithmetic-v1 or coding-agent-v1")
    source = runtime_source or (PROFILES / "runtime-fixture.json")
    runtime = load_runtime_manifest(source)
    if runtime.model["connector"] != expected_connector(agent):
        raise ExperimentError("runtime model connector does not match selected agent")
    root.mkdir(parents=True)
    if assay == "coding-agent-v1":
        advance_process_status(root, stage=1, run_kind="harness")
    runtime_path = root / "runtime.json"
    atomic_write(
        runtime_path, (canonical_json(runtime.document) + "\n").encode("ascii")
    )
    runtime = load_runtime_manifest(runtime_path)
    seed, remote, artifact = _initialize_repository(root)
    candidate = load_candidate(seed)
    conformance = run_conformance(runtime_path, seed, allow_fixture=agent == "fixture")
    atomic_write(
        root / "conformance.json",
        (canonical_json(conformance) + "\n").encode("ascii"),
    )
    proposal_command, executor_command = harness_commands(agent)
    receipts = root / "receipts"
    state = root / "state"
    if assay == "coding-agent-v1":
        development_tasks = load_assay_tasks(CODING_FIXTURES / "development-tasks.json")
        evaluator_path = CODING_EVALUATOR
        evaluation = "evolutionary-harness/development-coding-agent-v1"
        objective = (
            "Mutate exactly one typed Pi harness locus so independent sandboxed "
            "coding assays pass more cases. Preserve the action protocol and use the "
            "fixed coding workspace helpers. Do not edit tasks or claim success."
        )
        population_name = "coding-agent-harness-evolution"
    else:
        development_tasks = load_assay_tasks(FIXTURES / "development-tasks.json")
        evaluator_path = EVALUATOR
        evaluation = "evolutionary-harness/development-addition-v1"
        objective = (
            "Mutate one typed harness locus so the external arithmetic assay solves "
            "left-plus-right tasks more reliably. Do not claim success."
        )
        population_name = "reference-evolutionary-harness"
    request = harness_driver_request(
        artifact,
        proposal_command=proposal_command,
        tasks=development_tasks,
        runtime=runtime,
        evaluator_path=evaluator_path,
        evaluation=evaluation,
        objective=objective,
        population_name=population_name,
    )
    candidate_paths = ["harness.json", *sorted(candidate.paths.values())]
    if assay == "coding-agent-v1":
        advance_process_status(root, stage=2, run_kind="harness")
    with _configured_environment(
        agent=agent,
        runtime_path=runtime_path,
        runtime=runtime,
        remote=remote,
        receipts=receipts,
        runner_command=executor_command,
        candidate_paths=candidate_paths,
    ):
        development = run_population_driver(canonical_json(request), state)
        return _finish_experiment(
            root,
            agent=agent,
            assay=assay,
            runtime=runtime,
            development=development,
            development_tasks=development_tasks,
            evaluator_path=evaluator_path,
            conformance=cast(dict[str, object], conformance),
        )


def _record_harness_retry_effects(root: Path, pending: dict[str, object]) -> str:
    attempts = pending.get("attempts")
    if type(attempts) is not list or not attempts or type(attempts[-1]) is not dict:
        raise ExperimentError("harness pending attempts are malformed")
    attempt_id = cast(dict[str, object], attempts[-1]).get("attempt_id")
    intent_id = pending.get("intent_id")
    if type(attempt_id) is not str or type(intent_id) is not str:
        raise ExperimentError("harness pending attempt identity is malformed")
    receipt_root = root / "receipts"
    receipt_digests = sorted(
        path.stem
        for path in receipt_root.glob("*.json")
        if path.is_file() and not path.is_symlink()
    )
    document = {
        "attempt_id": attempt_id,
        "intent_id": intent_id,
        "receipt_sha256": receipt_digests,
        "retry_effects_schema": "evolutionary-harness-retry-effects-v2",
    }
    destination = root / "state" / "retry-effects" / f"{attempt_id}.json"
    source = (canonical_json(document) + "\n").encode("ascii")
    if destination.exists():
        if destination.is_symlink() or destination.read_bytes() != source:
            raise ExperimentError("harness retry-effects receipt conflicts")
    else:
        atomic_write(destination, source)
    return hashlib.sha256(source).hexdigest()


def continue_experiment(
    root: Path, *, retry_reason: str | None = None
) -> dict[str, object]:
    root = root.expanduser().absolute()
    if not root.is_dir() or root.is_symlink():
        raise ExperimentError(f"experiment root is absent or unsafe: {root}")
    report_path = root / "experiment-report.json"
    if report_path.exists():
        if retry_reason is not None:
            raise ExperimentError("completed harness experiment cannot be retried")
        source = report_path.read_text(encoding="ascii")
        report = decode_json_object(source, ExperimentError)
        if source != canonical_json(report) + "\n":
            raise ExperimentError("harness experiment report is not canonical")
        verify_experiment(root)
        if report.get("assay") == "coding-agent-v1":
            advance_process_status(root, stage=3, run_kind="harness")
        return report
    runtime_path = root / "runtime.json"
    runtime = load_runtime_manifest(runtime_path)
    connector = str(runtime.model["connector"])
    agents = {
        "fixture-v1": "fixture",
        "pi-v1": "pi",
        "prime-agent-v1": "prime-agent",
    }
    if connector not in agents:
        raise ExperimentError("harness runtime connector is unsupported")
    agent = agents[connector]
    driver_path = root / "state" / "driver.jsonl"
    lines = driver_path.read_text(encoding="ascii").splitlines()
    if not lines:
        raise ExperimentError("harness Population Driver ledger is absent")
    header = decode_json_object(lines[0], ExperimentError)
    configuration = header.get("configuration")
    if type(configuration) is not dict:
        raise ExperimentError("harness Driver configuration is malformed")
    generation = configuration.get("generation")
    proposal = configuration.get("proposal")
    population_configuration = configuration.get("population")
    if (
        type(generation) is not dict
        or type(proposal) is not dict
        or type(proposal.get("context")) is not dict
        or type(population_configuration) is not dict
        or type(population_configuration.get("configuration")) is not dict
        or type(generation.get("tasks")) is not list
    ):
        raise ExperimentError("harness Driver configuration cannot be resumed")
    evaluation = generation.get("evaluation")
    if evaluation == "evolutionary-harness/development-coding-agent-v1":
        assay = "coding-agent-v1"
        evaluator_path = CODING_EVALUATOR
        advance_process_status(root, stage=2, run_kind="harness")
    elif evaluation == "evolutionary-harness/development-addition-v1":
        assay = "arithmetic-v1"
        evaluator_path = EVALUATOR
    else:
        raise ExperimentError("harness development assay is unsupported")
    development_tasks = cast(list[dict[str, object]], generation["tasks"])
    context = cast(dict[str, object], proposal["context"])
    objective = context.get("objective")
    population_name = cast(
        dict[str, object], population_configuration["configuration"]
    ).get("name")
    if type(objective) is not str or type(population_name) is not str:
        raise ExperimentError("harness Driver objective is malformed")
    population_state = load_state(population_root(root / "state"))
    seeds = [
        candidate_id
        for candidate_id, parents in population_state.candidate_parents.items()
        if not parents
    ]
    if len(seeds) != 1:
        raise ExperimentError("harness Population has no unique seed")
    artifact = cast(
        dict[str, object], population_state.candidates[seeds[0]]["artifact"]
    )
    proposal_command, executor_command = harness_commands(agent)
    request = harness_driver_request(
        artifact,
        proposal_command=proposal_command,
        tasks=development_tasks,
        runtime=runtime,
        evaluator_path=evaluator_path,
        evaluation=str(evaluation),
        objective=objective,
        population_name=population_name,
    )
    candidate = load_candidate(REFERENCE)
    candidate_paths = ["harness.json", *sorted(candidate.paths.values())]
    conformance_path = root / "conformance.json"
    conformance_source = conformance_path.read_text(encoding="ascii")
    conformance = decode_json_object(conformance_source, ExperimentError)
    if conformance_source != canonical_json(conformance) + "\n":
        raise ExperimentError("harness conformance receipt is not canonical")
    with _configured_environment(
        agent=agent,
        runtime_path=runtime_path,
        runtime=runtime,
        remote=root / "candidate.git",
        receipts=root / "receipts",
        runner_command=executor_command,
        candidate_paths=candidate_paths,
    ):
        if retry_reason is None:
            development = run_population_driver(canonical_json(request), root / "state")
        else:
            if not retry_reason.strip() or "\x00" in retry_reason:
                raise ExperimentError("retry reason must be non-empty text")
            pending_path = root / "state" / "pending" / "round-intent.json"
            pending_source = pending_path.read_text(encoding="ascii")
            pending = decode_json_object(pending_source, ExperimentError)
            if pending_source != canonical_json(pending) + "\n":
                raise ExperimentError("harness pending intent is not canonical")
            retry_effects_id = _record_harness_retry_effects(root, pending)
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
                root / "state",
            )
        return _finish_experiment(
            root,
            agent=agent,
            assay=assay,
            runtime=runtime,
            development=development,
            development_tasks=development_tasks,
            evaluator_path=evaluator_path,
            conformance=conformance,
        )
