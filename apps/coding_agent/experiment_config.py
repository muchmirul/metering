"""Fixed solution experiment commands, resource budgets, and request identity."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import cast

from apps._support.wire import canonical_digest
from apps.coding_agent.protocol import task_documents
from apps.harness.runtime_manifest import RuntimeManifest
from apps.population.contract import RESOURCE_NAMES

ROOT = Path(__file__).resolve().parents[2]


GIT_ADAPTER = ROOT / "artifacts" / "git" / "git_candidate_adapter.py"


RUNNER = ROOT / "apps" / "coding_agent" / "candidate_runner.py"


EVALUATOR = ROOT / "apps" / "coding_agent" / "solution_evaluator.py"


EVIDENCE = ROOT / "apps" / "coding_agent" / "evidence_adapter.py"


VALIDATE = ROOT / "apps" / "coding_agent" / "validate_solution.py"


def control_python_executable() -> str:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    candidate = Path(sys.prefix) / relative
    try:
        if candidate.is_file() and candidate.resolve(strict=True) == Path(
            sys.executable
        ).resolve(strict=True):
            return str(candidate.absolute())
    except OSError:
        pass
    return sys.executable


def control_command(script: Path) -> list[str]:
    return [control_python_executable(), str(script)]


class SolutionExperimentError(RuntimeError):
    """Raised when a coding experiment cannot complete or replay safely."""


def resource_budget(value: int = 10**15) -> dict[str, int]:
    return {name: value for name in RESOURCE_NAMES}


def task_runner_timeout(tasks: list[dict[str, object]]) -> int:
    maximum_ms = max(
        int(
            cast(dict[str, object], cast(dict[str, object], task["input"])["assay"])[
                "timeout_ms"
            ]
        )
        for task in tasks
    )
    return max(600, (maximum_ms + 999) // 1_000 + 120)


def coding_runtime_identity(
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


def solution_driver_request(
    profile: dict[str, object],
    artifact: dict[str, object],
    *,
    proposer: Path,
    coding_runtime_id: str,
) -> dict[str, object]:
    limits = cast(dict[str, int], profile["limits"])
    development = task_documents(profile, "development")
    runner_timeout = task_runner_timeout(development)
    request: dict[str, object] = {
        "allocation_draws": profile["allocation_draws"],
        "evidence_adapter": {
            "command": control_command(EVIDENCE),
            "timeout_seconds": 300,
        },
        "generation": {
            "evaluation": "darwinian-coding/development-v1",
            "evaluator": {
                "command": control_command(EVALUATOR),
                "timeout_seconds": 300,
            },
            "runner": {
                "command": control_command(GIT_ADAPTER),
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
            "max_total_candidate_cost": resource_budget(10**15),
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
                "budget": resource_budget(10**12),
                "runtime_id": coding_runtime_id,
            },
        },
        "proposal": {
            "command": control_command(proposer),
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
    if "stopping" in profile:
        request["stopping"] = profile["stopping"]
    return request
