from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "apps" / "variant_search" / "variant_search.py"

sys.path.insert(0, str(ROOT / "apps"))
sys.path.insert(0, str(ROOT / "apps" / "variant_search"))

from agent_protocol import candidate_record  # noqa: E402
from population_math import price_decomposition, weighted_covariance  # noqa: E402


def skill(name: str) -> dict[str, object]:
    return candidate_record(
        {
            "artifact_schema": "agent-skill-v1",
            "files": [
                {
                    "content": name,
                    "executable": False,
                    "path": "SKILL.md",
                }
            ],
        }
    )


def run(database: Path, request: dict[str, object]) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--database", str(database)],
        cwd=ROOT,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout)


def initialize(database: Path) -> dict[str, object]:
    return run(
        database,
        {
            "schema_version": 1,
            "operation": "initialize",
            "law": {"runner": "fixed", "evaluator": "sealed-v1"},
        },
    )


def register(
    database: Path,
    candidate: dict[str, object],
    parents: list[str],
    generation: int,
    operator: str,
) -> dict[str, object]:
    artifact = candidate["artifact"]
    assert type(artifact) is dict
    files = artifact["files"]
    assert type(files) is list
    first = files[0]
    assert type(first) is dict
    return run(
        database,
        {
            "schema_version": 1,
            "operation": "register_candidate",
            "candidate": candidate,
            "parents": parents,
            "generation": generation,
            "operator": operator,
            "manifest": {"name": first["content"]},
        },
    )


def evaluate(
    database: Path,
    candidate: dict[str, object],
    task: float,
    cost: float,
    survival: bool,
) -> dict[str, object]:
    artifact = candidate["artifact"]
    assert type(artifact) is dict
    files = artifact["files"]
    assert type(files) is list
    first = files[0]
    assert type(first) is dict
    return run(
        database,
        {
            "schema_version": 1,
            "operation": "record_evaluation",
            "candidate_id": candidate["candidate_id"],
            "environment_id": "suite-v1",
            "metrics": {"task": task, "cost": cost},
            "constraints": {"survival": survival},
            "descriptors": {"style": first["content"]},
            "resources": {"tokens": cost},
        },
    )


def test_population_registry_selection_reallocation_and_verify(tmp_path: Path) -> None:
    database = tmp_path / "population.sqlite3"
    initialize(database)
    a, b, c = skill("a"), skill("b"), skill("c")
    register(database, a, [], 0, "seed")
    register(database, b, [str(a["candidate_id"])], 1, "mutation")
    register(
        database,
        c,
        [str(a["candidate_id"]), str(b["candidate_id"])],
        2,
        "recombination",
    )
    evidence_a = evaluate(database, a, 0.90, 100, True)
    evidence_b = evaluate(database, b, 0.85, 60, True)
    evidence_c = evaluate(database, c, 0.95, 150, False)

    selected = run(
        database,
        {
            "schema_version": 1,
            "operation": "select",
            "evidence_ids": [
                evidence_a["evidence_id"],
                evidence_b["evidence_id"],
                evidence_c["evidence_id"],
            ],
            "objectives": [
                {"metric": "task", "direction": "maximize", "weight": 1.0},
                {"metric": "cost", "direction": "minimize", "weight": 0.001},
            ],
            "required_constraints": ["survival"],
            "pool_size": 2,
            "beta": 2.0,
            "parent_draws": [0.0, 0.0],
        },
    )

    assert set(selected["pareto_front"]) == {
        a["candidate_id"],
        b["candidate_id"],
    }
    assert selected["rejected"] == [
        {
            "candidate_id": c["candidate_id"],
            "failed_constraints": ["survival"],
        }
    ]
    assert selected["parents"] == [a["candidate_id"], b["candidate_id"]]
    assert sum(item["weight"] for item in selected["pool"]) == pytest.approx(1.0)

    reallocated = run(
        database,
        {
            "schema_version": 1,
            "operation": "reallocate",
            "contribution_factors": {
                a["candidate_id"]: 0.5,
                b["candidate_id"]: 2.0,
            },
            "parent_draws": [0.99],
        },
    )
    weights = {item["candidate_id"]: item["weight"] for item in reallocated["pool"]}
    assert weights[b["candidate_id"]] > weights[a["candidate_id"]]

    verified = run(database, {"schema_version": 1, "operation": "verify"})
    assert verified["valid"] is True
    assert verified["candidate_count"] == 3
    assert verified["evaluation_count"] == 3
    snapshot = run(database, {"schema_version": 1, "operation": "snapshot"})
    assert snapshot["state_id"] == verified["state_id"]


def test_register_and_evaluation_are_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "population.sqlite3"
    initialize(database)
    candidate = skill("a")

    assert register(database, candidate, [], 0, "seed")["created"] is True
    assert register(database, candidate, [], 0, "seed")["created"] is False
    first = evaluate(database, candidate, 0.5, 2, True)
    second = evaluate(database, candidate, 0.5, 2, True)
    assert first["created"] is True
    assert second["created"] is False
    assert first["evidence_id"] == second["evidence_id"]


def test_verify_detects_sqlite_content_tampering(tmp_path: Path) -> None:
    database = tmp_path / "population.sqlite3"
    initialize(database)
    candidate = skill("a")
    register(database, candidate, [], 0, "seed")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE candidates SET manifest_json='{}'")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--database", str(database)],
        cwd=ROOT,
        input=json.dumps({"schema_version": 1, "operation": "verify"}),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stderr)["error"]["code"] == "invalid_population"


def test_population_math_exposes_price_accounting() -> None:
    assert weighted_covariance([1, 2], [1, 3], [0.5, 0.5]) == pytest.approx(0.5)
    result = price_decomposition([1, 2], [1, 2], [0, 0], [0.5, 0.5])
    assert result["allocation_effect"] == pytest.approx(1 / 6)
    assert result["change_effect"] == 0
    assert result["total_delta"] == pytest.approx(1 / 6)
