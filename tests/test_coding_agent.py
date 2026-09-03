"""Isolated coding workspace and independently evaluated harness behavior."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json  # noqa: E402
import apps.coding_agent.solution_experiment as solution_module  # noqa: E402
from apps.coding_agent.evaluator import evaluate  # noqa: E402
from apps.coding_agent.process_tracker import (  # noqa: E402
    ProcessTrackerError,
    advance_process_status,
    load_process_status,
)
from apps.coding_agent.protocol import (  # noqa: E402
    CodingTaskError,
    load_final_checks,
    load_task_profile,
)
from apps.harness.experiment import (  # noqa: E402
    harness_process_status,
    run_experiment,
    verify_experiment,
)
from apps.harness.harness_runner import execute  # noqa: E402
from apps.harness.protocol import load_candidate, refresh_manifest  # noqa: E402
from apps.coding_agent.solution_experiment import (  # noqa: E402
    SolutionExperimentError,
    continue_experiment as continue_solution_experiment,
    run_experiment as run_solution_experiment,
    solution_process_status,
    verify_experiment as verify_solution_experiment,
)
from apps.population_driver.runtime import PopulationDriverError  # noqa: E402
from artifacts.git.git_repository import run_git  # noqa: E402

REFERENCE = ROOT / "apps" / "harness" / "reference"
FIXTURES = ROOT / "apps" / "harness" / "fixtures"
CODING_FIXTURES = ROOT / "apps" / "coding_agent" / "fixtures"
RUNTIME = ROOT / "apps" / "harness" / "profiles" / "runtime-fixture.json"


def test_coding_task_profile_golden_identity() -> None:
    profile = load_task_profile(CODING_FIXTURES / "task-profile-v1.json")
    assert profile["task_id"] == (
        "58297ecbc04d4b7957215becdd5fd8e7844f35bf5bbf2f549a802c8272dc7375"
    )


def test_protected_final_profile_is_external_digest_bound_and_inline_is_rejected(
    tmp_path: Path,
) -> None:
    source_profile = json.loads(
        (CODING_FIXTURES / "task-profile-v1.json").read_text(encoding="ascii")
    )
    final_source = (CODING_FIXTURES / "final-profile-v1.json").read_bytes()
    final_path = tmp_path / "final.json"
    final_path.write_bytes(final_source)
    source_profile["final_assay"] = {
        "path": str(final_path.absolute()),
        "sha256": hashlib.sha256(final_source).hexdigest(),
    }
    profile_path = tmp_path / "task.json"
    profile_path.write_text(
        canonical_json(source_profile) + "\n", encoding="ascii", newline=""
    )
    profile = load_task_profile(profile_path)
    assert load_final_checks(profile) == json.loads(final_source)["checks"]
    final_path.write_bytes(final_source + b" ")
    with pytest.raises(CodingTaskError, match="digest does not match"):
        load_final_checks(profile)

    source_profile["final_checks"] = json.loads(final_source)["checks"]
    del source_profile["final_assay"]
    profile_path.write_text(
        canonical_json(source_profile) + "\n", encoding="ascii", newline=""
    )
    with pytest.raises(CodingTaskError, match="legacy-only"):
        load_task_profile(profile_path)


def _task() -> dict[str, object]:
    document = json.loads(
        (CODING_FIXTURES / "development-tasks.json").read_text(encoding="ascii")
    )
    return cast(list[dict[str, object]], document["tasks"])[0]


def _run(
    checkout: Path,
    candidate_id: str,
    task: dict[str, object],
    monkeypatch,
    receipts: Path,
) -> dict[str, object]:
    monkeypatch.setenv("METERING_HARNESS_RUNTIME_MANIFEST", str(RUNTIME))
    monkeypatch.setenv("METERING_HARNESS_RECEIPT_DIR", str(receipts))
    monkeypatch.setenv("METERING_HARNESS_ALLOW_UNSAFE_FIXTURE", "1")
    monkeypatch.setenv(
        "METERING_HARNESS_MODEL_COMMAND",
        canonical_json([sys.executable, str(FIXTURES / "fixture_model.py")]),
    )
    return execute(
        canonical_json(
            {
                "candidate": {
                    "artifact": {"entrypoint": "harness.json"},
                    "candidate_id": candidate_id,
                    "checkout_path": str(checkout),
                },
                "protocol_version": 1,
                "task": task,
            }
        )
    )


def test_six_stage_process_projection_is_canonical_and_monotonic(
    tmp_path: Path,
) -> None:
    harness_root = tmp_path / "harness-process"
    harness_root.mkdir()
    stage_one = advance_process_status(harness_root, stage=1, run_kind="harness")
    assert stage_one["display"] == "[1/6] Task and runtime configured"
    assert (
        advance_process_status(harness_root, stage=2, run_kind="harness")["display"]
        == "[2/6] Evolving harness"
    )

    root = tmp_path / "process"
    root.mkdir()
    stage_four = advance_process_status(root, stage=4, run_kind="solution")
    assert stage_four["display"] == "[4/6] Evolving solution"
    stage_five = advance_process_status(root, stage=5, run_kind="solution")
    assert stage_five["display"] == "[5/6] Protected final assay"
    assert advance_process_status(root, stage=4, run_kind="solution") == stage_five
    assert load_process_status(root, expected_run_kind="solution") == stage_five
    path = root / "process-status.json"
    document = json.loads(path.read_text(encoding="ascii"))
    document["stage_label"] = "forged"
    path.write_text(canonical_json(document) + "\n", encoding="ascii", newline="")
    with pytest.raises(ProcessTrackerError, match="does not replay"):
        load_process_status(root)


def test_harness_edits_repository_in_kernel_and_evaluator_runs_fresh_copy(
    tmp_path: Path, monkeypatch
) -> None:
    seed = tmp_path / "seed"
    addition = tmp_path / "addition"
    shutil.copytree(REFERENCE, seed)
    shutil.copytree(REFERENCE, addition)
    candidate = load_candidate(addition)
    prompt = addition / candidate.paths["system_prompt"]
    prompt.write_text(
        prompt.read_text(encoding="utf-8").replace(
            "ARITHMETIC_POLICY=SUBTRACT", "ARITHMETIC_POLICY=ADD"
        ),
        encoding="utf-8",
        newline="",
    )
    refresh_manifest(addition)
    task = _task()
    seed_run = _run(seed, "1" * 64, task, monkeypatch, tmp_path / "receipts")
    addition_run = _run(addition, "2" * 64, task, monkeypatch, tmp_path / "receipts")
    response = evaluate(
        {
            "case": task,
            "evaluation": "coding-fixture-v1",
            "protocol_version": 1,
            "submissions": [
                {
                    "candidate_id": "1" * 64,
                    "submission": seed_run["submission"],
                },
                {
                    "candidate_id": "2" * 64,
                    "submission": addition_run["submission"],
                },
            ],
        }
    )
    results = {
        str(item["candidate_id"]): item
        for item in cast(list[dict[str, object]], response["results"])
    }
    assert results["1" * 64]["passed"] is False
    assert results["2" * 64]["passed"] is True
    workspace = cast(
        dict[str, object],
        cast(dict[str, object], addition_run["submission"])[
            "_metering_coding_workspace"
        ],
    )
    assert workspace["changed_paths"] == ["solver.py"]
    tampered = json.loads(canonical_json(addition_run["submission"]))
    tampered_workspace = tampered["_metering_coding_workspace"]
    tampered_workspace["changed_paths"] = []
    tampered_workspace["sha256"] = hashlib.sha256(
        canonical_json(
            {
                "changed_paths": [],
                "files": tampered_workspace["files"],
            }
        ).encode("ascii")
    ).hexdigest()
    rejected = evaluate(
        {
            "case": task,
            "evaluation": "coding-fixture-v1",
            "protocol_version": 1,
            "submissions": [{"candidate_id": "2" * 64, "submission": tampered}],
        }
    )
    rejected_result = cast(list[dict[str, object]], rejected["results"])[0]
    assert rejected_result["passed"] is False
    assert rejected_result["safety_passed"] is False


def test_level_two_fixture_evolves_harness_on_coding_tasks_and_seals_final(
    tmp_path: Path,
) -> None:
    root = tmp_path / "harness-evolution"
    report = run_experiment("fixture", root, None, assay="coding-agent-v1")
    assert report["assay"] == "coding-agent-v1"
    development = cast(dict[str, object], report["development"])
    final = cast(dict[str, object], report["final"])
    assert development["completed_rounds"] == 2
    assert development["candidate_count"] == 3
    assert final["passed_count"] == final["task_count"] == 3
    assert report["final_selection"] == {
        "eligible_candidate_ids": [final["candidate_id"]],
        "policy": "development-task-rate-reliability-v1",
        "tie_draw": {"denominator": 1, "numerator": 0},
    }
    verified = verify_experiment(root)
    assert verified["assay"] == "coding-agent-v1"
    assert verified["status"] == "verified"
    assert harness_process_status(root)["display"] == "[3/6] Harness sealed"


def _write_solution_profile(
    root: Path,
    *,
    max_rounds: int,
    max_proposal_calls: int,
    stop_on_goal: bool = False,
) -> Path:
    root.mkdir(parents=True)
    repository = root / "source"
    repository.mkdir()
    (repository / "solver.py").write_text(
        "def solve(left: int, right: int) -> int:\n    return left - right\n",
        encoding="utf-8",
    )
    run_git(["init", "--quiet"], cwd=repository)
    run_git(["add", "--all"], cwd=repository)
    tree = run_git(["write-tree"], cwd=repository).strip()
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
    }
    commit = run_git(
        ["commit-tree", tree],
        cwd=repository,
        input_text="seed\n",
        environment=environment,
    ).strip()
    run_git(["update-ref", "refs/heads/main", commit], cwd=repository)
    final_document = {
        "checks": [
            {
                "argv": [
                    "python",
                    "-c",
                    "from solver import solve; assert solve(41, -9) == 32",
                ],
                "case_id": "final-mixed",
                "timeout_ms": 10_000,
            }
        ],
        "final_schema": "darwinian-coding-final-v1",
        "schema_version": 1,
    }
    final_path = root / "operator-final.json"
    final_source = (canonical_json(final_document) + "\n").encode("ascii")
    final_path.write_bytes(final_source)
    profile = {
        "allocation_draws": [
            {"denominator": 1, "numerator": 0} for _ in range(max_rounds - 1)
        ],
        "allowed_paths": ["solver.py"],
        "development_checks": [
            {
                "argv": [
                    "python",
                    "-c",
                    "from solver import solve; assert solve(2, 3) == 5",
                ],
                "case_id": "development-positive",
                "timeout_ms": 10_000,
            }
        ],
        "final_assay": {
            "path": str(final_path.absolute()),
            "sha256": hashlib.sha256(final_source).hexdigest(),
        },
        "final_draw": {"denominator": 1, "numerator": 0},
        "goal": "Fix solver.py so solve returns left plus right.",
        "limits": {
            "max_proposal_calls": max_proposal_calls,
            "max_rounds": max_rounds,
            "max_wall_seconds": 100_000,
        },
        "repository": {
            "base_commit": commit,
            "entrypoint": "solver.py",
            "path": str(repository.absolute()),
        },
        "schema_version": 1,
        "task_schema": "darwinian-coding-task-v1",
    }
    if stop_on_goal:
        profile["stopping"] = {
            "minimum_replicates": 1,
            "type": "all-development-cases-pass-v1",
        }
    profile_path = root / "task.json"
    profile_path.write_text(
        canonical_json(profile) + "\n", encoding="ascii", newline=""
    )
    return profile_path


def test_task_profile_binds_a_worded_goal_and_a_maximum_100_rounds(
    tmp_path: Path,
) -> None:
    profile_path = _write_solution_profile(
        tmp_path / "goal-profile",
        max_rounds=100,
        max_proposal_calls=100,
        stop_on_goal=True,
    )

    profile = load_task_profile(profile_path)
    assert profile["goal"] == "Fix solver.py so solve returns left plus right."
    assert cast(dict[str, int], profile["limits"])["max_rounds"] == 100
    assert len(cast(list[object], profile["allocation_draws"])) == 99
    assert profile["stopping"] == {
        "minimum_replicates": 1,
        "type": "all-development-cases-pass-v1",
    }
    request = solution_module._request(
        profile,
        {},
        proposer=Path("fixture-proposer.py"),
        coding_runtime_id="0" * 64,
    )
    assert request["stopping"] == profile["stopping"]


def test_agentvolve_stops_on_verified_goal_before_numeric_limit(
    tmp_path: Path,
) -> None:
    harness_root = tmp_path / "harness-evolution"
    run_experiment("fixture", harness_root, None, assay="coding-agent-v1")
    profile_path = _write_solution_profile(
        tmp_path / "goal-profile",
        max_rounds=3,
        max_proposal_calls=3,
        stop_on_goal=True,
    )
    solution_root = tmp_path / "solution-evolution"

    report = run_solution_experiment(
        "fixture",
        profile_path,
        solution_root,
        RUNTIME,
        harness_root / "selected-harness.json",
    )

    development = cast(dict[str, object], report["development"])
    final = cast(dict[str, object], report["final"])
    assert development["status"] == "development_goal_reached"
    assert development["completed_rounds"] == 1
    assert development["candidate_count"] == 2
    assert final["passed_count"] == final["task_count"] == 1
    final_development_round = [
        json.loads(line)
        for line in (solution_root / "state" / "driver.jsonl").read_text().splitlines()
    ][-1]
    assert final_development_round["next_allocation_record_id"] is None
    assert verify_solution_experiment(solution_root)["status"] == "verified"


def test_selected_harness_evolves_solution_commits_and_returns_verified_patch(
    tmp_path: Path,
) -> None:
    harness_root = tmp_path / "harness-evolution"
    run_experiment("fixture", harness_root, None, assay="coding-agent-v1")

    repository = tmp_path / "source"
    repository.mkdir()
    (repository / "solver.py").write_text(
        "def solve(left: int, right: int) -> int:\n    return left - right\n",
        encoding="utf-8",
    )
    run_git(["init", "--quiet"], cwd=repository)
    run_git(["add", "--all"], cwd=repository)
    tree = run_git(["write-tree"], cwd=repository).strip()
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
    }
    commit = run_git(
        ["commit-tree", tree],
        cwd=repository,
        input_text="seed\n",
        environment=environment,
    ).strip()
    run_git(["update-ref", "refs/heads/main", commit], cwd=repository)

    final_document = {
        "checks": [
            {
                "argv": [
                    "python",
                    "-c",
                    "from solver import solve; assert solve(41, -9) == 32",
                ],
                "case_id": "final-mixed",
                "timeout_ms": 10_000,
            },
            {
                "argv": [
                    "python",
                    "-c",
                    "from solver import solve; assert solve(-17, 6) == -11",
                ],
                "case_id": "final-negative",
                "timeout_ms": 10_000,
            },
        ],
        "final_schema": "darwinian-coding-final-v1",
        "schema_version": 1,
    }
    final_path = tmp_path / "protected-final.json"
    final_source = (canonical_json(final_document) + "\n").encode("ascii")
    final_path.write_bytes(final_source)
    profile = {
        "allocation_draws": [{"denominator": 1, "numerator": 0}],
        "allowed_paths": ["solver.py"],
        "development_checks": [
            {
                "argv": [
                    "python",
                    "-c",
                    "from solver import solve; assert solve(2, 3) == 5",
                ],
                "case_id": "development-positive",
                "timeout_ms": 10_000,
            },
            {
                "argv": [
                    "python",
                    "-c",
                    "from solver import solve; assert solve(-4, 7) == 3",
                ],
                "case_id": "development-negative",
                "timeout_ms": 10_000,
            },
        ],
        "final_assay": {
            "path": str(final_path.absolute()),
            "sha256": hashlib.sha256(final_source).hexdigest(),
        },
        "final_draw": {"denominator": 1, "numerator": 0},
        "goal": "Fix solver.py so solve returns left plus right.",
        "limits": {
            "max_proposal_calls": 2,
            "max_rounds": 2,
            "max_wall_seconds": 100_000,
        },
        "repository": {
            "base_commit": commit,
            "entrypoint": "solver.py",
            "path": str(repository.absolute()),
        },
        "schema_version": 1,
        "task_schema": "darwinian-coding-task-v1",
    }
    profile_path = tmp_path / "task.json"
    profile_path.write_text(
        canonical_json(profile) + "\n", encoding="ascii", newline=""
    )
    solution_root = tmp_path / "solution-evolution"
    report = run_solution_experiment(
        "fixture",
        profile_path,
        solution_root,
        RUNTIME,
        harness_root / "selected-harness.json",
    )
    final = cast(dict[str, object], report["final"])
    assert final["passed_count"] == final["task_count"] == 2
    assert final["selection_policy"] == "development-task-rate-reliability-v1"
    localized_descriptor = json.loads(
        (solution_root / "selected-harness.json").read_text(encoding="ascii")
    )
    assert localized_descriptor["descriptor_schema"] == (
        "selected-evolutionary-harness-v2"
    )
    assert localized_descriptor["artifact"]["repository"] == str(
        (harness_root / "candidate.git").absolute()
    )
    assert (solution_root / "harness.git").is_dir()
    selected = cast(dict[str, object], report["selected_solution"])
    selected_artifact = cast(dict[str, object], selected["artifact"])
    assert selected_artifact["commit"] != commit
    patch = (solution_root / "selected.patch").read_text(encoding="utf-8")
    assert "return left + right" in patch
    assert "return left - right" in (repository / "solver.py").read_text(
        encoding="utf-8"
    )
    (solution_root / "state" / "population" / "population.sqlite").unlink(
        missing_ok=True
    )
    verified = verify_solution_experiment(solution_root)
    assert verified["status"] == "verified"
    assert verified["mutation_receipt_count"] == 2
    assert solution_process_status(solution_root)["display"] == (
        "[6/6] Result ready for review"
    )
    (solution_root / "process-status.json").unlink()
    assert verify_solution_experiment(solution_root)["status"] == "verified"
    assert solution_process_status(solution_root)["display"] == (
        "[6/6] Result ready for review"
    )
    assert continue_solution_experiment(solution_root) == report
    assert (solution_root / "process-status.json").is_file()
    hidden_fragment = "solve(41, -9)"
    assert hidden_fragment not in (solution_root / "state" / "driver.jsonl").read_text(
        encoding="utf-8"
    )
    assert all(
        hidden_fragment not in path.read_text(encoding="utf-8")
        for path in (solution_root / "mutation-receipts").glob("*.json")
    )
    harness_path = solution_root / "selected-harness.json"
    harness_source = harness_path.read_bytes()
    harness_document = json.loads(harness_source)
    harness_document["provenance"]["final_passed_count"] = 0
    harness_path.write_text(
        canonical_json(harness_document) + "\n", encoding="ascii", newline=""
    )
    with pytest.raises(SolutionExperimentError, match="provenance changed identity"):
        verify_solution_experiment(solution_root)
    harness_path.write_bytes(harness_source)
    patch_path = solution_root / "selected.patch"
    original_patch = patch_path.read_bytes()
    patch_path.write_bytes(original_patch + b"tampered\n")
    with pytest.raises(SolutionExperimentError, match="patch does not replay"):
        verify_solution_experiment(solution_root)


def test_solution_resume_never_repeats_call_and_retry_requires_reserved_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness_root = tmp_path / "harness-evolution"
    run_experiment("fixture", harness_root, None, assay="coding-agent-v1")
    counter = tmp_path / "proposal-calls.txt"
    failing = tmp_path / "failing-proposer.py"
    failing.write_text(
        "import os,sys\n"
        "from pathlib import Path\n"
        "path=Path(os.environ['CODING_TEST_CALL_COUNTER'])\n"
        "path.write_text(path.read_text()+'x' if path.exists() else 'x')\n"
        "marker=Path(os.environ['METERING_GIT_REPOSITORY']).parent/'proposal.attempt'\n"
        "if marker.exists():\n"
        " os.execv(sys.executable,[sys.executable,os.environ['CODING_TEST_PROPOSER']])\n"
        "marker.write_text('failed-once')\n"
        "import subprocess\n"
        "payload=sys.stdin.buffer.read()\n"
        "subprocess.run([sys.executable,os.environ['CODING_TEST_PROPOSER']],"
        "input=payload,stdout=subprocess.DEVNULL,check=True)\n"
        "raise SystemExit(17)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODING_TEST_CALL_COUNTER", str(counter))
    original = solution_module.FIXTURE_PROPOSER
    monkeypatch.setenv("CODING_TEST_PROPOSER", str(original))
    monkeypatch.setattr(solution_module, "FIXTURE_PROPOSER", failing)

    exhausted_profile = _write_solution_profile(
        tmp_path / "exhausted-input", max_rounds=1, max_proposal_calls=1
    )
    exhausted_root = tmp_path / "exhausted-run"
    with pytest.raises(SolutionExperimentError, match="explicit retry required"):
        run_solution_experiment(
            "fixture",
            exhausted_profile,
            exhausted_root,
            RUNTIME,
            harness_root / "selected-harness.json",
        )
    assert counter.read_text() == "x"
    assert solution_process_status(exhausted_root)["display"] == (
        "[4/6] Evolving solution"
    )
    with pytest.raises(SolutionExperimentError, match="explicit retry required"):
        continue_solution_experiment(exhausted_root)
    assert counter.read_text() == "x"
    with pytest.raises(
        PopulationDriverError, match="proposal call limit forbids this retry"
    ):
        continue_solution_experiment(exhausted_root, retry_reason="reviewed retry")
    assert counter.read_text() == "x"
    assert not (exhausted_root / "protected-final.json").exists()

    reserved_profile = _write_solution_profile(
        tmp_path / "reserved-input", max_rounds=2, max_proposal_calls=3
    )
    reserved_root = tmp_path / "reserved-run"
    with pytest.raises(SolutionExperimentError, match="explicit retry required"):
        run_solution_experiment(
            "fixture",
            reserved_profile,
            reserved_root,
            RUNTIME,
            harness_root / "selected-harness.json",
        )
    assert counter.read_text() == "xx"
    with pytest.raises(SolutionExperimentError, match="explicit retry required"):
        continue_solution_experiment(reserved_root)
    assert counter.read_text() == "xx"
    report = continue_solution_experiment(
        reserved_root, retry_reason="operator reviewed transport failure"
    )
    retry_receipts = list((reserved_root / "state" / "retry-effects").glob("*.json"))
    assert len(retry_receipts) == 1
    retry_receipt = json.loads(retry_receipts[0].read_text(encoding="ascii"))
    assert retry_receipt["retry_effects_schema"] == "darwinian-coding-retry-effects-v2"
    assert len(retry_receipt["mutation_receipt_sha256"]) == 1
    retry_id = hashlib.sha256(retry_receipts[0].read_bytes()).hexdigest()
    driver_round = json.loads(
        (reserved_root / "state" / "driver.jsonl")
        .read_text(encoding="ascii")
        .splitlines()[1]
    )
    assert driver_round["attempts"][1]["reason"].endswith(
        f"\nretry-effects-sha256:{retry_id}"
    )
    assert cast(dict[str, object], report["final"])["passed_count"] == 1
    assert verify_solution_experiment(reserved_root)["status"] == "verified"
    retry_receipt["retry_effects_schema"] = "darwinian-coding-retry-effects-v1"
    retry_receipts[0].write_text(
        canonical_json(retry_receipt) + "\n", encoding="ascii", newline=""
    )
    with pytest.raises(SolutionExperimentError, match="schema was downgraded"):
        verify_solution_experiment(reserved_root)
