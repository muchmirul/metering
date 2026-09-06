"""Detached Agentvolve worker and read-only operator projection checks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json  # noqa: E402
from apps.coding_agent import agentvolve_worker as worker  # noqa: E402
from apps.coding_agent.operator_view import history_view, progress_view  # noqa: E402


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
