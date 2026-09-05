"""Fixed harness experiment configuration, commands, and read-only allocation policy."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

from apps._support.wire import canonical_json, decode_json_object
from apps.harness.runtime_manifest import RuntimeManifest
from apps.population.contract import RESOURCE_NAMES, load_state
from apps.population_driver.paths import population_root

ROOT = Path(__file__).resolve().parents[2]


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


def load_assay_tasks(path: Path) -> list[dict[str, object]]:
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


def resource_budget(value: int = 10**12) -> dict[str, int]:
    return {name: value for name in RESOURCE_NAMES}


def harness_commands(agent: str) -> tuple[list[str], list[str]]:
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


def capability_first_draw(
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


def harness_driver_request(
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
            "max_total_candidate_cost": resource_budget(10**15),
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
                "budget": resource_budget(),
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


def expected_connector(agent: str) -> str:
    return {
        "fixture": "fixture-v1",
        "pi": "pi-v1",
        "prime-agent": "prime-agent-v1",
    }[agent]
