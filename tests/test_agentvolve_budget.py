"""Reject unfundable starts, preserve reservation semantics, and diagnose old runs."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json  # noqa: E402
from apps.coding_agent import agentvolve_worker as worker  # noqa: E402
from apps.coding_agent import experiment_config as config  # noqa: E402
from apps.coding_agent import experiment_runtime as runtime  # noqa: E402
from apps.coding_agent.operator_view import progress_view  # noqa: E402
from apps.coding_agent.preflight import preflight_task  # noqa: E402
from apps.coding_agent.protocol import CodingTaskError, load_task_profile  # noqa: E402
from apps.coding_agent.task_profile_tool import derive_profile, main  # noqa: E402
from apps.population_driver.population_driver_protocol import controller_timeout_seconds  # noqa: E402
from test_agentvolve_hardening import _profile, _write_document  # noqa: E402


def underfunded_profile(tmp_path):
    path = _profile(tmp_path / "task")
    document = json.loads(path.read_text())
    document["limits"].update(max_wall_seconds=1800, max_rounds=2, max_proposal_calls=2)
    document["allocation_draws"] = [{"numerator": 0, "denominator": 1}]
    _write_document(path, document)
    return path


def test_preflight_rejects_zero_round_budget_before_any_execution(tmp_path, monkeypatch):
    path = underfunded_profile(tmp_path)
    before = path.read_bytes()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("An unfundable task must fail before execution or protected-profile reads")

    for name in ("run_conformance", "localize_harness", "initialize_solution_repository", "run_population_driver"):
        monkeypatch.setattr(runtime, name, forbidden)
    monkeypatch.setattr("apps.coding_agent.preflight.load_final_profile", forbidden)
    with pytest.raises(CodingTaskError, match="wall_reservation_limit.*1800.*3680"):
        runtime.run_experiment("fixture", path, tmp_path / "run", ROOT / "apps/harness/profiles/runtime-fixture.json", tmp_path / "absent-harness.json")
    assert not (tmp_path / "run").exists()
    assert path.read_bytes() == before
    # Old profiles still load and keep their original identities for replay.
    assert load_task_profile(path)["limits"]["max_wall_seconds"] == 1800


def test_worker_refuses_budget_before_detaching_or_evolving_a_harness(tmp_path, monkeypatch):
    path = underfunded_profile(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Worker must not launch with an unfundable task")

    monkeypatch.setattr(worker, "_spawn_worker", forbidden)
    with pytest.raises(worker.AgentvolveWorkerError, match="wall_reservation_limit.*1800.*3680"):
        worker.start_workflow(tmp_path / "runs", path, ROOT / "apps/harness/profiles/runtime-fixture.json")
    assert list((tmp_path / "runs").iterdir()) == []


@pytest.mark.parametrize("timeouts", [[120000], [10000, 120000], [3600000, 120000]])
def test_budget_diagnostic_uses_exact_driver_reservations(tmp_path, timeouts):
    path = _profile(tmp_path / "task")
    profile = load_task_profile(path)
    profile["development_checks"] = [{"argv": ["python", "check.py"], "case_id": str(index), "timeout_ms": timeout} for index, timeout in enumerate(timeouts)]
    profile["limits"].update(max_rounds=2, max_proposal_calls=2, max_wall_seconds=100000)
    request = config.solution_driver_request(profile, {}, proposer=Path("fixture"), coding_runtime_id="0" * 64)
    expected = controller_timeout_seconds(request) + request["evidence_adapter"]["timeout_seconds"]
    budget = config.development_reservation(timeouts, 2, expected)
    assert budget["round_reservation_seconds"] == expected
    assert budget["requested_rounds_seconds"] == 2 * expected
    assert budget["funded_rounds_without_retries"] == 1
    profile["limits"]["max_wall_seconds"] = expected
    # A cap need not be fully funded: one affordable round is accepted, with a warning.
    result = preflight_task(profile)
    assert result["development_reservation"] == budget
    assert any("1 of 2" in warning for warning in result["warnings"])


@pytest.mark.parametrize("status", ["wall_reservation_limit", "candidate_cost_limit", "empty_archive"])
def test_no_archive_reports_driver_stop_without_entering_final(tmp_path, monkeypatch, status):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Final selection/copy/assay must not start without an archive")

    for name in ("select_final_candidate", "copy_protected_final_tasks", "run_final_assay"):
        monkeypatch.setattr(runtime, name, forbidden)
    development = {"archive_count": 0, "completed_rounds": 0, "proposal_calls": 0, "status": status}
    with pytest.raises(runtime.SolutionExperimentError, match=f"{status}.*0 completed rounds"):
        runtime._run_protected_final(tmp_path / "run", {}, development, "0" * 64)
    assert not (tmp_path / "run").exists()


def test_historical_zero_round_stop_is_diagnosed_without_rewriting_evidence(tmp_path, monkeypatch):
    profile = load_task_profile(underfunded_profile(tmp_path))
    root = tmp_path / "solution-pi-20260908T083239462Z"
    root.mkdir()
    _remote, artifact = runtime.initialize_solution_repository(root, profile)
    request = config.solution_driver_request(profile, artifact, proposer=config.ROOT / "connectors/fixed/pi/coding_proposer.py", coding_runtime_id="0" * 64)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No model call is authorized by this budget")

    monkeypatch.setattr("apps.population_driver.machine.run_json_process", forbidden)
    # Simulate a pre-upgrade run without routing through the new preflight.
    development = runtime.run_population_driver(canonical_json(request), root / "state")
    assert development["status"] == "wall_reservation_limit"
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    progress = progress_view(tmp_path, root.name, include_diff=False)
    assert "wall_reservation_limit" in progress["activity"]
    assert "3680" in progress["activity"] and "1800" in progress["activity"]
    assert progress["evolution"]["completed_rounds"] == 0
    assert progress["evolution"]["proposal_calls"] == 0
    with pytest.raises(runtime.SolutionExperimentError, match="wall_reservation_limit.*0 completed rounds"):
        runtime._run_protected_final(root, profile, development, "0" * 64)
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_derive_can_correct_budget_only_in_a_new_explicit_profile(tmp_path):
    path = underfunded_profile(tmp_path)
    original = path.read_bytes()
    final_path = Path(json.loads(original)["final_assay"]["path"])
    protected = final_path.read_bytes()
    goal = tmp_path / "goal.txt"
    goal.write_text("Solve the reviewed task")
    with pytest.raises(CodingTaskError, match="wall_reservation_limit"):
        derive_profile(path, goal, 2, tmp_path / "bad-output")
    assert list((tmp_path / "bad-output").glob("*.task.json")) == []
    result = derive_profile(path, goal, 2, tmp_path / "good-output", max_wall_seconds=7360)
    new = load_task_profile(Path(result["profile"]))
    assert new["limits"]["max_wall_seconds"] == 7360
    assert new["task_id"] != load_task_profile(path)["task_id"]
    assert path.read_bytes() == original and final_path.read_bytes() == protected
    assert new["development_checks"] == json.loads(original)["development_checks"]


def test_budget_cli_is_read_only_and_strict(tmp_path, capsys):
    path = tmp_path / "budget.json"
    document = {"check_timeouts_ms": [120000], "max_rounds": 2, "max_wall_seconds": 1800}
    path.write_text(canonical_json(document) + "\n")
    before = path.read_bytes()
    assert main(["budget", str(path)]) == 0
    output = capsys.readouterr()
    assert not output.err
    budget = json.loads(output.out)
    assert budget["round_reservation_seconds"] == 3680
    assert budget["requested_rounds_seconds"] == 7360
    assert budget["funded_rounds_without_retries"] == 0
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]
    for field, invalid in (("max_rounds", True), ("max_rounds", 2.0), ("max_wall_seconds", 0), ("check_timeouts_ms", []), ("check_timeouts_ms", [True]), ("extra", 1)):
        path.write_text(canonical_json({**document, field: invalid}) + "\n")
        assert main(["budget", str(path)]) == 2
        output = capsys.readouterr()
        assert not output.out and output.err
