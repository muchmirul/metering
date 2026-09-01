"""End-to-end Darwinian recurrence over immutable executable Git code."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "apps" / "population_driver" / "population_driver.py"
ADAPTER = ROOT / "apps" / "population_driver" / "darwinian_code_adapter.py"
RESOURCE_NAMES = (
    "actions",
    "energy_millijoules",
    "gpu_milliseconds",
    "memory_bytes",
    "storage_bytes",
    "tokens",
    "wall_milliseconds",
)


def _git(repository: Path, *arguments: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _solver(operator: str) -> str:
    return (
        "import json,sys\n"
        "request=json.load(sys.stdin)\n"
        f"answer=request['left'] {operator} request['right']\n"
        "print(json.dumps({'answer':answer},separators=(',',':'),sort_keys=True))\n"
    )


def _content_identity(content: bytes) -> str:
    path = b"solver.py"
    digest = hashlib.sha256(b"metering-git-candidate-content-v1\x00")
    digest.update(b"100644\x00")
    digest.update(str(len(path)).encode("ascii") + b":" + path)
    digest.update(str(len(content)).encode("ascii") + b":" + content)
    return digest.hexdigest()


def _seed_repository(repository: Path) -> dict[str, object]:
    repository.mkdir()
    _git(repository, "init", "--quiet")
    source = _solver("-")
    (repository / "solver.py").write_text(source, encoding="utf-8")
    _git(repository, "add", "--", "solver.py")
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_AUTHOR_NAME": "Metering Fixture",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Metering Fixture",
        }
    )
    _git(
        repository,
        "commit",
        "--quiet",
        "--no-gpg-sign",
        "-m",
        "seed subtraction solver",
        env=environment,
    )
    commit = _git(repository, "rev-parse", "HEAD")
    return {
        "artifact_schema": "git-candidate-v1",
        "commit": commit,
        "content_sha256": _content_identity(source.encode()),
        "entrypoint": "solver.py",
        "git_tree": _git(repository, "rev-parse", "HEAD^{tree}"),
        "outputs": [],
        "repository": str(repository),
    }


def _component(action: str) -> dict[str, object]:
    return {
        "command": [sys.executable, str(ADAPTER), action],
        "timeout_seconds": 20,
    }


def _request(initial_artifact: dict[str, object]) -> dict[str, object]:
    return {
        "allocation_draws": [{"denominator": 1, "numerator": 0}],
        "evidence_adapter": _component("evidence"),
        "generation": {
            "evaluation": "darwinian-arithmetic/addition-v1",
            "evaluator": _component("evaluator"),
            "runner": _component("runner"),
            "selection_policy": {
                "minimum_pass_improvement": 1,
                "reject_safety_regression": True,
                "type": "task-pass-count-v1",
            },
            "tasks": [
                {"case_id": "positive", "input": {"left": 2, "right": 3}},
                {"case_id": "separated", "input": {"left": 4, "right": 7}},
                {"case_id": "signed", "input": {"left": -3, "right": 8}},
            ],
        },
        "initial_parent_artifact": initial_artifact,
        "limits": {
            "max_proposal_calls": 2,
            "max_rounds": 2,
            "max_total_candidate_cost": {name: 100 for name in RESOURCE_NAMES},
            "max_wall_seconds": 1000,
        },
        "population": {
            "configuration": {
                "archive_policy": {
                    "capacity": 8,
                    "reliability_kappa": 0,
                    "type": "pareto-uniform-v1",
                },
                "name": "darwinian-executable-git-arithmetic",
            },
            "development": {
                "behavior_space": ["incorrect", "correct"],
                "budget": {name: 10 for name in RESOURCE_NAMES},
                "runtime_id": "1" * 64,
            },
        },
        "proposal": {
            "command": [sys.executable, str(ADAPTER), "proposal"],
            "context": {"objective": "Evolve solver.py to return left plus right."},
            "timeout_seconds": 20,
        },
        "schema_version": 1,
    }


def _run_driver(
    command: str,
    state: Path,
    request: dict[str, object] | None,
    environment: dict[str, str],
) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(DRIVER), command, str(state)],
        cwd=ROOT,
        input=(
            ""
            if request is None
            else json.dumps(
                request, allow_nan=False, separators=(",", ":"), sort_keys=True
            )
        ),
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert type(result) is dict
    return result


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_darwinian_recurrence_evolves_and_retains_executable_git_code(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "candidates"
    initial_artifact = _seed_repository(repository)
    state = tmp_path / "state"
    environment = os.environ.copy()
    environment["METERING_GIT_REPOSITORY"] = str(repository)

    summary = _run_driver("run", state, _request(initial_artifact), environment)
    assert summary["status"] == "round_limit"
    assert summary["completed_rounds"] == 2
    assert summary["candidate_count"] == 3
    assert summary["run_count"] == 4
    assert summary["archive_count"] == 2
    assert summary["allocation_count"] == 1
    assert summary["final_evaluation_started"] is False

    driver_records = _records(state / "driver.jsonl")
    decisions = [
        cast(dict[str, object], record["selection"])["decision"]
        for record in driver_records[1:]
    ]
    assert decisions == ["promote_challenger", "retain_incumbent"]

    population_records = _records(state / "population" / "population.jsonl")
    candidate_records = [
        record for record in population_records if record["kind"] == "candidate"
    ]
    candidates = [
        cast(dict[str, object], record["body"])["candidate"]
        for record in candidate_records
    ]
    seed, improvement, regression = cast(list[dict[str, object]], candidates)
    allocation_record = next(
        record for record in population_records if record["kind"] == "allocation"
    )
    allocation_result = cast(
        dict[str, object], cast(dict[str, object], allocation_record["body"])["result"]
    )
    assert allocation_result["selected_candidate_id"] == improvement["candidate_id"]
    assert driver_records[2]["parent_candidate_id"] == improvement["candidate_id"]
    assert (
        driver_records[2]["parent_allocation_record_id"]
        == allocation_record["record_id"]
    )
    commits = [
        str(cast(dict[str, object], candidate["artifact"])["commit"])
        for candidate in candidates
    ]
    assert _git(repository, "rev-parse", f"{commits[1]}^") == commits[0]
    assert _git(repository, "rev-parse", f"{commits[2]}^") == commits[1]

    run_records = [record for record in population_records if record["kind"] == "run"]
    totals: dict[str, tuple[int, int]] = {}
    for record in run_records:
        body = cast(dict[str, object], record["body"])
        run = cast(dict[str, object], body["run"])
        task = cast(dict[str, int], cast(dict[str, object], body["evidence"])["task"])
        candidate_id = str(run["candidate_id"])
        old_passed, old_count = totals.get(candidate_id, (0, 0))
        totals[candidate_id] = (
            old_passed + task["passed_count"],
            old_count + task["case_count"],
        )
    assert totals[str(seed["candidate_id"])] == (0, 3)
    assert totals[str(improvement["candidate_id"])] == (6, 6)
    assert totals[str(regression["candidate_id"])] == (0, 3)

    archives = [
        cast(dict[str, object], record["body"])
        for record in population_records
        if record["kind"] == "archive"
    ]
    latest_members = cast(list[dict[str, object]], archives[-1]["members"])
    assert [member["candidate_id"] for member in latest_members] == [
        improvement["candidate_id"]
    ]
    assert {
        item["candidate_id"]: item["reason"]
        for item in cast(list[dict[str, str]], archives[-1]["excluded"])
    } == {
        seed["candidate_id"]: "dominated",
        regression["candidate_id"]: "dominated",
    }
    selected_source = _git(repository, "show", f"{commits[1]}:solver.py")
    assert "request['left'] + request['right']" in selected_source

    verified = _run_driver("verify", state, None, environment)
    assert verified["status"] == "verified"
    assert verified["population_head_record_id"] == summary["population_head_record_id"]
