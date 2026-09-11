"""Registry recovery must preserve evidence and never grant an implicit retry."""

import signal
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.coding_agent import agentvolve_worker as worker  # noqa: E402
from apps.coding_agent.operator_view import history_view, progress_view  # noqa: E402
from test_agentvolve_operator import write_document  # noqa: E402


@pytest.fixture
def launch(tmp_path, monkeypatch):
    task, runtime, harness = (tmp_path / name for name in ("task.json", "runtime.json", "selected-harness.json"))
    write_document(task, {})
    write_document(runtime, {"model": {"connector": "pi", "provider": "fixture", "model": "fixture", "reasoning": "off"}})
    write_document(harness, {})
    monkeypatch.setattr(worker, "_preflight_workflow", lambda *_args: None)
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *_args, **_kwargs: type("Process", (), {"pid": 43210})())
    return lambda: worker.start_workflow(tmp_path / "runs", task, runtime, harness)


def test_legacy_history_does_not_own_the_detached_registry(tmp_path, launch):
    runs = tmp_path / "runs"
    legacy = runs / "harness-pi-20260902T200200234Z"
    legacy.mkdir(parents=True)
    evidence = legacy / "old-evidence.txt"
    evidence.write_bytes(b"An interrupted experiment is not a completed one.\n")
    response = launch()
    assert response["state"] == "queued"
    assert response["legacy_unfinished_count"] == 1
    assert list(legacy.iterdir()) == [evidence]
    assert evidence.read_bytes() == b"An interrupted experiment is not a completed one.\n"
    assert {run["name"] for run in history_view(runs)["runs"]} == {legacy.name, Path(response["workflow_root"]).name}


def test_registry_inspection_is_read_only(tmp_path, launch):
    runs = tmp_path / "runs"
    assert worker.registry_status(runs)["blocker"] is None
    assert not runs.exists()
    root = Path(launch()["workflow_root"])
    (root / "worker.lock").unlink()
    before = {path: path.read_bytes() for path in runs.rglob("*") if path.is_file()}
    view = worker.registry_status(runs)
    assert view["blocker"]["workflow_root"] == str(root)
    assert view["blocker"]["active"] is False
    assert {path: path.read_bytes() for path in runs.rglob("*") if path.is_file()} == before


def test_unfinished_workflow_requires_explicit_close_and_cannot_restart(tmp_path, launch):
    root = Path(launch()["workflow_root"])
    with pytest.raises(worker.AgentvolveWorkerError, match="unfinished Agentvolve workflow"):
        launch()
    request = worker.load_workflow_request(root)
    solution = Path(request["solution_run_root"])
    pending = solution / "state/pending/round-intent.json"
    pending.parent.mkdir(parents=True)
    write_document(pending, {"stage": "controller_pending", "controller_receipt": None})
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    pending_before = pending.read_bytes()
    assert worker.workflow_control_state(root)["retry_required"] is True
    response = worker.close_workflow(root, "Operator gives up this task; keep its failed evidence")
    assert response["state"] == "closed-incomplete"
    assert worker.registry_status(tmp_path / "runs")["blocker"] is None
    assert all(path.read_bytes() == payload for path, payload in before.items())
    assert pending.read_bytes() == pending_before
    assert not (solution / "experiment-report.json").exists()
    assert not (root / "workflow-report.json").exists()
    assert worker.load_workflow_closure(root)["workflow_id"] == request["workflow_id"]
    assert progress_view(tmp_path / "runs", root.name, include_diff=False)["state"] == "closed-incomplete"
    for action, reason in (("resume", None), ("retry", "one more try"), ("verify", None)):
        with pytest.raises(worker.AgentvolveWorkerError, match="closed as incomplete"):
            worker.launch_existing(root, action, reason)
    with pytest.raises(worker.AgentvolveWorkerError, match="already closed"):
        worker.close_workflow(root, "replacement reason")
    assert launch()["state"] == "queued"


def test_closure_before_first_status_is_visible_in_history(tmp_path, launch):
    root = Path(launch()["workflow_root"])
    (root / "worker-status.json").unlink()
    worker.close_workflow(root, "Startup failed before writing status")
    assert not (root / "worker-status.json").exists()
    assert history_view(tmp_path / "runs")["runs"][0]["state"] == "closed-incomplete"
    progress = progress_view(tmp_path / "runs", root.name, include_diff=False)
    assert progress["state"] == "closed-incomplete"
    assert all(stage["status"] != "running" for stage in progress["stages"])


def test_live_locks_still_block_start_and_close(tmp_path, launch):
    root = Path(launch()["workflow_root"])
    lock = worker._open_lock(root)
    try:
        assert worker.workflow_control_state(root)["active"] is True
        with pytest.raises(worker.AgentvolveWorkerError, match="active"):
            launch()
        with pytest.raises(worker.AgentvolveWorkerError, match="live worker"):
            worker.close_workflow(root, "Cannot close running work")
        assert not (root / "closed.json").exists()
    finally:
        lock.close()


def test_process_tree_stop_escalates_identity_checked_groups(monkeypatch):
    live = {100: "worker", 200: "effect"}
    signals = []
    monkeypatch.setattr(worker, "_process_start_token", lambda pid: live.get(pid))
    monkeypatch.setattr(worker.os, "getpgid", lambda pid: pid)

    def killpg(pid, sent):
        signals.append((pid, sent))
        if sent == signal.SIGKILL:
            live.pop(pid, None)

    monkeypatch.setattr(worker.os, "killpg", killpg)
    assert worker._terminate_process_groups(100, "worker", 200, "effect", grace_seconds=0) is True
    assert signals == [
        (200, signal.SIGTERM), (100, signal.SIGTERM),
        (200, signal.SIGKILL), (100, signal.SIGKILL),
    ]


def test_stop_workflow_waits_for_tree_and_records_terminal_state(tmp_path, launch, monkeypatch):
    root = Path(launch()["workflow_root"])
    request = worker.load_workflow_request(root)
    job = worker._load_job(next((root / "jobs").glob("*.json")))
    monkeypatch.setattr(worker, "_process_start_token", lambda pid: "worker-token" if pid == 43210 else None)
    worker._write_status(root, request, job, state="running", stage=4,
                         activity="running", effect_pid=9876, worker_pid=43210)
    monkeypatch.setattr(worker, "_worker_alive", lambda *_: True)
    calls = []
    monkeypatch.setattr(worker, "_terminate_process_groups",
                        lambda *args: calls.append(args) or True)

    response = worker.stop_workflow(root)

    assert response["state"] == "stopped"
    assert calls == [(43210, "worker-token", 9876, None)]
    status = worker.load_worker_status(root)
    assert status["state"] == "stopped"
    assert status["worker_pid"] is None and status["effect_pid"] is None
    assert status["error"] == "forced termination after grace period"


@pytest.mark.parametrize("reason", ["", " ", "bad\x00reason", "x" * 2001, None, 1])
def test_close_requires_bounded_operator_reason(tmp_path, launch, reason):
    root = Path(launch()["workflow_root"])
    with pytest.raises(worker.AgentvolveWorkerError, match="reason"):
        worker.close_workflow(root, reason)
    assert not (root / "closed.json").exists()


def test_close_rejects_completed_work_and_unsafe_or_tampered_closure(tmp_path, launch):
    root = Path(launch()["workflow_root"])
    request = worker.load_workflow_request(root)
    solution = Path(request["solution_run_root"])
    solution.mkdir()
    write_document(solution / "experiment-report.json", {"schema": "darwinian-coding-experiment-v1"})
    write_document(solution / "selected-solution.json", {})
    with pytest.raises(worker.AgentvolveWorkerError, match="completed"):
        worker.close_workflow(root, "Not incomplete")
    (solution / "experiment-report.json").unlink()
    target = tmp_path / "outside"
    target.write_text("untouched")
    (root / "closed.json").symlink_to(target)
    with pytest.raises(worker.AgentvolveWorkerError, match="symbolic link"):
        worker.close_workflow(root, "No symlinks")
    assert target.read_text() == "untouched"
    (root / "closed.json").unlink()
    worker.close_workflow(root, "Keep history")
    closure = worker.load_workflow_closure(root)
    closure["workflow_id"] = "another-workflow"
    write_document(root / "closed.json", closure)
    with pytest.raises(worker.AgentvolveWorkerError, match="closure"):
        launch()
