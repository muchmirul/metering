"""Detached Agentvolve worker and read-only operator projection checks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.journal import content_record  # noqa: E402
from apps._support.wire import canonical_json  # noqa: E402
from apps.coding_agent import agentvolve_worker as worker  # noqa: E402
from apps.coding_agent.operator_view import (  # noqa: E402
    OperatorViewError,
    history_view,
    main,
    progress_view,
    trace_view,
)


def write_document(path: Path, document: dict[str, object]) -> None:
    path.write_text(canonical_json(document) + "\n", encoding="ascii")


def test_worker_preflight_rejects_malformed_task_before_launch(tmp_path: Path):
    task = tmp_path / "task.json"
    runtime = tmp_path / "runtime.json"
    write_document(task, {})
    write_document(runtime, {})
    with pytest.raises(worker.AgentvolveWorkerError, match="coding task"):
        worker._preflight_workflow(task, runtime, None)


def test_worker_launch_is_detached_and_operator_view_is_truthful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    runs = tmp_path / "runs"
    task = tmp_path / "task.json"
    runtime = tmp_path / "runtime.json"
    harness = tmp_path / "selected-harness.json"
    write_document(
        task,
        {
            "goal": "Improve behavior under independent checks",
            "limits": {"max_rounds": 3},
            "repository": {"path": str(tmp_path)},
            "task_id": "operator-test",
        },
    )
    write_document(
        runtime,
        {
            "model": {
                "connector": "pi",
                "model": "worker-model",
                "provider": "worker-provider",
                "reasoning": "high",
            }
        },
    )
    write_document(harness, {})

    launches: list[tuple[list[str], dict[str, object]]] = []

    class FakeProcess:
        pid = 43210

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        launches.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(worker.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(worker, "_preflight_workflow", lambda *_args: None)
    response = worker.start_workflow(runs, task, runtime, harness)
    workflow_root = Path(str(response["workflow_root"]))

    registry_lock = worker._open_registry_lock(runs)
    try:
        with pytest.raises(worker.AgentvolveWorkerError, match="launch is in progress"):
            worker.start_workflow(runs, task, runtime, harness)
    finally:
        registry_lock.close()

    assert response["state"] == "queued"
    assert launches[0][0][:4] == [
        worker.sys.executable,
        "-m",
        "apps.coding_agent.agentvolve_worker",
        "_work",
    ]
    assert launches[0][1]["start_new_session"] is True
    assert launches[0][1]["stdin"] is worker.subprocess.DEVNULL
    assert launches[0][1]["pass_fds"]
    assert worker._fresh_harness_command(runs / "h", runtime)[1:3] == [
        "-m",
        "apps.harness.experiment",
    ]
    assert worker._fresh_solution_command(runs / "s", task, runtime, harness)[1:3] == [
        "-m",
        "apps.coding_agent.solution_experiment",
    ]

    request = worker.load_workflow_request(workflow_root)
    solution_root = Path(str(request["solution_run_root"]))
    (solution_root / "state" / "pending").mkdir(parents=True)
    write_document(
        solution_root / "state" / "pending" / "round-intent.json",
        {"controller_receipt": None, "stage": "controller_pending"},
    )
    job_path = next((workflow_root / "jobs").glob("*.json"))
    job = worker._load_job(job_path)
    worker._write_status(
        workflow_root,
        request,
        job,
        state="waiting-retry",
        stage=4,
        activity="operator retry authorization is required",
        worker_pid=0,
    )

    progress = progress_view(runs, workflow_root.name, include_diff=False)
    assert progress["stage"] == 4
    assert progress["state"] == "waiting-retry"
    assert progress["authority"] == "projection-only"
    assert progress["worker"] == {
        "alive": False,
        "effect_pid": None,
        "model": {
            "connector": "pi",
            "model": "worker-model",
            "provider": "worker-provider",
            "reasoning": "high",
        },
        "pid": None,
        "separation": "detached-operator-worker-v1",
    }
    stages = progress["stages"]
    assert isinstance(stages, list)
    assert [stage["status"] for stage in stages] == [
        "complete",
        "reused",
        "reused",
        "waiting-retry",
        "pending",
        "pending",
    ]
    assert progress["diff"] is None

    history = history_view(runs)
    assert history["runs"][0]["name"] == workflow_root.name  # type: ignore[index]
    assert history["runs"][0]["state"] == "waiting-retry"  # type: ignore[index]


def test_worker_recovery_actions_enforce_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    runs = tmp_path / "runs"
    task = tmp_path / "task.json"
    runtime = tmp_path / "runtime.json"
    harness = tmp_path / "selected-harness.json"
    write_document(task, {})
    write_document(
        runtime,
        {
            "model": {
                "connector": "pi",
                "model": "model",
                "provider": "provider",
                "reasoning": "high",
            }
        },
    )
    write_document(harness, {})

    class FakeProcess:
        pid = 43210

    monkeypatch.setattr(
        worker.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess()
    )
    monkeypatch.setattr(worker, "_preflight_workflow", lambda *_args: None)
    response = worker.start_workflow(runs, task, runtime, harness)
    workflow_root = Path(str(response["workflow_root"]))
    request = worker.load_workflow_request(workflow_root)
    solution_root = Path(str(request["solution_run_root"]))
    (solution_root / "state" / "pending").mkdir(parents=True)
    first_job = worker._load_job(next((workflow_root / "jobs").glob("*.json")))
    worker._write_status(
        workflow_root,
        request,
        first_job,
        state="waiting-retry",
        stage=4,
        activity="retry required",
        worker_pid=0,
    )
    with pytest.raises(worker.AgentvolveWorkerError, match="pending indeterminate"):
        worker.launch_existing(workflow_root, "retry", "status alone is not authority")
    write_document(
        solution_root / "state" / "pending" / "round-intent.json",
        {"controller_receipt": None, "stage": "controller_pending"},
    )

    with pytest.raises(worker.AgentvolveWorkerError, match="explicit retry"):
        worker.launch_existing(workflow_root, "resume")
    jobs_before_lock_test = list((workflow_root / "jobs").glob("*.json"))
    held_lock = worker._open_lock(workflow_root)
    try:
        with pytest.raises(worker.AgentvolveWorkerError, match="live worker"):
            worker.launch_existing(
                workflow_root, "retry", "operator reviewed the interruption"
            )
    finally:
        held_lock.close()
    assert list((workflow_root / "jobs").glob("*.json")) == jobs_before_lock_test

    retry = worker.launch_existing(
        workflow_root, "retry", "operator reviewed the interruption"
    )
    assert retry["action"] == "retry"

    retry_job = worker._load_job(sorted((workflow_root / "jobs").glob("*.json"))[-1])
    write_document(
        solution_root / "experiment-report.json",
        {"schema": "darwinian-coding-experiment-v1"},
    )
    write_document(solution_root / "selected-solution.json", {})
    worker._write_status(
        workflow_root,
        request,
        retry_job,
        state="completed",
        stage=6,
        activity="result ready",
        worker_pid=0,
    )
    with pytest.raises(worker.AgentvolveWorkerError, match="pending indeterminate"):
        worker.launch_existing(workflow_root, "retry", "not applicable")
    with pytest.raises(worker.AgentvolveWorkerError, match="no effects to resume"):
        worker.launch_existing(workflow_root, "resume")
    assert worker.launch_existing(workflow_root, "verify")["action"] == "verify"


def test_history_pages_all_runs_and_progress_selects_newest(tmp_path: Path):
    runs = tmp_path / "runs"
    assert history_view(runs)["runs"] == []
    assert not runs.exists()
    runs.mkdir()
    for index in range(55):
        (runs / f"solution-pi-20260906T1900{index:02}000Z").mkdir()
    latest = runs / "solution-pi-20260906T190054000Z"
    write_document(latest / "experiment-report.json", {"schema": "darwinian-coding-experiment-v1"})
    first = history_view(runs)
    second = history_view(runs, 50)
    assert first["total_runs"] == 55
    assert first["next_offset"] == 50
    assert len(first["runs"]) == 50
    assert len(second["runs"]) == 5
    assert second["next_offset"] is None
    assert progress_view(runs, include_diff=False)["workflow_root"] == str(latest)
    assert progress_view(runs, include_diff=False)["state"] == "completed"
    assert len({run["name"] for page in (first, second) for run in page["runs"]}) == 55
    with pytest.raises(OperatorViewError, match="nonnegative"):
        history_view(runs, -1)
    with pytest.raises(OperatorViewError, match="direct child"):
        progress_view(runs, "../other")


def write_projection_ledger(root: Path, count: int) -> None:
    """Fixture projection evidence, not a Population experiment or replay claim."""
    (root / "state").mkdir(parents=True)
    records = [content_record({"kind": "header", "parent_record_id": None, "configuration": {"limits": {"max_rounds": count}}}, ValueError)]
    for index in range(1, count + 1):
        records.append(content_record({
            "kind": "round", "parent_record_id": records[-1]["record_id"],
            "round": index, "attempts": [{}, {}], "archive_member_candidate_ids": ["a"],
            "parent_candidate_id": f"parent-{index}", "child_candidate_id": f"child-{index}",
            "selection": {"decision": "retain_incumbent", "selected": f"parent-{index}", "comparison": {"incumbent": {"passed_count": 1}, "challenger": {"passed_count": 0}}},
        }, ValueError))
    (root / "state/driver.jsonl").write_text("".join(canonical_json(record) + "\n" for record in records), encoding="ascii")


def test_trace_pages_every_generation_and_rejects_corrupt_evidence(tmp_path: Path, capsys):
    root = tmp_path / "solution-pi-20260906T190000000Z"
    write_projection_ledger(root, 45)
    before = (root / "state/driver.jsonl").read_bytes()
    pages = [trace_view(tmp_path, root.name, offset) for offset in (0, 20, 40)]
    assert [len(page["rounds"]) for page in pages] == [20, 20, 5]
    assert [page["next_offset"] for page in pages] == [20, 40, None]
    assert [record["round"] for page in pages for record in page["rounds"]] == list(range(1, 46))
    assert pages[0]["authority"] == "projection-only"
    assert all(record["retries"] == 1 for page in pages for record in page["rounds"])
    assert (root / "state/driver.jsonl").read_bytes() == before
    assert main(["trace", str(tmp_path), root.name, "40"]) == 0
    assert '"total_rounds":45' in capsys.readouterr().out
    assert main(["history", str(tmp_path), "-1"]) == 2
    assert "nonnegative" in capsys.readouterr().err
    (root / "state/driver.jsonl").write_bytes(before.replace(b'parent-1', b'broken-1', 1))
    with pytest.raises(OperatorViewError, match="does not match"):
        trace_view(tmp_path, root.name)


def test_workflow_trace_keeps_both_levels_and_marks_reused_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    task, runtime = tmp_path / "task.json", tmp_path / "runtime.json"
    write_document(task, {})
    write_document(runtime, {"model": {"connector": "pi", "provider": "fixture", "model": "fixture", "reasoning": "off"}})
    monkeypatch.setattr(worker, "_preflight_workflow", lambda *_args: None)
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *_args, **_kwargs: type("Process", (), {"pid": 43210})())
    harness = tmp_path / "original-harness"
    write_projection_ledger(harness, 25)
    descriptor = harness / "selected-harness.json"
    write_document(descriptor, {})
    runs = tmp_path / "runs"
    response = worker.start_workflow(runs, task, runtime, descriptor)
    root = Path(str(response["workflow_root"]))
    request = worker.load_workflow_request(root)
    solution = Path(str(request["solution_run_root"]))
    write_projection_ledger(solution, 23)
    pages = [trace_view(runs, root.name, offset) for offset in (0, 20, 40)]
    experiments = pages[0]["experiments"]
    assert [(experiment["kind"], experiment["reused"]) for experiment in experiments] == [("harness", True), ("solution", False)]
    rows = [row for page in pages for row in page["rounds"]]
    assert len(rows) == 48
    assert [row["kind"] for row in rows] == ["harness"] * 25 + ["solution"] * 23
    assert len(history_view(runs)["runs"]) == 1  # owned child experiments are not duplicate workflow entries
