"""Session mode via the deployed Pi shim and a deterministic, network-free provider."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from test_agentvolve_goal import EXTENSION, ROOT, RPC

pytestmark = pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
PROVIDER = ROOT / "tests/fixtures/agentvolve_mode_provider.ts"


@contextmanager
def deployed(tmp_path: Path, *args: str, environment: dict | None = None):
    config = tmp_path / "pi-config"
    config.mkdir(exist_ok=True)
    process = subprocess.Popen(
        ["pi", "--mode", "rpc", "--offline", "--no-extensions", "--no-skills",
         "--no-context-files", "--no-prompt-templates", "-e", str(EXTENSION),
         "-e", str(PROVIDER), "--provider", "mode-fixture", "--model", "fixture",
         "--session-dir", str(tmp_path / "sessions"), *args], cwd=tmp_path,
        env={**os.environ, "PI_CODING_AGENT_DIR": str(config), "PI_OFFLINE": "1",
             "MODE_PROMPT_LOG": str(tmp_path / "prompts.jsonl"),
             "METERING_EVOLUTION_RUNS_DIR": str(tmp_path / "runs"),
             "METERING_EVOLUTION_TASKS_DIR": str(tmp_path / "tasks"), **(environment or {})},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        yield RPC(process)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        assert process.stderr is not None
        assert process.stderr.read() == b""


def talk(rpc: RPC, text: str) -> list[dict]:
    events = rpc.prompt(text)
    deadline = time.monotonic() + 30
    while not any(e.get("type") == "agent_settled" for e in events):
        events.append(rpc.event(deadline))
    assert not any(e.get("type") == "extension_error" for e in events), events
    assert not any(e.get("isError") for e in events), events
    return events


def check_prompt(tmp_path: Path, active: bool, excluded: set[str] = frozenset()):
    snapshot = json.loads((tmp_path / "prompts.jsonl").read_text().splitlines()[-1])
    assert ("operator mode is off for this session" in snapshot["prompt"]) is not active
    assert ("[AGENTVOLVE]" in snapshot["prompt"]) is active
    assert ("Never replace Agentvolve's immutable candidates" in snapshot["prompt"]) is active
    assert ("ordinary edits instead of Agentvolve" in snapshot["prompt"]) is active
    assert "workflow_deactivate" in snapshot["prompt"]
    assert {"read", "bash", "write", "edit", "darwinian_coding"} - excluded <= set(snapshot["tools"])
    assert not excluded & set(snapshot["tools"])


def modes(rpc: RPC) -> list[dict]:
    return [e["data"] for e in rpc.entries() if e.get("customType") == "agentvolve-mode"]


def state(rpc: RPC) -> dict:
    return rpc.request({"id": "state", "type": "get_state"})[-1]["data"]


@pytest.mark.parametrize("excluded", [set(), {"write", "edit"}])
def test_session_transitions_reload_resume_and_new_isolation(tmp_path: Path, excluded: set[str]):
    args = ["--exclude-tools", ",".join(sorted(excluded))] if excluded else []
    with deployed(tmp_path, *args) as rpc:
        commands = rpc.request({"id": "commands", "type": "get_commands"})[-1]["data"]["commands"]
        assert {c["name"] for c in commands if c.get("sourceInfo", {}).get("path") == str(EXTENSION)} == {"goal", "limit", "history", "progress"}
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False, excluded)
        assert modes(rpc) == []
        if not excluded:
            talk(rpc, "Write normal file")
            assert (tmp_path / "normal.txt").read_text() == "normal coding\n"
        rpc.prompt("/limit 7")
        # Missing/declined task preparation must still not launch a worker.
        for _ in range(2):
            talk(rpc, "Activate Agentvolve")
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, True, excluded)
        original = state(rpc)
        assert modes(rpc) == [{"active": True, "sessionId": original["sessionId"]}]
        first_user = next(e for e in rpc.entries() if e.get("type") == "message" and e["message"]["role"] == "user")
        rpc.prompt(f'/mode-test-tree {first_user["id"]}')
        rpc.prompt("/mode-test-reload")
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, True, excluded)
        rpc.request({"id": "new", "type": "new_session"})
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False, excluded)
        assert modes(rpc) == []
        rpc.request({"id": "resume", "type": "switch_session", "sessionPath": original["sessionFile"]})
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, True, excluded)
        configurations = [e for e in rpc.entries() if e.get("customType") == "agentvolve-workflow-configuration"]
        for _ in range(2):
            talk(rpc, "Deactivate Agentvolve")
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False, excluded)
        assert [m["active"] for m in modes(rpc)] == [True, False]
        assert [e for e in rpc.entries() if e.get("customType") == "agentvolve-workflow-configuration"] == configurations
        if not excluded:
            talk(rpc, "Edit normal file")
            assert (tmp_path / "normal.txt").read_text() == "normal edits\n"
        rpc.prompt("/mode-test-reload")
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False, excluded)
        # Navigating before the last mode record must not roll session mode back.
        active_entry = next(e for e in rpc.entries() if e.get("customType") == "agentvolve-mode" and e["data"]["active"])
        rpc.prompt(f'/mode-test-tree {active_entry["id"]}')
        rpc.prompt("/mode-test-reload")
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False, excluded)
    with deployed(tmp_path, "--session", original["sessionFile"], *args) as rpc:
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False, excluded)
        talk(rpc, "Activate Agentvolve")
        talk(rpc, "Inspect mode")
        rpc.request({"id": "clone", "type": "clone"})
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False, excluded)
        rpc.prompt("/mode-test-reload")
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False, excluded)
        talk(rpc, "Activate Agentvolve")
        talk(rpc, "Inspect mode")
        fork_point = [e for e in rpc.entries() if e.get("type") == "message" and e["message"]["role"] == "user"][-1]
        rpc.request({"id": "fork", "type": "fork", "entryId": fork_point["id"]})
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False, excluded)
    with deployed(tmp_path, "--fork", original["sessionFile"], *args) as rpc:
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False, excluded)
    assert not (tmp_path / "runs").exists()


def test_deactivation_allows_normal_edit_in_the_same_turn(tmp_path: Path):
    with deployed(tmp_path) as rpc:
        talk(rpc, "Write normal file")
        talk(rpc, "Activate Agentvolve")
        events = talk(rpc, "Deactivate Agentvolve then edit normal file")
        calls = [e["toolName"] for e in events if e.get("type") == "tool_execution_end"]
        assert calls == ["darwinian_coding", "edit"]
        assert (tmp_path / "normal.txt").read_text() == "normal edits\n"
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False)


def test_ephemeral_legacy_fork_stays_off_after_reload(tmp_path: Path):
    with deployed(tmp_path, "--no-session") as rpc:
        rpc.prompt("/mode-test-legacy")
        rpc.prompt("/mode-test-reload")
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, True)
        rpc.request({"id": "clone", "type": "clone"})
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False)
        rpc.prompt("/mode-test-reload")
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False)
        assert modes(rpc)[-1] == {"active": False, "sessionId": state(rpc)["sessionId"]}


def legacy_session(path: Path, active: bool, *, parent: bool = False, own: bool = False):
    header = {"type": "session", "version": 3, "id": "legacy-session", "cwd": str(path.parent), "timestamp": "2026-01-02T00:00:00.000Z"}
    if parent:
        header["parentSession"] = str(path.parent / "absent-parent.jsonl")
    records = [header,
        {"type": "custom", "id": "config", "parentId": None, "timestamp": "2026-01-01T00:00:00.000Z", "customType": "agentvolve-workflow-configuration", "data": {"goal": "pending goal", "maxRounds": 9}},
        {"type": "custom", "id": "mode", "parentId": "config", "timestamp": "2026-01-03T00:00:00.000Z" if own else "2026-01-01T00:00:00.000Z", "customType": "agentvolve-mode", "data": {"active": active, "modelMode": "routed"}}]
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


@pytest.mark.parametrize("active", [True, False])
@pytest.mark.parametrize("parent,own", [(False, False), (True, False), (True, True)])
def test_legacy_restore_both_values_and_fork_ownership(tmp_path: Path, active: bool, parent: bool, own: bool):
    session = tmp_path / "legacy.jsonl"
    legacy_session(session, active, parent=parent, own=own)
    with deployed(tmp_path, "--session", str(session)) as rpc:
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, active and (not parent or own))
        before = [e for e in rpc.entries() if e.get("customType") == "agentvolve-workflow-configuration"]
        talk(rpc, "Deactivate Agentvolve")
        rpc.prompt("/mode-test-reload")
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False)
        assert [e for e in rpc.entries() if e.get("customType") == "agentvolve-workflow-configuration"] == before


def wait_file(path: Path):
    deadline = time.monotonic() + 15
    while not path.exists():
        assert time.monotonic() < deadline, f"No monitor read: {path}"
        time.sleep(.02)


@pytest.mark.parametrize("late_error", [False, True])
@pytest.mark.parametrize("reactivate", [False, True])
def test_deactivation_invalidates_inflight_monitor_without_worker_effects(tmp_path: Path, late_error: bool, reactivate: bool):
    # A harmless standing process is a worker sentinel, not an evolution run.
    worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    runs = tmp_path / "runs"
    run = runs / "workflow-pi-20260906T190000000Z"
    run.mkdir(parents=True)
    status = {"authority": "projection-only", "stage": 1, "stage_label": "Task and runtime configured", "state": "queued", "status_schema": "agentvolve-worker-status-v1", "updated_unix_ns": time.time_ns(), "workflow_id": "sentinel", "worker_pid": worker.pid}
    (run / "worker-status.json").write_text(json.dumps(status))
    (run / "evidence.jsonl").write_text('{"untouched":"evidence sentinel"}\n')
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in run.iterdir()}
    # Only the monitor's read-only projection command is permitted. Its second
    # read waits for release, allowing deactivation and optionally a new epoch.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(f'''#!{sys.executable}
import json, pathlib, sys, time
root = pathlib.Path({str(tmp_path)!r})
with (root / "execs").open("a") as log: log.write(json.dumps(sys.argv[1:]) + "\\n")
assert sys.argv[1:6] == ["run", "python", "-m", "apps.coding_agent.operator_view", "progress"]
counter = root / "counter"
n = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(n))
if n == 2:
 (root / "waiting").touch()
 while not (root / "release").exists(): time.sleep(.02)
 if {late_error!r}: sys.exit(1)
from_result = json.loads((root / "projection.json").read_text())
if n == 2:
 for stage in from_result["stages"]: stage["status"] = "complete"
print(json.dumps(from_result))
''')
    uv.chmod(0o755)
    try:
        labels = ["Task and runtime configured", "Evolving harness", "Harness sealed", "Evolving solution", "Protected final assay", "Result ready for review"]
        projection = {"progress_schema": "agentvolve-progress-view-v1", "authority": "projection-only",
            "stage": 1, "state": "queued", "activity": "sentinel", "error": None,
            "workflow_id": "sentinel", "workflow_root": str(run), "updated_unix_ns": None, "warnings": [],
            "worker": {"alive": True, "pid": worker.pid, "effect_pid": None, "model": None, "separation": "detached"},
            "stages": [{"number": n, "label": label, "status": "complete" if n == 1 else "pending", "summary": "sentinel"} for n, label in enumerate(labels, 1)],
            "evolution": None, "diff": None, "task": None, "result": None}
        (tmp_path / "projection.json").write_text(json.dumps(projection))
        with deployed(tmp_path, environment={"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}) as rpc:
            talk(rpc, "Activate Agentvolve")
            wait_file(tmp_path / "waiting")
            talk(rpc, "Deactivate Agentvolve")
            count = len((tmp_path / "execs").read_text().splitlines())
            if reactivate:
                talk(rpc, "Activate Agentvolve")
            (tmp_path / "release").touch()
            time.sleep(.3)
            events = talk(rpc, "Inspect mode")
            check_prompt(tmp_path, reactivate)
            assert [e["data"]["stage"] for e in rpc.entries() if e.get("customType") == "agentvolve-stage-report"] == [1]
            if reactivate:
                assert not any(e.get("method") == "setWidget" and "widgetLines" not in e for e in events)
            assert not any("Agentvolve finished" in e.get("message", "") for e in events)
            if not reactivate:
                time.sleep(2.2)
                events += rpc.request({"id": "drain", "type": "get_state"})
                assert len((tmp_path / "execs").read_text().splitlines()) == count
                assert not any(e.get("method") == "setWidget" and "widgetLines" in e for e in events)
            assert worker.poll() is None
            assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in run.iterdir()} == before
    finally:
        worker.terminate()
        worker.wait(timeout=10)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFO")
@pytest.mark.parametrize("late_error", [False, True])
def test_deactivation_during_initial_status_read_cannot_restart_monitor(tmp_path: Path, late_error: bool):
    run = tmp_path / "runs/workflow-pi-20260906T190000000Z"
    run.mkdir(parents=True)
    fifo = run / "worker-status.json"
    os.mkfifo(fifo)
    with deployed(tmp_path) as rpc:
        # Pi executes sibling tools concurrently: activation blocks in its first
        # status read while deactivation invalidates the pending monitor start.
        events = rpc.prompt("Race mode calls")
        deadline = time.monotonic() + 15
        while not any(e.get("type") == "tool_execution_end" and e.get("result", {}).get("details", {}).get("active") is False for e in events):
            events.append(rpc.event(deadline))
        while True:
            try:
                fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                break
            except OSError:
                assert time.monotonic() < deadline, "Activation did not open status FIFO"
                time.sleep(.01)
        try:
            status = {"authority": "projection-only", "stage": 6, "stage_label": "Result ready for review", "state": "queued", "status_schema": "agentvolve-worker-status-v1", "updated_unix_ns": time.time_ns(), "workflow_id": "late"}
            os.write(fd, b"malformed" if late_error else json.dumps(status).encode())
        finally:
            os.close(fd)
        while not any(e.get("type") == "agent_settled" for e in events):
            events.append(rpc.event(deadline))
        activation = [e for e in events if e.get("type") == "tool_execution_end" and "superseded" in json.dumps(e)]
        assert activation and activation[-1]["result"]["details"]["active"] is False
        talk(rpc, "Inspect mode")
        check_prompt(tmp_path, False)
        time.sleep(2.2)
        after = rpc.request({"id": "drain", "type": "get_state"})
        assert not any(e.get("method") in {"setStatus", "setWidget"} for e in after)
        assert [m["active"] for m in modes(rpc)] == [True, False]
        assert not [e for e in rpc.entries() if e.get("customType") == "agentvolve-stage-report"]
        # A leaked timer would open the FIFO again and leave a waiting reader.
        with pytest.raises(OSError):
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
