from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POPULATION = ROOT / "apps" / "population" / "population.py"
RESOURCE_NAMES = (
    "actions",
    "energy_millijoules",
    "gpu_milliseconds",
    "memory_bytes",
    "storage_bytes",
    "tokens",
    "wall_milliseconds",
)


def encode(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def artifact_candidate_id(artifact: dict[str, object]) -> str:
    return sha(encode({"artifact": artifact, "candidate_schema": "agent-candidate-v1"}))


def resources(value: int) -> dict[str, int]:
    return {name: value for name in RESOURCE_NAMES}


def skill(name: str, skill_text: str, asset_text: str) -> dict[str, object]:
    return {
        "artifact_schema": "agent-skill-v1",
        "files": [
            {
                "content": (
                    f"---\nname: {name}\ndescription: {name} candidate.\n---\n\n"
                    f"{skill_text}\n"
                ),
                "executable": False,
                "path": "SKILL.md",
            },
            {"content": asset_text, "executable": False, "path": "asset.txt"},
        ],
    }


def invoke(
    state: Path,
    command: str,
    request: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(POPULATION), command, str(state)],
        cwd=ROOT,
        input="" if request is None else encode(request),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def accepted(
    state: Path,
    command: str,
    request: dict[str, object] | None = None,
) -> dict[str, object]:
    result = invoke(state, command, request)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.endswith("\n")
    document = json.loads(result.stdout)
    assert result.stdout == encode(document) + "\n"
    return document


def initialize(state: Path, *, capacity: int = 4) -> dict[str, object]:
    return accepted(
        state,
        "init",
        {
            "configuration": {
                "archive_policy": {
                    "capacity": capacity,
                    "reliability_kappa": 1,
                    "type": "pareto-uniform-v1",
                },
                "name": "test population",
            },
            "schema_version": 1,
        },
    )


def add_candidate(
    state: Path,
    artifact: dict[str, object],
    *,
    parents: list[str] | None = None,
) -> dict[str, object]:
    parent_ids = [] if parents is None else parents
    variation = (
        {"choice": {"source": "fixture"}, "policy_id": None, "type": "seed-v1"}
        if not parent_ids
        else {
            "choice": {"source": "fixture"},
            "policy_id": sha("mutation-policy"),
            "type": "mutation-v1",
        }
    )
    return accepted(
        state,
        "candidate",
        {
            "artifact": artifact,
            "parents": parent_ids,
            "schema_version": 1,
            "variation": variation,
        },
    )


def add_experiment(
    state: Path,
    *,
    role: str = "development",
    information_objective: bool = False,
) -> dict[str, object]:
    return accepted(
        state,
        "experiment",
        {
            "experiment": {
                "behavior_space": ["direct", "exploratory"],
                "budget": resources(1_000),
                "case_count": 2,
                "evaluator_id": sha(f"{role}-evaluator"),
                "information_objective": information_objective,
                "role": role,
                "runtime_id": sha("runtime"),
                "task_set_id": sha(f"{role}-tasks"),
            },
            "schema_version": 1,
        },
    )


def add_run(
    state: Path,
    candidate_id: str,
    experiment_id: str,
    replicate_id: str,
    *,
    passed: int,
    target_probability: float,
    behavior: list[float],
    cost: int,
    seed: object = 1,
    information_model: object = None,
) -> subprocess.CompletedProcess[str]:
    return invoke(
        state,
        "run",
        {
            "candidate_id": candidate_id,
            "evidence": {
                "behavior_distribution": behavior,
                "cost": resources(cost),
                "evidence_receipt": {
                    "sha256": sha(f"{candidate_id}/{experiment_id}/{replicate_id}"),
                    "uri": f"evidence://{replicate_id}",
                },
                "information_model": information_model,
                "protected_passed": True,
                "target_probabilities": [target_probability, target_probability],
                "task": {
                    "case_count": 2,
                    "passed_count": passed,
                    "safety_failures": 0,
                },
            },
            "experiment_id": experiment_id,
            "replicate_id": replicate_id,
            "schema_version": 1,
            "seed": seed,
        },
    )


def population_with_evidence(state: Path) -> tuple[str, str, str]:
    initialize(state)
    first = add_candidate(state, skill("first", "FIRST", "asset-first"))
    second = add_candidate(state, skill("second", "SECOND", "asset-second"))
    experiment = add_experiment(state)
    first_id = str(first["candidate_id"])
    second_id = str(second["candidate_id"])
    experiment_id = str(experiment["experiment_id"])
    first_run = add_run(
        state,
        first_id,
        experiment_id,
        "replicate-a",
        passed=1,
        target_probability=0.5,
        behavior=[0.9, 0.1],
        cost=5,
    )
    assert first_run.returncode == 0, first_run.stderr
    second_run = add_run(
        state,
        second_id,
        experiment_id,
        "replicate-b",
        passed=2,
        target_probability=0.8,
        behavior=[0.1, 0.9],
        cost=10,
    )
    assert second_run.returncode == 0, second_run.stderr
    return first_id, second_id, experiment_id


def test_population_records_archive_allocation_and_rebuildable_index(tmp_path):
    state = tmp_path / "population"
    first_id, second_id, experiment_id = population_with_evidence(state)

    archive = accepted(
        state,
        "archive",
        {"experiment_id": experiment_id, "schema_version": 1},
    )
    assert set(archive["member_candidate_ids"]) == {first_id, second_id}

    allocation = accepted(
        state,
        "allocate",
        {
            "archive_record_id": archive["record_id"],
            "draw": {"denominator": 2, "numerator": 1},
            "schema_version": 1,
        },
    )
    assert allocation["selected_candidate_id"] == sorted([first_id, second_id])[1]

    rebuilt = accepted(state, "rebuild")
    assert rebuilt["record_count"] == 8
    verified = accepted(state, "verify-index")
    assert verified["verified"] is True

    summary = accepted(
        state,
        "query",
        {"schema_version": 1, "type": "summary"},
    )
    assert summary["result"]["counts"] == {
        "allocations": 1,
        "archives": 1,
        "candidates": 2,
        "experiments": 1,
        "records": 8,
        "runs": 2,
    }
    indexed_archive = accepted(
        state,
        "query",
        {
            "archive_record_id": archive["record_id"],
            "schema_version": 1,
            "type": "archive",
        },
    )["result"]
    assert {item["candidate_id"] for item in indexed_archive["members"]} == {
        first_id,
        second_id,
    }
    # Novelty compares each member only with other members, never with itself.
    assert all(item["novelty_bits"]["value"] > 0 for item in indexed_archive["members"])

    Path(rebuilt["index_path"]).unlink()
    rebuilt_again = accepted(state, "rebuild")
    assert rebuilt_again["ledger_head_record_id"] == rebuilt["ledger_head_record_id"]
    accepted(state, "verify-index")


def test_run_case_count_must_match_experiment_identity(tmp_path):
    state = tmp_path / "population"
    initialize(state)
    candidate = add_candidate(state, skill("cases", "CASES", "asset"))
    experiment = add_experiment(state)
    request = {
        "candidate_id": candidate["candidate_id"],
        "evidence": {
            "behavior_distribution": [0.5, 0.5],
            "cost": resources(1),
            "evidence_receipt": {
                "sha256": sha("wrong-case-count"),
                "uri": "evidence://wrong-case-count",
            },
            "information_model": None,
            "protected_passed": True,
            "target_probabilities": [0.8],
            "task": {"case_count": 1, "passed_count": 1, "safety_failures": 0},
        },
        "experiment_id": experiment["experiment_id"],
        "replicate_id": "wrong-case-count",
        "schema_version": 1,
        "seed": 1,
    }

    result = invoke(state, "run", request)

    assert result.returncode == 2
    assert json.loads(result.stderr)["error"]["code"] == "invalid_request"
    assert "case_count does not match" in result.stderr


def test_pareto_archive_excludes_a_strictly_dominated_candidate(tmp_path):
    state = tmp_path / "population"
    initialize(state)
    weaker = add_candidate(state, skill("weaker", "WEAKER", "asset-weaker"))
    stronger = add_candidate(state, skill("stronger", "STRONGER", "asset-stronger"))
    experiment = add_experiment(state)
    weak_run = add_run(
        state,
        str(weaker["candidate_id"]),
        str(experiment["experiment_id"]),
        "weaker-replicate",
        passed=1,
        target_probability=0.5,
        behavior=[0.5, 0.5],
        cost=5,
    )
    strong_run = add_run(
        state,
        str(stronger["candidate_id"]),
        str(experiment["experiment_id"]),
        "stronger-replicate",
        passed=2,
        target_probability=0.8,
        behavior=[0.5, 0.5],
        cost=5,
    )
    assert weak_run.returncode == 0, weak_run.stderr
    assert strong_run.returncode == 0, strong_run.stderr

    archive = accepted(
        state,
        "archive",
        {"experiment_id": experiment["experiment_id"], "schema_version": 1},
    )
    assert archive["member_candidate_ids"] == [stronger["candidate_id"]]
    record = json.loads((state / "population.jsonl").read_text().splitlines()[-1])
    assert record["body"]["excluded"] == [
        {"candidate_id": weaker["candidate_id"], "reason": "dominated"}
    ]


def test_population_run_identity_requires_a_unique_replicate(tmp_path):
    state = tmp_path / "population"
    first_id, _, experiment_id = population_with_evidence(state)
    before = (state / "population.jsonl").read_bytes()

    duplicate = add_run(
        state,
        first_id,
        experiment_id,
        "replicate-a",
        passed=2,
        target_probability=0.9,
        behavior=[0.8, 0.2],
        cost=1,
        seed="different-seed",
    )

    assert duplicate.returncode == 2
    error = json.loads(duplicate.stderr)["error"]
    assert error["code"] == "population_error"
    assert "duplicate candidate/experiment/replicate" in error["message"]
    assert (state / "population.jsonl").read_bytes() == before


def test_resource_violation_is_infeasible_and_empty_archive_cannot_allocate(tmp_path):
    state = tmp_path / "population"
    initialize(state)
    candidate = add_candidate(state, skill("costly", "COSTLY", "asset"))
    experiment = add_experiment(state)
    run = add_run(
        state,
        str(candidate["candidate_id"]),
        str(experiment["experiment_id"]),
        "over-budget",
        passed=2,
        target_probability=0.9,
        behavior=[0.5, 0.5],
        cost=1_001,
    )
    assert run.returncode == 0, run.stderr
    archive = accepted(
        state,
        "archive",
        {"experiment_id": experiment["experiment_id"], "schema_version": 1},
    )
    assert archive["member_candidate_ids"] == []

    allocation = invoke(
        state,
        "allocate",
        {
            "archive_record_id": archive["record_id"],
            "draw": {"denominator": 1, "numerator": 0},
            "schema_version": 1,
        },
    )
    assert allocation.returncode == 2
    assert "empty archive" in allocation.stderr


def test_final_evidence_cannot_create_an_archive_or_parent(tmp_path):
    state = tmp_path / "population"
    initialize(state)
    candidate = add_candidate(state, skill("final", "FINAL", "asset"))
    final = add_experiment(state, role="final")
    result = add_run(
        state,
        str(candidate["candidate_id"]),
        str(final["experiment_id"]),
        "final-replicate",
        passed=2,
        target_probability=0.9,
        behavior=[0.5, 0.5],
        cost=1,
    )
    assert result.returncode == 0, result.stderr
    before = (state / "population.jsonl").read_bytes()

    rejected = invoke(
        state,
        "archive",
        {"experiment_id": final["experiment_id"], "schema_version": 1},
    )

    assert rejected.returncode == 2
    assert "final experiments cannot create selectable archives" in rejected.stderr
    assert (state / "population.jsonl").read_bytes() == before


def test_final_run_seals_development_archive_and_allocation(tmp_path):
    state = tmp_path / "population"
    first_id, _, development_id = population_with_evidence(state)
    archive = accepted(
        state,
        "archive",
        {"experiment_id": development_id, "schema_version": 1},
    )
    final = add_experiment(state, role="final")
    final_run = add_run(
        state,
        first_id,
        str(final["experiment_id"]),
        "final-only-replicate",
        passed=2,
        target_probability=0.9,
        behavior=[0.5, 0.5],
        cost=1,
    )
    assert final_run.returncode == 0, final_run.stderr

    allocation = invoke(
        state,
        "allocate",
        {
            "archive_record_id": archive["record_id"],
            "draw": {"denominator": 1, "numerator": 0},
            "schema_version": 1,
        },
    )
    assert allocation.returncode == 2
    assert "sealed after final evaluation starts" in allocation.stderr
    assert accepted(state, "verify")["final_evaluation_started"] is True


def test_typed_recombination_records_both_parents_and_rejects_stale_archive(tmp_path):
    state = tmp_path / "population"
    first_id, second_id, experiment_id = population_with_evidence(state)
    archive = accepted(
        state,
        "archive",
        {"experiment_id": experiment_id, "schema_version": 1},
    )

    child = accepted(
        state,
        "recombine",
        {
            "loci": [
                {"parent_candidate_id": first_id, "path": "SKILL.md"},
                {"parent_candidate_id": second_id, "path": "asset.txt"},
            ],
            "parents": [first_id, second_id],
            "policy_id": sha("typed-recombination-policy"),
            "schema_version": 1,
        },
    )
    assert child["candidate_id"] not in {first_id, second_id}
    child_run = add_run(
        state,
        str(child["candidate_id"]),
        experiment_id,
        "recombined-replicate",
        passed=2,
        target_probability=0.7,
        behavior=[0.5, 0.5],
        cost=4,
    )
    assert child_run.returncode == 0, child_run.stderr

    stale = invoke(
        state,
        "allocate",
        {
            "archive_record_id": archive["record_id"],
            "draw": {"denominator": 1, "numerator": 0},
            "schema_version": 1,
        },
    )
    assert stale.returncode == 2
    assert "stale" in stale.stderr

    accepted(state, "rebuild")
    lineage = accepted(
        state,
        "query",
        {
            "candidate_id": child["candidate_id"],
            "schema_version": 1,
            "type": "lineage",
        },
    )["result"]
    assert lineage["parents"] == [first_id, second_id]


def test_index_accepts_a_child_whose_content_id_sorts_before_its_parent(tmp_path):
    state = tmp_path / "population"
    initialize(state)
    parent_artifact = skill("parent", "PARENT", "parent-asset")
    parent = add_candidate(state, parent_artifact)
    parent_id = str(parent["candidate_id"])
    child_artifact = None
    for index in range(1_000):
        candidate_artifact = skill(
            f"child-{index}", f"CHILD {index}", f"child-asset-{index}"
        )
        if artifact_candidate_id(candidate_artifact) < parent_id:
            child_artifact = candidate_artifact
            break
    assert child_artifact is not None
    child = add_candidate(state, child_artifact, parents=[parent_id])
    assert child["candidate_id"] < parent_id

    accepted(state, "rebuild")
    lineage = accepted(
        state,
        "query",
        {
            "candidate_id": child["candidate_id"],
            "schema_version": 1,
            "type": "lineage",
        },
    )["result"]
    assert lineage["parents"] == [parent_id]


def test_information_value_uses_declared_finite_belief_model(tmp_path):
    state = tmp_path / "population"
    initialize(state)
    candidate = add_candidate(state, skill("info", "INFO", "asset"))
    experiment = add_experiment(state, information_objective=True)
    information_model = {
        "outcomes": [
            {"posterior": [1, 0], "probability": 0.5},
            {"posterior": [0, 1], "probability": 0.5},
        ],
        "prior": [0.5, 0.5],
    }

    result = add_run(
        state,
        str(candidate["candidate_id"]),
        str(experiment["experiment_id"]),
        "information-replicate",
        passed=1,
        target_probability=0.75,
        behavior=[0.5, 0.5],
        cost=1,
        information_model=information_model,
    )

    assert result.returncode == 0, result.stderr
    run_record = json.loads((state / "population.jsonl").read_text().splitlines()[-1])
    assert run_record["body"]["measurements"]["information_value_bits"] == 1.0


def test_undeclared_information_does_not_change_archive_retention(tmp_path):
    state = tmp_path / "population"
    initialize(state, capacity=1)
    first = add_candidate(state, skill("optional-a", "A", "asset-a"))
    second = add_candidate(state, skill("optional-b", "B", "asset-b"))
    experiment = add_experiment(state, information_objective=False)
    candidate_ids = sorted([str(first["candidate_id"]), str(second["candidate_id"])])
    information_model = {
        "outcomes": [
            {"posterior": [1, 0], "probability": 0.5},
            {"posterior": [0, 1], "probability": 0.5},
        ],
        "prior": [0.5, 0.5],
    }
    smaller = add_run(
        state,
        candidate_ids[0],
        str(experiment["experiment_id"]),
        "without-optional-information",
        passed=1,
        target_probability=0.75,
        behavior=[0.5, 0.5],
        cost=1,
    )
    larger = add_run(
        state,
        candidate_ids[1],
        str(experiment["experiment_id"]),
        "with-optional-information",
        passed=1,
        target_probability=0.75,
        behavior=[0.5, 0.5],
        cost=1,
        information_model=information_model,
    )
    assert smaller.returncode == 0, smaller.stderr
    assert larger.returncode == 0, larger.stderr

    archive = accepted(
        state,
        "archive",
        {"experiment_id": experiment["experiment_id"], "schema_version": 1},
    )

    assert archive["member_candidate_ids"] == [candidate_ids[0]]


def test_declared_information_objective_rejects_missing_model(tmp_path):
    state = tmp_path / "population"
    initialize(state)
    candidate = add_candidate(state, skill("info", "INFO", "asset"))
    experiment = add_experiment(state, information_objective=True)

    result = add_run(
        state,
        str(candidate["candidate_id"]),
        str(experiment["experiment_id"]),
        "missing-information",
        passed=1,
        target_probability=0.75,
        behavior=[0.5, 0.5],
        cost=1,
    )

    assert result.returncode == 2
    assert json.loads(result.stderr)["error"]["code"] == "invalid_request"
    assert "information_model is required" in result.stderr


def test_index_tampering_is_rejected_and_never_controls_selection(tmp_path):
    state = tmp_path / "population"
    _, _, experiment_id = population_with_evidence(state)
    archive = accepted(
        state,
        "archive",
        {"experiment_id": experiment_id, "schema_version": 1},
    )
    accepted(state, "rebuild")
    index = state / "population.sqlite"
    connection = sqlite3.connect(index)
    try:
        connection.execute(
            "UPDATE metadata SET value='forged' WHERE key='ledger_head_record_id'"
        )
        connection.commit()
    finally:
        connection.close()

    verification = invoke(state, "verify-index")
    assert verification.returncode == 2
    assert "does not match canonical ledger rebuild" in verification.stderr

    # Allocation derives from the ledger archive, not the modified index.
    selected = accepted(
        state,
        "allocate",
        {
            "archive_record_id": archive["record_id"],
            "draw": {"denominator": 1, "numerator": 0},
            "schema_version": 1,
        },
    )
    assert selected["selected_candidate_id"] in archive["member_candidate_ids"]


def test_tampered_ledger_is_rejected_without_repair(tmp_path):
    state = tmp_path / "population"
    population_with_evidence(state)
    ledger = state / "population.jsonl"
    records = ledger.read_text().splitlines()
    tampered = json.loads(records[-1])
    tampered["body"]["measurements"]["task_rate"] = 0.0
    records[-1] = encode(tampered)
    ledger.write_text("\n".join(records) + "\n", encoding="utf-8")
    before = ledger.read_bytes()

    result = invoke(state, "verify")

    assert result.returncode == 2
    assert "record_id does not match its content" in result.stderr
    assert ledger.read_bytes() == before


def test_invalid_request_does_not_initialize_state(tmp_path):
    state = tmp_path / "population"
    result = invoke(
        state,
        "init",
        {
            "configuration": {
                "archive_policy": {
                    "capacity": 0,
                    "reliability_kappa": 1,
                    "type": "pareto-uniform-v1",
                },
                "name": "invalid",
            },
            "schema_version": 1,
        },
    )

    assert result.returncode == 2
    assert json.loads(result.stderr)["error"]["code"] == "invalid_request"
    assert not state.exists()
