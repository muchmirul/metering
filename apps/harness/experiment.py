#!/usr/bin/env python3
"""One-command mutation-only Darwinian harness experiment and offline verifier."""

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
from apps.agent_protocol import (  # noqa: E402
    GIT_ARTIFACT_SCHEMA,
    decode_agent_artifact,
)
from apps.coding_agent.evaluator import evaluation_cost  # noqa: E402
from apps.coding_agent.process_tracker import (  # noqa: E402
    ProcessTrackerError,
    advance_process_status,
    load_process_status,
    process_document,
)
from apps.harness.conformance import run_conformance  # noqa: E402
from apps.harness.final_assay import FinalAssayError, run_final_assay  # noqa: E402
from apps.harness.harness_runner import EVIDENCE_KEY  # noqa: E402
from apps.harness.protocol import (  # noqa: E402
    HarnessProtocolError,
    load_candidate,
)
from apps.harness.receipts import (  # noqa: E402
    HarnessReceiptError,
    aggregate_cost,
    load_receipt,
    verify_receipt_binding,
)
from apps.harness.runtime_manifest import (  # noqa: E402
    RuntimeManifest,
    RuntimeManifestError,
    assert_candidate_compatible,
    load_runtime_manifest,
)
from apps.harness.workspace import (  # noqa: E402
    WorkspaceError,
    changed_paths,
    decode_files,
    files_digest,
    normalize_policy,
    require_allowed_changes,
)
from apps.population.contract import (  # noqa: E402
    RESOURCE_NAMES,
    PopulationState,
    load_state,
)
from apps.population_driver.paths import population_root  # noqa: E402
from apps.population_driver.population_driver_protocol import (  # noqa: E402
    PopulationDriverError,
)
from apps.population_driver.population_driver_state import read_receipt  # noqa: E402
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

REFERENCE = ROOT / "apps" / "harness" / "reference"
FIXTURES = ROOT / "apps" / "harness" / "fixtures"
CODING_FIXTURES = ROOT / "apps" / "coding_agent" / "fixtures"
PROFILES = ROOT / "apps" / "harness" / "profiles"
VALIDATE = ROOT / "apps" / "harness" / "validate_candidate.py"
GENERIC_RUNNER = ROOT / "apps" / "harness" / "harness_runner.py"
EVIDENCE = ROOT / "apps" / "harness" / "evidence_adapter.py"
GIT_ADAPTER = ROOT / "artifacts" / "git" / "git_candidate_adapter.py"
EVALUATOR = FIXTURES / "arithmetic_evaluator.py"
CODING_EVALUATOR = ROOT / "apps" / "coding_agent" / "evaluator.py"
FIXTURE_MODEL = FIXTURES / "fixture_model.py"
FIXTURE_PROPOSER = FIXTURES / "fixture_proposer.py"
DRIVER_SCHEMA_VERSION = 1


class ExperimentError(RuntimeError):
    """Raised when the reference composition cannot safely complete."""


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


def _tasks(path: Path) -> list[dict[str, object]]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ExperimentError(f"cannot read assay tasks: {exc}") from exc
    document = decode_json_object(source, ExperimentError)
    if source != canonical_json(document) + "\n" or set(document) != {"tasks"}:
        raise ExperimentError("assay task file is not canonical")
    tasks = document["tasks"]
    if (
        type(tasks) is not list
        or not tasks
        or any(type(item) is not dict for item in tasks)
    ):
        raise ExperimentError("assay task file is malformed")
    return cast(list[dict[str, object]], tasks)


def _budget(value: int = 10**12) -> dict[str, int]:
    return {name: value for name in RESOURCE_NAMES}


def _commands(agent: str) -> tuple[list[str], list[str]]:
    if agent == "fixture":
        return [sys.executable, str(FIXTURE_PROPOSER)], [
            sys.executable,
            str(GENERIC_RUNNER),
        ]
    directory = "pi" if agent == "pi" else "prime_agent"
    connector = ROOT / "connectors" / "fixed" / directory
    return (
        [sys.executable, str(connector / "harness_proposer.py")],
        [sys.executable, str(connector / "harness_runner.py")],
    )


def _capability_first_draw(
    state_root: Path,
    development_experiment_id: str,
    tie_draw: dict[str, int],
) -> tuple[str, dict[str, int], list[str], str]:
    state = load_state(population_root(state_root))
    archive_id = state.latest_archive_by_experiment.get(development_experiment_id)
    if archive_id is None:
        raise ExperimentError("coding harness development archive is absent")
    archive = cast(dict[str, object], state.record(archive_id)["body"])
    members = cast(list[dict[str, object]], archive["members"])
    if not members:
        raise ExperimentError("coding harness development archive is empty")
    best_rate = max(
        float(cast(dict[str, object], member["task"])["rate"]) for member in members
    )
    best_reliability = max(
        float(member["reliability"])
        for member in members
        if float(cast(dict[str, object], member["task"])["rate"]) == best_rate
    )
    finalists = sorted(
        str(member["candidate_id"])
        for member in members
        if float(cast(dict[str, object], member["task"])["rate"]) == best_rate
        and float(member["reliability"]) == best_reliability
    )
    index = (tie_draw["numerator"] * len(finalists)) // tie_draw["denominator"]
    selected = finalists[index]
    all_candidates = sorted(str(member["candidate_id"]) for member in members)
    return (
        selected,
        {
            "denominator": len(all_candidates),
            "numerator": all_candidates.index(selected),
        },
        finalists,
        archive_id,
    )


def _request(
    artifact: dict[str, object],
    *,
    proposal_command: list[str],
    tasks: list[dict[str, object]],
    runtime: RuntimeManifest,
    evaluator_path: Path = EVALUATOR,
    evaluation: str = "evolutionary-harness/development-addition-v1",
    objective: str = (
        "Mutate one typed harness locus so the external arithmetic assay solves "
        "left-plus-right tasks more reliably. Do not claim success."
    ),
    population_name: str = "reference-evolutionary-harness",
) -> dict[str, object]:
    evaluator = [sys.executable, str(evaluator_path)]
    return {
        "allocation_draws": [{"denominator": 1, "numerator": 0}],
        "evidence_adapter": {
            "command": [sys.executable, str(EVIDENCE)],
            "timeout_seconds": 60,
        },
        "generation": {
            "evaluation": evaluation,
            "evaluator": {"command": evaluator, "timeout_seconds": 30},
            "runner": {
                "command": [sys.executable, str(GIT_ADAPTER)],
                "timeout_seconds": 600,
            },
            "selection_policy": {
                "minimum_pass_improvement": 1,
                "reject_safety_regression": True,
                "type": "task-pass-count-v1",
            },
            "tasks": tasks,
        },
        "initial_parent_artifact": artifact,
        "limits": {
            "max_proposal_calls": 4,
            "max_rounds": 2,
            "max_total_candidate_cost": _budget(10**15),
            "max_wall_seconds": 100_000,
        },
        "population": {
            "configuration": {
                "archive_policy": {
                    "capacity": 8,
                    "reliability_kappa": 0,
                    "type": "pareto-uniform-v1",
                },
                "name": population_name,
            },
            "development": {
                "behavior_space": ["fail", "pass"],
                "budget": _budget(),
                "runtime_id": runtime.runtime_id,
            },
        },
        "proposal": {
            "command": proposal_command,
            "context": {
                "candidate_contract": "evolutionary-harness-v1",
                "model_identity": runtime.model,
                "objective": objective,
            },
            "timeout_seconds": 600,
        },
        "schema_version": DRIVER_SCHEMA_VERSION,
    }


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


def _expected_connector(agent: str) -> str:
    return {
        "fixture": "fixture-v1",
        "pi": "pi-v1",
        "prime-agent": "prime-agent-v1",
    }[agent]


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
        final_tasks = _tasks(CODING_FIXTURES / "final-tasks.json")
        selection_policy = {
            "policy": "development-task-rate-reliability-v1",
            "tie_draw": {"denominator": 1, "numerator": 0},
        }
        expected_final_candidate, final_draw, finalists, _ = _capability_first_draw(
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
        final_tasks = _tasks(FIXTURES / "final-tasks.json")
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
            budget=_budget(),
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
    if runtime.model["connector"] != _expected_connector(agent):
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
    proposal_command, executor_command = _commands(agent)
    receipts = root / "receipts"
    state = root / "state"
    if assay == "coding-agent-v1":
        development_tasks = _tasks(CODING_FIXTURES / "development-tasks.json")
        evaluator_path = CODING_EVALUATOR
        evaluation = "evolutionary-harness/development-coding-agent-v1"
        objective = (
            "Mutate exactly one typed Pi harness locus so independent sandboxed "
            "coding assays pass more cases. Preserve the action protocol and use the "
            "fixed coding workspace helpers. Do not edit tasks or claim success."
        )
        population_name = "coding-agent-harness-evolution"
    else:
        development_tasks = _tasks(FIXTURES / "development-tasks.json")
        evaluator_path = EVALUATOR
        evaluation = "evolutionary-harness/development-addition-v1"
        objective = (
            "Mutate one typed harness locus so the external arithmetic assay solves "
            "left-plus-right tasks more reliably. Do not claim success."
        )
        population_name = "reference-evolutionary-harness"
    request = _request(
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
    proposal_command, executor_command = _commands(agent)
    request = _request(
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


def _run_receipt_binding(
    run: object,
    *,
    receipt_root: Path,
    runtime: RuntimeManifest,
    manifests: dict[str, str],
) -> str:
    if type(run) is not dict:
        raise ExperimentError("Controller harness run is malformed")
    candidate_id = run.get("candidate_id")
    task = run.get("task")
    forecast = run.get("forecast")
    runner = run.get("runner")
    if (
        type(candidate_id) is not str
        or candidate_id not in manifests
        or type(task) is not dict
        or type(forecast) is not dict
        or set(forecast) != {"entropy", "outcomes"}
        or type(runner) is not dict
    ):
        raise ExperimentError("Controller harness run is incomplete")
    submission = runner.get("submission")
    if type(submission) is not dict:
        raise ExperimentError("Controller harness submission is malformed")
    metadata = submission.get(EVIDENCE_KEY)
    if type(metadata) is not dict or set(metadata) != {
        "manifest_id",
        "receipt",
        "runtime_id",
    }:
        raise ExperimentError("Controller harness receipt metadata is malformed")
    if (
        metadata["manifest_id"] != manifests[candidate_id]
        or metadata["runtime_id"] != runtime.runtime_id
        or type(metadata["receipt"]) is not dict
    ):
        raise ExperimentError("Controller harness metadata changed identity")
    case_id = task.get("case_id")
    task_input = task.get("input")
    if type(case_id) is not str or type(task_input) is not dict:
        raise ExperimentError("Controller harness task is malformed")
    reference = cast(dict[str, object], metadata["receipt"])
    receipt = load_receipt(reference, receipt_root)
    clean_submission = {
        name: value for name, value in submission.items() if name != EVIDENCE_KEY
    }
    verify_receipt_binding(
        receipt,
        candidate_id=candidate_id,
        case_id=case_id,
        task=task_input,
        manifest_id=manifests[candidate_id],
        runtime=runtime,
        forecast={"outcomes": forecast["outcomes"]},
        submission=clean_submission,
    )
    digest = reference.get("sha256")
    if type(digest) is not str:
        raise ExperimentError("Controller harness receipt digest is malformed")
    return digest


def _load_bundle(
    reference: object, receipt_root: Path
) -> tuple[dict[str, object], str]:
    if type(reference) is not dict or set(reference) != {"sha256", "uri"}:
        raise ExperimentError("final assay receipt reference is malformed")
    digest = reference["sha256"]
    if (
        type(digest) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ExperimentError("final assay receipt digest is malformed")
    path = receipt_root / f"{digest}.json"
    if reference["uri"] != path.as_uri() or path.is_symlink() or not path.is_file():
        raise ExperimentError("final assay receipt path is unsafe")
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != digest:
        raise ExperimentError("final assay receipt digest does not match")
    try:
        text = source.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ExperimentError("final assay receipt must be ASCII JSON") from exc
    document = decode_json_object(text, ExperimentError)
    if text != canonical_json(document) + "\n":
        raise ExperimentError("final assay receipt is not canonical")
    return document, digest


def _verify_coding_kernel_evidence(
    evidence: object,
    *,
    task: dict[str, object],
    submission: dict[str, object],
    runtime: RuntimeManifest,
) -> tuple[bool, bool]:
    if type(evidence) is not dict or set(evidence) != {
        "assay_sha256",
        "cost",
        "isolation_enforced",
        "kernel_observations",
        "returncode",
        "runtime_id",
        "stderr_sha256",
        "stdout_sha256",
        "timed_out",
        "workspace_sha256",
    }:
        raise ExperimentError("coding evaluator evidence is malformed")
    task_input = task.get("input")
    workspace = submission.get("_metering_coding_workspace")
    if (
        type(task_input) is not dict
        or type(task_input.get("assay")) is not dict
        or type(task_input.get("workspace")) is not dict
        or type(workspace) is not dict
    ):
        raise ExperimentError("coding evaluator workspace binding is malformed")
    task_workspace = cast(dict[str, object], task_input["workspace"])
    try:
        policy = normalize_policy(task_workspace["policy"])
        base_files = decode_files(
            task_workspace["files"],
            max_files=int(policy["max_files"]),
            max_bytes=int(policy["max_bytes"]),
        )
        files = decode_files(
            workspace["files"],
            max_files=int(policy["max_files"]),
            max_bytes=int(policy["max_bytes"]),
        )
        paths = changed_paths(base_files, files)
        require_allowed_changes(paths, cast(list[str], policy["allowed_write_paths"]))
    except (KeyError, TypeError, WorkspaceError) as exc:
        raise ExperimentError("coding evaluator workspace does not replay") from exc
    body = {"changed_paths": paths, "files": files}
    if (
        set(workspace) != {"base_sha256", "changed_paths", "files", "sha256"}
        or workspace["base_sha256"] != files_digest(base_files)
        or workspace["changed_paths"] != paths
        or workspace["sha256"] != canonical_digest(body)
        or evidence["workspace_sha256"] != files_digest(files)
        or evidence["assay_sha256"] != canonical_digest(task_input["assay"])
        or evidence["runtime_id"] != runtime.runtime_id
        or evidence["isolation_enforced"] is not runtime.isolation_enforced
    ):
        raise ExperimentError("coding evaluator evidence changed identity")
    returncode = evidence["returncode"]
    if (
        (returncode is not None and type(returncode) is not int)
        or type(evidence["timed_out"]) is not bool
        or type(evidence["stderr_sha256"]) is not str
        or type(evidence["stdout_sha256"]) is not str
        or any(
            len(cast(str, evidence[name])) != 64
            or any(
                character not in "0123456789abcdef"
                for character in cast(str, evidence[name])
            )
            for name in ("stderr_sha256", "stdout_sha256")
        )
    ):
        raise ExperimentError("coding evaluator execution evidence is malformed")
    observations = evidence["kernel_observations"]
    expected_keys = {
        "cpu_microseconds",
        "memory_peak_bytes",
        "processes_peak",
        "source",
        "storage_write_bytes",
        "wall_milliseconds",
    }
    if type(observations) is not list or not observations:
        raise ExperimentError("coding evaluator omitted kernel observations")
    for observation in observations:
        if type(observation) is not dict or set(observation) != expected_keys:
            raise ExperimentError("coding evaluator kernel observation is malformed")
        for name in (
            "cpu_microseconds",
            "memory_peak_bytes",
            "processes_peak",
            "storage_write_bytes",
            "wall_milliseconds",
        ):
            value = observation[name]
            if value is not None and (type(value) is not int or value < 0):
                raise ExperimentError(
                    "coding evaluator kernel observation is malformed"
                )
        if (
            type(observation["wall_milliseconds"]) is not int
            or type(observation["source"]) is not str
            or not observation["source"]
        ):
            raise ExperimentError("coding evaluator kernel observation is malformed")
        if runtime.isolation_enforced:
            required = {
                "cpu": "cpu_microseconds",
                "memory": "memory_peak_bytes",
                "processes": "processes_peak",
                "storage": "storage_write_bytes",
                "wall": "wall_milliseconds",
            }
            if observation["source"] != "cgroup-v2" or any(
                observation[required[name]] is None
                for name in runtime.required_observations
            ):
                raise ExperimentError(
                    "coding evaluator omitted required isolation observations"
                )
    if evidence["cost"] != evaluation_cost(
        cast(list[dict[str, object]], observations), runtime
    ):
        raise ExperimentError("coding evaluator cost does not replay")
    passed = returncode == 0 and evidence["timed_out"] is False
    safety_passed = (
        evidence["isolation_enforced"] is True if runtime.isolation_enforced else True
    )
    return passed, safety_passed


def _verify_coding_observer_trace(
    trace: dict[str, object], runtime: RuntimeManifest
) -> None:
    task = trace.get("task")
    observer = trace.get("observer_evaluation")
    if type(task) is not dict or type(observer) is not dict:
        raise ExperimentError("coding Controller trace omitted evaluator evidence")
    results = observer.get("results")
    if type(results) is not list:
        raise ExperimentError("coding Controller evaluator results are malformed")
    by_candidate = {
        item.get("candidate_id"): item for item in results if type(item) is dict
    }
    for name in ("incumbent_run", "challenger_run"):
        run = trace.get(name)
        if type(run) is not dict or type(run.get("runner")) is not dict:
            raise ExperimentError("coding Controller run is malformed")
        candidate_id = run.get("candidate_id")
        submission = cast(dict[str, object], run["runner"]).get("submission")
        result = by_candidate.get(candidate_id)
        if type(submission) is not dict or type(result) is not dict:
            raise ExperimentError("coding evaluator candidate result is absent")
        passed, safety_passed = _verify_coding_kernel_evidence(
            result.get("evidence"),
            task=task,
            submission=submission,
            runtime=runtime,
        )
        if (
            set(result)
            != {"candidate_id", "evidence", "outcome", "passed", "safety_passed"}
            or result["passed"] is not passed
            or result["safety_passed"] is not safety_passed
            or result["outcome"] != ("pass" if passed else "fail")
        ):
            raise ExperimentError("coding evaluator result does not replay")


def _verify_receipts(
    root: Path,
    runtime: RuntimeManifest,
    state: PopulationState,
    manifests: dict[str, str],
    final_run: dict[str, object],
    *,
    development_tasks: list[dict[str, object]],
    final_tasks: list[dict[str, object]],
    verify_coding_evidence: bool,
) -> tuple[int, int]:
    receipt_root = root / "receipts"
    if not receipt_root.is_dir() or receipt_root.is_symlink():
        raise ExperimentError("harness receipt directory is absent or unsafe")
    expected_run_digests: list[str] = []
    driver_path = root / "state" / "driver.jsonl"
    driver_lines = driver_path.read_text(encoding="utf-8").splitlines()
    if not driver_lines:
        raise ExperimentError("Population Driver ledger is empty")
    header = decode_json_object(driver_lines[0], ExperimentError)
    configuration = header.get("configuration")
    if type(configuration) is not dict:
        raise ExperimentError("Population Driver configuration is malformed")
    generation = configuration.get("generation")
    population = configuration.get("population")
    if (
        type(generation) is not dict
        or generation.get("tasks") != development_tasks
        or type(population) is not dict
        or type(population.get("experiment")) is not dict
    ):
        raise ExperimentError("reference development task set does not replay")
    development_experiment = cast(dict[str, object], population["experiment"])
    expected_development_task_set = canonical_digest(
        {
            "evaluation": generation["evaluation"],
            "task_set_schema": "population-driver-task-set-v1",
            "tasks": development_tasks,
        }
    )
    if (
        development_experiment.get("task_set_id") != expected_development_task_set
        or development_experiment.get("runtime_id") != runtime.runtime_id
        or development_experiment.get("role") != "development"
    ):
        raise ExperimentError("reference development experiment identity changed")
    expected_retry_effects: dict[str, tuple[str, str]] = {}
    for line in driver_lines[1:]:
        record = decode_json_object(line, ExperimentError)
        attempts = record.get("attempts")
        intent_id = record.get("intent_id")
        if type(attempts) is not list or type(intent_id) is not str:
            raise ExperimentError("Driver round attempts are malformed")
        for index, attempt in enumerate(attempts[:-1]):
            next_attempt = attempts[index + 1]
            if (
                type(attempt) is not dict
                or type(attempt.get("attempt_id")) is not str
                or type(next_attempt) is not dict
                or type(next_attempt.get("reason")) is not str
            ):
                raise ExperimentError("Driver retry attempt is malformed")
            expected_retry_effects[str(attempt["attempt_id"])] = (
                intent_id,
                str(next_attempt["reason"]),
            )
        controller = read_receipt(root / "state", record.get("controller_receipt"))
        result = controller.get("controller_result")
        if type(result) is not dict or type(result.get("cases")) is not list:
            raise ExperimentError("Controller receipt omitted case traces")
        for trace in result["cases"]:
            if type(trace) is not dict:
                raise ExperimentError("Controller case trace is malformed")
            for name in ("incumbent_run", "challenger_run"):
                expected_run_digests.append(
                    _run_receipt_binding(
                        trace.get(name),
                        receipt_root=receipt_root,
                        runtime=runtime,
                        manifests=manifests,
                    )
                )
            if verify_coding_evidence:
                _verify_coding_observer_trace(trace, runtime)

    run = cast(dict[str, object], final_run["run"])
    evidence = cast(dict[str, object], final_run["evidence"])
    bundle, bundle_digest = _load_bundle(evidence.get("evidence_receipt"), receipt_root)
    if set(bundle) != {
        "allocation_record_id",
        "candidate_id",
        "cases",
        "evaluator_id",
        "final_assay_schema",
        "runtime_id",
    }:
        raise ExperimentError("final assay receipt has the wrong keys")
    if (
        bundle["final_assay_schema"] != "evolutionary-harness-final-assay-v1"
        or bundle["runtime_id"] != runtime.runtime_id
        or bundle["candidate_id"] != run["candidate_id"]
        or bundle["allocation_record_id"]
        != cast(dict[str, object], run["seed"])["allocation_record_id"]
    ):
        raise ExperimentError("final assay receipt changed sealed identities")
    allocation_id = bundle["allocation_record_id"]
    if type(allocation_id) is not str:
        raise ExperimentError("final allocation identity is malformed")
    allocation_record = state.record(allocation_id)
    if allocation_record is None:
        raise ExperimentError("final allocation record is absent")
    allocation_body = cast(dict[str, object], allocation_record["body"])
    allocation_request = cast(dict[str, object], allocation_body["request"])
    archive_record = state.record(str(allocation_request["archive_record_id"]))
    if archive_record is None:
        raise ExperimentError("final allocation archive is absent")
    trailing_allocations = [
        record_id
        for record_id, _ in state.allocations
        if int(cast(dict[str, object], state.record(record_id))["sequence"])
        > int(archive_record["sequence"])
    ]
    if trailing_allocations != [allocation_id]:
        raise ExperimentError("final allocation is not the unique sealed allocation")
    tasks = final_tasks
    experiment = state.experiments[str(run["experiment_id"])]
    expected_task_set = canonical_digest(
        {"task_set_schema": "protected-harness-final-v1", "tasks": tasks}
    )
    if (
        experiment["task_set_id"] != expected_task_set
        or experiment["case_count"] != len(tasks)
        or bundle["evaluator_id"] != experiment["evaluator_id"]
    ):
        raise ExperimentError("final assay experiment identity does not replay")
    cases = bundle["cases"]
    if type(cases) is not list or len(cases) != len(tasks):
        raise ExperimentError("final assay receipt cases are malformed")
    final_receipts: list[dict[str, object]] = []
    for case, task in zip(cases, tasks, strict=True):
        expected_keys = {
            "case_id",
            "evidence",
            "forecast",
            "outcome",
            "passed",
            "receipt",
            "result_sha256",
            "safety_passed",
            "submission",
            "target_probability",
        }
        if type(case) is not dict or set(case) != expected_keys:
            raise ExperimentError("final assay case is malformed")
        if case["case_id"] != task.get("case_id") or type(case["receipt"]) is not dict:
            raise ExperimentError("final assay case changed task identity")
        receipt = load_receipt(case["receipt"], receipt_root)
        task_input = task.get("input")
        if type(task_input) is not dict:
            raise ExperimentError("protected final task is malformed")
        candidate_id = str(run["candidate_id"])
        verify_receipt_binding(
            receipt,
            candidate_id=candidate_id,
            case_id=str(task["case_id"]),
            task=task_input,
            manifest_id=manifests[candidate_id],
            runtime=runtime,
            forecast=case["forecast"],
            submission=case["submission"],
        )
        if verify_coding_evidence:
            passed_result, safety_result = _verify_coding_kernel_evidence(
                case["evidence"],
                task=task,
                submission=cast(dict[str, object], case["submission"]),
                runtime=runtime,
            )
            if (
                case["passed"] is not passed_result
                or case["safety_passed"] is not safety_result
                or case["outcome"] != ("pass" if passed_result else "fail")
            ):
                raise ExperimentError("final coding evaluator result does not replay")
        completion = cast(dict[str, object], receipt["completion"])
        if case["result_sha256"] != completion["result_sha256"]:
            raise ExperimentError("final assay result digest does not match its run")
        forecast = case["forecast"]
        if type(forecast) is not dict or type(forecast.get("outcomes")) is not list:
            raise ExperimentError("final assay forecast is malformed")
        probabilities = {
            item.get("outcome"): item.get("probability")
            for item in forecast["outcomes"]
            if type(item) is dict
        }
        if probabilities.get(case["outcome"]) != case["target_probability"]:
            raise ExperimentError("final assay target probability does not replay")
        digest = cast(dict[str, object], case["receipt"]).get("sha256")
        if type(digest) is not str:
            raise ExperimentError("final assay run receipt digest is malformed")
        expected_run_digests.append(digest)
        final_receipts.append(receipt)
    passed = sum(int(case["passed"] is True) for case in cases)
    safety_failures = sum(int(case["safety_passed"] is not True) for case in cases)
    final_cost = aggregate_cost(final_receipts)
    for case in cases:
        case_evidence = cast(dict[str, object], case["evidence"])
        evaluator_cost = case_evidence.get("cost")
        if evaluator_cost is None:
            continue
        if type(evaluator_cost) is not dict or set(evaluator_cost) != set(
            RESOURCE_NAMES
        ):
            raise ExperimentError("final evaluator cost is malformed")
        for name in RESOURCE_NAMES:
            value = evaluator_cost[name]
            if type(value) is not int or value < 0:
                raise ExperimentError("final evaluator cost is malformed")
            final_cost[name] += value
    expected_evidence = {
        "behavior_distribution": [1.0 - passed / len(cases), passed / len(cases)],
        "cost": final_cost,
        "evidence_receipt": evidence["evidence_receipt"],
        "information_model": None,
        "protected_passed": safety_failures == 0,
        "target_probabilities": [case["target_probability"] for case in cases],
        "task": {
            "case_count": len(cases),
            "passed_count": passed,
            "safety_failures": safety_failures,
        },
    }
    if evidence != expected_evidence:
        raise ExperimentError("final Population evidence does not replay from receipts")

    actual_run_digests: set[str] = set()
    actual_bundle_digests: set[str] = set()
    entries = sorted(receipt_root.iterdir())
    for path in entries:
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise ExperimentError("harness receipt directory contains an unsafe entry")
        source = path.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        if path.name != f"{digest}.json":
            raise ExperimentError("harness receipt filename does not match content")
        document = decode_json_object(source.decode("ascii"), ExperimentError)
        if source.decode("ascii") != canonical_json(document) + "\n":
            raise ExperimentError("harness receipt is not canonical")
        if document.get("receipt_schema") == "evolutionary-harness-run-receipt-v1":
            load_receipt({"sha256": digest, "uri": path.as_uri()}, receipt_root)
            actual_run_digests.add(digest)
        elif (
            document.get("final_assay_schema") == "evolutionary-harness-final-assay-v1"
        ):
            actual_bundle_digests.add(digest)
        else:
            raise ExperimentError("unknown harness receipt schema")
    retry_root = root / "state" / "retry-effects"
    retry_receipts: set[str] = set()
    actual_retry_ids: set[str] = set()
    if retry_root.exists():
        if retry_root.is_symlink() or not retry_root.is_dir():
            raise ExperimentError("harness retry-effects directory is unsafe")
        for path in sorted(retry_root.iterdir()):
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ExperimentError("harness retry-effects entry is unsafe")
            source = path.read_text(encoding="ascii")
            document = decode_json_object(source, ExperimentError)
            if source != canonical_json(document) + "\n" or set(document) != {
                "attempt_id",
                "intent_id",
                "receipt_sha256",
                "retry_effects_schema",
            }:
                raise ExperimentError("harness retry-effects receipt is malformed")
            attempt_id = document["attempt_id"]
            digests = document["receipt_sha256"]
            schema = document["retry_effects_schema"]
            expected_identity = expected_retry_effects.get(cast(str, attempt_id))
            if (
                type(schema) is not str
                or schema
                not in {
                    "evolutionary-harness-retry-effects-v1",
                    "evolutionary-harness-retry-effects-v2",
                }
                or type(attempt_id) is not str
                or path.name != f"{attempt_id}.json"
                or expected_identity is None
                or expected_identity[0] != document["intent_id"]
                or type(digests) is not list
                or digests != sorted(set(digests))
                or any(
                    type(digest) is not str
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                    for digest in digests
                )
            ):
                raise ExperimentError("harness retry-effects identity is malformed")
            marker = "\nretry-effects-sha256:"
            if schema == "evolutionary-harness-retry-effects-v2":
                receipt_id = hashlib.sha256(source.encode("ascii")).hexdigest()
                suffix = f"{marker}{receipt_id}"
                if (
                    not expected_identity[1].endswith(suffix)
                    or not expected_identity[1][: -len(suffix)].strip()
                ):
                    raise ExperimentError(
                        "harness retry-effects receipt is not bound to retry"
                    )
            elif marker in expected_identity[1]:
                raise ExperimentError("harness retry-effects schema was downgraded")
            actual_retry_ids.add(attempt_id)
            retry_receipts.update(cast(list[str], digests))
    if actual_retry_ids != set(expected_retry_effects):
        raise ExperimentError("harness retry-effects receipt set is incomplete")
    if not retry_receipts <= actual_run_digests:
        raise ExperimentError("harness retry-effects reference unknown receipts")
    if actual_run_digests != set(expected_run_digests) | retry_receipts:
        raise ExperimentError(
            "harness run receipt set does not match authenticated or retry effects"
        )
    if actual_bundle_digests != {bundle_digest}:
        raise ExperimentError("final assay receipt set does not match Population")
    return len(actual_run_digests), len(actual_bundle_digests)


def _verify_conformance(
    root: Path, runtime: RuntimeManifest, manifests: dict[str, str]
) -> None:
    path = root / "conformance.json"
    if path.is_symlink() or not path.is_file():
        raise ExperimentError("kernel conformance receipt is absent or unsafe")
    source = path.read_text(encoding="utf-8")
    document = decode_json_object(source, ExperimentError)
    if source != canonical_json(document) + "\n" or set(document) != {
        "candidate_manifest_id",
        "checks",
        "conformance_id",
        "isolation_enforced",
        "resources",
        "runtime_id",
        "schema",
    }:
        raise ExperimentError("kernel conformance receipt is malformed")
    body = {name: value for name, value in document.items() if name != "conformance_id"}
    if (
        document["conformance_id"] != canonical_digest(body)
        or document["schema"] != "evolutionary-harness-conformance-v1"
        or document["runtime_id"] != runtime.runtime_id
        or document["candidate_manifest_id"] not in set(manifests.values())
        or document["isolation_enforced"] is not runtime.isolation_enforced
        or document["checks"]
        != [
            "boot",
            "execute",
            "snapshot",
            "restore",
            "interrupt",
            "timeout",
            "cleanup",
            "shutdown",
        ]
        or type(document["resources"]) is not list
        or not document["resources"]
    ):
        raise ExperimentError("kernel conformance receipt does not replay")


def _verification_tasks(
    root: Path,
) -> tuple[
    str,
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object] | None,
]:
    path = root / "assay.json"
    if not path.exists():
        return (
            "arithmetic-v1",
            _tasks(FIXTURES / "development-tasks.json"),
            _tasks(FIXTURES / "final-tasks.json"),
            None,
        )
    if path.is_symlink() or not path.is_file():
        raise ExperimentError("coding assay manifest is unsafe")
    source = path.read_text(encoding="ascii")
    document = decode_json_object(source, ExperimentError)
    legacy_keys = {
        "assay_schema",
        "development_tasks",
        "final_tasks",
        "schema_version",
    }
    current_keys = {*legacy_keys, "final_selection"}
    keys = set(document)
    if source != canonical_json(document) + "\n" or (
        keys != legacy_keys and keys != current_keys
    ):
        raise ExperimentError("coding assay manifest is malformed")
    if (
        document["assay_schema"] != "coding-agent-assay-v1"
        or document["schema_version"] != 1
    ):
        raise ExperimentError("coding assay manifest version is unsupported")
    development = document["development_tasks"]
    final = document["final_tasks"]
    if (
        type(development) is not list
        or not development
        or any(type(item) is not dict for item in development)
        or type(final) is not list
        or not final
        or any(type(item) is not dict for item in final)
    ):
        raise ExperimentError("coding assay task sets are malformed")
    selection = document.get("final_selection")
    if selection is not None and selection != {
        "policy": "development-task-rate-reliability-v1",
        "tie_draw": {"denominator": 1, "numerator": 0},
    }:
        raise ExperimentError("coding assay final selection policy is malformed")
    return (
        "coding-agent-v1",
        cast(list[dict[str, object]], development),
        cast(list[dict[str, object]], final),
        cast(dict[str, object] | None, selection),
    )


def verify_experiment(root: Path) -> dict[str, object]:
    root = root.expanduser().absolute()
    assay, development_tasks, final_tasks, final_selection = _verification_tasks(root)
    runtime = load_runtime_manifest(root / "runtime.json")
    driver = verify_population_driver(root / "state")
    state = load_state(population_root(root / "state"))
    if not state.final_evaluation_started:
        raise ExperimentError("Population is not sealed by final evidence")
    final_runs = [
        body
        for body in state.runs
        if state.experiments[
            str(cast(dict[str, object], body["run"])["experiment_id"])
        ]["role"]
        == "final"
    ]
    if len(final_runs) != 1:
        raise ExperimentError("experiment must contain exactly one final run")
    expected_repository = str((root / "candidate.git").absolute())
    manifests: dict[str, str] = {}
    old_repository = os.environ.get("METERING_GIT_REPOSITORY")
    try:
        os.environ["METERING_GIT_REPOSITORY"] = expected_repository
        with tempfile.TemporaryDirectory(
            prefix="metering-harness-verify-"
        ) as temporary:
            temporary_root = Path(temporary)
            for index, candidate in enumerate(state.candidates.values()):
                candidate_id = str(candidate["candidate_id"])
                artifact = cast(dict[str, object], candidate["artifact"])
                if artifact.get("repository") != expected_repository:
                    raise ExperimentError("candidate identifies another Git repository")
                checkout = temporary_root / str(index)
                clone_verified(artifact, checkout)
                loaded = load_candidate(
                    checkout, entrypoint=str(artifact["entrypoint"])
                )
                assert_candidate_compatible(
                    runtime,
                    (checkout / loaded.paths["dependency_lock"]).read_bytes(),
                )
                manifests[candidate_id] = loaded.manifest_id
    finally:
        if old_repository is None:
            os.environ.pop("METERING_GIT_REPOSITORY", None)
        else:
            os.environ["METERING_GIT_REPOSITORY"] = old_repository
    if final_selection is not None:
        tie_draw = cast(dict[str, int], final_selection["tie_draw"])
        expected_candidate, allocation_draw, _finalists, archive_id = (
            _capability_first_draw(
                root / "state", str(driver["experiment_id"]), tie_draw
            )
        )
        final_run_record = cast(dict[str, object], final_runs[0]["run"])
        seed = final_run_record["seed"]
        if type(seed) is not dict:
            raise ExperimentError("coding harness final seed is malformed")
        allocation_id = seed.get("allocation_record_id")
        if (
            final_run_record["candidate_id"] != expected_candidate
            or seed.get("draw") != allocation_draw
            or type(allocation_id) is not str
        ):
            raise ExperimentError("coding harness final selection does not replay")
        allocation = cast(dict[str, object], state.record(allocation_id)["body"])
        request = cast(dict[str, object], allocation["request"])
        result = cast(dict[str, object], allocation["result"])
        if (
            request.get("archive_record_id") != archive_id
            or request.get("draw") != allocation_draw
            or result.get("selected_candidate_id") != expected_candidate
        ):
            raise ExperimentError("coding harness allocation does not replay")
    if assay == "coding-agent-v1":
        descriptor_path = root / "selected-harness.json"
        if descriptor_path.is_symlink() or not descriptor_path.is_file():
            raise ExperimentError("selected harness descriptor is absent or unsafe")
        descriptor_source = descriptor_path.read_text(encoding="ascii")
        descriptor = decode_json_object(descriptor_source, ExperimentError)
        common_keys = {
            "artifact",
            "candidate_id",
            "descriptor_schema",
            "manifest_id",
            "runtime_id",
        }
        expected_keys = (
            {*common_keys, "provenance"} if final_selection is not None else common_keys
        )
        if (
            descriptor_source != canonical_json(descriptor) + "\n"
            or set(descriptor) != expected_keys
        ):
            raise ExperimentError("selected harness descriptor is malformed")
        candidate_id = descriptor["candidate_id"]
        final_body = cast(dict[str, object], final_runs[0])
        final_run = cast(dict[str, object], final_body["run"])
        final_evidence = cast(dict[str, object], final_body["evidence"])
        expected_schema = (
            "selected-evolutionary-harness-v2"
            if final_selection is not None
            else "selected-evolutionary-harness-v1"
        )
        expected_provenance = None
        if final_selection is not None:
            assay_document = {
                "assay_schema": "coding-agent-assay-v1",
                "development_tasks": development_tasks,
                "final_selection": final_selection,
                "final_tasks": final_tasks,
                "schema_version": 1,
            }
            reference = cast(dict[str, object], final_evidence["evidence_receipt"])
            expected_provenance = {
                "assay_id": canonical_digest(assay_document),
                "development_experiment_id": driver["experiment_id"],
                "final_allocation_record_id": cast(
                    dict[str, object], final_run["seed"]
                )["allocation_record_id"],
                "final_passed_count": cast(dict[str, object], final_evidence["task"])[
                    "passed_count"
                ],
                "final_receipt_sha256": reference["sha256"],
                "final_run_record_id": state.run_record_ids[str(final_run["run_id"])],
                "final_safety_failures": cast(
                    dict[str, object], final_evidence["task"]
                )["safety_failures"],
                "final_task_count": cast(dict[str, object], final_evidence["task"])[
                    "case_count"
                ],
                "population_head_record_id": state.head_id,
            }
        if (
            descriptor["descriptor_schema"] != expected_schema
            or descriptor["runtime_id"] != runtime.runtime_id
            or type(candidate_id) is not str
            or candidate_id not in state.candidates
            or descriptor["artifact"] != state.candidates[candidate_id]["artifact"]
            or descriptor["manifest_id"] != manifests.get(candidate_id)
            or (
                final_selection is not None
                and descriptor["provenance"] != expected_provenance
            )
        ):
            raise ExperimentError("selected harness descriptor changed identity")
    _verify_conformance(root, runtime, manifests)
    run_receipts, bundles = _verify_receipts(
        root,
        runtime,
        state,
        manifests,
        cast(dict[str, object], final_runs[0]),
        development_tasks=development_tasks,
        final_tasks=final_tasks,
        verify_coding_evidence=final_selection is not None,
    )
    if run_receipts < 1 or bundles != 1:
        raise ExperimentError("experiment receipt set is incomplete")
    return {
        "assay": assay,
        "candidate_count": len(state.candidates),
        "driver": driver,
        "final_run_count": len(final_runs),
        "harness_receipt_count": run_receipts,
        "runtime_id": runtime.runtime_id,
        "schema": "evolutionary-harness-verification-v1",
        "status": "verified",
    }


def harness_process_status(root: Path) -> dict[str, object]:
    root = root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise ExperimentError(f"experiment root is absent or unsafe: {root}")
    status = load_process_status(root, expected_run_kind="harness")
    if status is not None:
        return status
    if (root / "selected-harness.json").is_file():
        return process_document(3, "harness")
    driver_path = root / "state" / "driver.jsonl"
    if driver_path.is_file():
        lines = driver_path.read_text(encoding="ascii").splitlines()
        header = decode_json_object(lines[0] if lines else "", ExperimentError)
        configuration = header.get("configuration")
        generation = (
            configuration.get("generation") if type(configuration) is dict else None
        )
        if (
            type(generation) is dict
            and generation.get("evaluation")
            == "evolutionary-harness/development-coding-agent-v1"
        ):
            return process_document(2, "harness")
    raise ExperimentError("coding harness process has not started")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(arguments) == 2 and arguments[0] == "verify":
            result = verify_experiment(Path(arguments[1]))
        elif len(arguments) == 2 and arguments[0] == "status":
            result = harness_process_status(Path(arguments[1]))
        elif len(arguments) == 2 and arguments[0] == "resume":
            result = continue_experiment(Path(arguments[1]))
        elif len(arguments) == 3 and arguments[0] == "retry":
            result = continue_experiment(Path(arguments[1]), retry_reason=arguments[2])
        elif len(arguments) == 2 and arguments[0] in {"fixture", "coding-fixture"}:
            result = run_experiment(
                "fixture",
                Path(arguments[1]).absolute(),
                None,
                assay=(
                    "coding-agent-v1"
                    if arguments[0] == "coding-fixture"
                    else "arithmetic-v1"
                ),
            )
        elif len(arguments) == 3 and arguments[0] in {
            "pi",
            "prime-agent",
            "coding-pi",
            "coding-prime-agent",
        }:
            selected_agent = arguments[0].removeprefix("coding-")
            result = run_experiment(
                selected_agent,
                Path(arguments[1]).absolute(),
                Path(arguments[2]),
                assay=(
                    "coding-agent-v1"
                    if arguments[0].startswith("coding-")
                    else "arithmetic-v1"
                ),
            )
        else:
            raise ExperimentError(
                "usage: experiment.py {fixture|coding-fixture} NEW_ROOT | "
                "{pi|prime-agent|coding-pi|coding-prime-agent} NEW_ROOT "
                "RUNTIME.json | status ROOT | resume ROOT | retry ROOT REASON | "
                "verify ROOT"
            )
    except (
        ExperimentError,
        FinalAssayError,
        GitCandidateError,
        HarnessProtocolError,
        HarnessReceiptError,
        OSError,
        ProcessTrackerError,
        PopulationDriverError,
        RuntimeManifestError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    write_document(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
