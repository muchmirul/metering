"""Deployed Pi job adapter with deterministic model/worker boundary doubles."""
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
from test_workspace_profile import workspace_draft

pytestmark = pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
PROVIDER = ROOT / "tests/fixtures/agentvolve_job_provider.ts"
NAME = "workflow-pi-20260906T190000000Z"
LABELS = ["Task and runtime configured", "Evolving harness", "Harness sealed", "Evolving solution", "Protected final assay", "Result ready for review"]


@contextmanager
def deployed(tmp_path, *args, environment=None):
    config = tmp_path / "interactive-config"
    config.mkdir(exist_ok=True)
    process = subprocess.Popen(
        ["pi", "--mode", "rpc", "--offline", "--no-extensions", "--no-skills", "--no-context-files",
         "--no-prompt-templates", "-e", str(EXTENSION), "-e", str(PROVIDER), "--provider", "job-fixture",
         "--model", "fixture", "--session-dir", str(tmp_path / "sessions"), *args], cwd=tmp_path,
        env={**{k: v for k, v in os.environ.items() if not k.startswith("METERING_EVOLUTION_") and k != "METERING_PI_CONFIG_DIR"},
             "PI_CODING_AGENT_DIR": str(config), "PI_OFFLINE": "1", "JOB_PROMPT_LOG": str(tmp_path / "prompts.jsonl"),
             "METERING_EVOLUTION_RUNS_DIR": str(tmp_path / "runs"), "METERING_EVOLUTION_TASKS_DIR": str(tmp_path / "tasks"), **(environment or {})},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        yield RPC(process)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        assert process.stderr.read() == b""


def talk(rpc, text, *, error=False, dialog=None):
    events = rpc.prompt(text, dialog)
    deadline = time.monotonic() + 30
    while not any(e.get("type") == "agent_settled" for e in events):
        event = rpc.event(deadline)
        events.append(event)
        if event.get("method") in {"input", "select", "confirm", "editor"}:
            rpc.send({"type": "extension_ui_response", "id": event["id"], **(dialog(event) if dialog else {"cancelled": True})})
    assert not any(e.get("type") == "extension_error" for e in events), events
    if not error:
        assert not any(e.get("isError") for e in events), events
    return events


def result(events):
    return [e["result"] for e in events if e.get("type") == "tool_execution_end"][-1]


def ordinary(rpc, tmp_path):
    for tool in ("Write", "Read", "Edit", "Bash"):
        events = talk(rpc, f"{tool} normal file")
        assert [e["toolName"] for e in events if e.get("type") == "tool_execution_end"] == [tool.lower()]
    assert (tmp_path / "normal.txt").read_text() == "normal edits\n"
    assert (tmp_path / "bash.txt").read_text() == "ordinary bash\n"
    snapshot = json.loads((tmp_path / "prompts.jsonl").read_text().splitlines()[-1])
    assert "All old activation/deactivation messages, operator-only restrictions and mode entries are historical" in snapshot["prompt"]
    assert {"read", "write", "edit", "bash", "darwinian_coding"} <= set(snapshot["tools"])


def submission(rpc):
    return [e["data"] for e in rpc.entries() if e.get("customType") == "agentvolve-submission"][-1]


def projection(root, identity="a" * 64, state="running"):
    return {"progress_schema": "agentvolve-progress-view-v1", "authority": "projection-only", "stage": 4,
            "stage_label": "[4/6] Evolving solution", "state": state, "activity": "bound fixture", "error": None,
            "workflow_id": identity, "workflow_root": str(root), "updated_unix_ns": None, "warnings": [],
            "worker": {"alive": state == "running", "pid": 12345, "effect_pid": None,
                       "model": {"connector": "pi-v1", "provider": "worker-provider", "model": "pinned-worker", "reasoning": "medium"}, "separation": "detached"},
            "stages": [{"number": n, "label": label, "status": "complete" if state == "completed" or n == 1 else "pending", "summary": "fixture"} for n, label in enumerate(LABELS, 1)],
            "evolution": None, "diff": None, "task": None, "result": None}


@pytest.fixture
def boundary(tmp_path):
    """Only fixed execution/review/projection boundaries are doubled; registration is real."""
    document, _, _ = workspace_draft(tmp_path)
    document["limits"]["max_wall_seconds"] = 100000
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(document))
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({"model": {"provider": "worker-provider", "model": "pinned-worker", "reasoning": "medium"}}))
    harness = tmp_path / "selected-harness.json"
    harness.write_text("sealed fixture boundary\n")
    config = tmp_path / "worker-config"
    config.mkdir()
    (config / "models.json").write_text('{"providers":{}}')
    (config / "auth.json").write_text('{"fixture":{"key":"PRIVATE_WORKER_TOKEN"}}')
    root = tmp_path / "runs" / NAME
    (tmp_path / "projection.json").write_text(json.dumps(projection(root)))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(f'''#!{sys.executable}
import hashlib, json, os, pathlib, sys, time
base = pathlib.Path({str(tmp_path)!r})
args = sys.argv[1:]
with (base / "execs").open("a") as log: log.write(json.dumps(args) + "\\n")
action = args[4] if len(args) > 4 else ""
module = args[3] if len(args) > 3 else ""
if module == "connectors.fixed.pi.runtime":
 if action == "discover-configured":
  source = base / "setup-catalogue.json"
  print(source.read_text() if source.exists() else json.dumps({{"setup_schema":"agentvolve-setup-discovery-v1", "authority":"diagnostic-only", "options":[], "issues":[], "truncated":False}}))
 elif action == "review-configured":
  if (base / "review-failure").exists(): sys.exit("incompatible reviewed runtime/harness")
  if (base / "review-pause").exists():
   (base / "review-waiting").touch()
   deadline = time.monotonic() + 20
   while not (base / "review-release").exists():
    if time.monotonic() > deadline: sys.exit("fixture review pause expired")
    time.sleep(.02)
  print(json.dumps({{"review_schema":"agentvolve-execution-review-v1", "authority":"diagnostic-only", "runtime_id":"b"*64, "harness_candidate_id":"c"*64, "harness_descriptor_sha256":hashlib.sha256(pathlib.Path(args[6]).read_bytes()).hexdigest(), "worker_configuration":args[7], "worker_models_sha256":hashlib.sha256((pathlib.Path(args[7]) / "models.json").read_bytes()).hexdigest(), "command":["/stable/pi-0.84.4"], "model":{{"connector":"pi-v1", "provider":"worker-provider", "model":"pinned-worker", "implementation_version":"0.84.4", "reasoning":"medium"}}}}))
 elif action == "ready-configured":
  if (base / "model-unready").exists(): sys.exit("Model not loaded. Arrange safe startup separately; no service restart performed.")
  print(json.dumps({{"readiness_schema":"agentvolve-worker-readiness-v1", "authority":"diagnostic-only", "provider":"llamacpp", "model":"local", "state":"ready", "inference_performed":False}}))
 elif action == "check": print('{{}}')
 elif action == "start-configured":
  approved = json.loads(pathlib.Path(args[10]).read_text())
  assert approved["worker_configuration"] == args[9]
  (base / "dispatch-record.json").write_text(json.dumps({{"args":args, "approved":approved}}))
  (base / "dispatched").touch()
  if (base / "dispatch-failure").exists(): sys.exit("dispatch acknowledgement lost")
  root = pathlib.Path(args[5]) / {NAME!r}
  root.mkdir(parents=True, exist_ok=True)
  (root / "evidence.jsonl").write_text('immutable fixture evidence\\n')
  response = {{"worker_response_schema":"agentvolve-worker-response-v1", "action":"start", "pid":12345, "state":"queued", "workflow_id":"a"*64, "workflow_root":str(root)}}
  if (base / "ack-override.json").exists(): response.update(json.loads((base / "ack-override.json").read_text()))
  print(json.dumps(response))
 else: raise AssertionError(args)
elif module == "apps.coding_agent.agentvolve_worker":
 if action == "registry": print(json.dumps({{"registry_schema":"agentvolve-registry-status-v1", "authority":"projection-only", "blocker":None, "legacy_unfinished_count":0}}))
 elif action == "verify":
  print(json.dumps({{"worker_response_schema":"agentvolve-worker-response-v1", "action":"verify", "pid":12345, "state":"queued", "workflow_id":"a"*64, "workflow_root":args[5]}}))
 else: raise AssertionError(args)
elif module == "apps.coding_agent.operator_view":
 if action == "progress":
  assert len(args) == 7, "Implicit latest selection forbidden"
  value = json.loads((base / "projection.json").read_text())
  if (base / "pause").exists():
   (base / "waiting").touch()
   while not (base / "release").exists(): time.sleep(.02)
   for stage in value["stages"]: stage["status"] = "complete"
   if (base / "late-error").exists(): sys.exit("late error")
  if not pathlib.Path(args[6]).exists(): sys.exit("referenced job missing")
  value["workflow_root"] = args[6]
  print(json.dumps(value))
 elif action == "trace": print(json.dumps({{"authority":"projection-only", "trace_schema":"agentvolve-trace-view-v1", "workflow_root":args[6], "offset":0,"page_size":20,"total_rounds":0,"next_offset":None,"experiments":[],"rounds":[]}}))
 else: raise AssertionError(args)
else: os.execv({shutil.which('uv')!r}, [{shutil.which('uv')!r}, *args])
''')
    uv.chmod(0o755)
    return {"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"], "JOB_DRAFT": str(draft),
            "METERING_EVOLUTION_RUNTIME_MANIFEST": str(runtime), "METERING_EVOLUTION_HARNESS_DESCRIPTOR": str(harness),
            "METERING_PI_CONFIG_DIR": str(config)}


def approve(event):
    if event["method"] == "input":
        assert event["title"].startswith("Enter the exact")
        return {"value": "1"}
    assert event["method"] == "confirm", event
    assert "1 generations, 1 proposal calls" in event["message"]
    for text in ("Interactive drafting only: job-fixture/fixture", "pinned-worker", "worker-provider", "0.84.4", "Reused verified harness", "No Level-2 search", "private per-job directory"):
        assert text in event["message"]
    return {"confirmed": True}


def bind(rpc, root, *, pid=12345):
    root.mkdir(parents=True, exist_ok=True)
    data = {"schema": "agentvolve-submission-v1", "attemptId": "fixture-attempt", "state": "launched",
            "workflow": {"worker_response_schema": "agentvolve-worker-response-v1", "action": "start", "pid": pid,
                         "state": "queued", "workflow_id": "a" * 64, "workflow_root": str(root)}}
    rpc.prompt("/job-test-record " + json.dumps(data))
    rpc.prompt("/job-test-reload")


def test_real_submission_tracks_exact_job_not_newer_or_older_and_preserves_tools(tmp_path, boundary):
    with deployed(tmp_path, environment=boundary) as rpc:
        ordinary(rpc, tmp_path)
        rpc.prompt("/limit 17")
        rpc.prompt("/goal Produce the reviewed output, at most one generation", approve)
        job = submission(rpc)
        assert job["state"] == "launched"
        root = Path(job["workflow"]["workflow_root"])
        evidence = (root / "evidence.jsonl").read_bytes()
        profile = next((tmp_path / "tasks").glob("*.task.json"))
        frozen_profile = profile.read_bytes()
        assert json.loads(frozen_profile)["limits"]["max_rounds"] == 1
        newer = tmp_path / "runs/workflow-pi-20260909T190000000Z"
        newer.mkdir()
        older = tmp_path / "runs/workflow-pi-20260901T190000000Z"
        older.mkdir()
        ordinary(rpc, tmp_path)
        assert result(talk(rpc, "Job status"))["details"]["workflow_root"] == str(root)
        rpc.prompt("/history " + newer.name)
        assert submission(rpc) == job
        assert result(talk(rpc, "Verify job"))["details"]["workflow_root"] == str(root)
        rpc.request({"id": "model", "type": "set_model", "provider": "job-fixture", "modelId": "other"})
        assert result(talk(rpc, "Job status"))["details"]["worker"]["model"]["model"] == "pinned-worker"
        (tmp_path / "projection.json").write_text(json.dumps(projection(root, state="completed")))
        ordinary(rpc, tmp_path)
        assert result(talk(rpc, "Job status"))["details"]["state"] == "completed"
        rpc.prompt("/goal New request cancelled")
        assert submission(rpc)["state"] == "not-launched"
        assert "not-launched" in result(talk(rpc, "Job status"))["content"][0]["text"]
        rpc.prompt("/progress")
        ordinary(rpc, tmp_path)
        assert (root / "evidence.jsonl").read_bytes() == evidence
        assert profile.read_bytes() == frozen_profile
        calls = [json.loads(line) for line in (tmp_path / "execs").read_text().splitlines()]
        assert len([a for a in calls if a[3:5] == ["connectors.fixed.pi.runtime", "start-configured"]]) == 1
        assert [a[5] for a in calls if a[3:5] == ["apps.coding_agent.agentvolve_worker", "verify"]] == [str(root)]


@pytest.mark.parametrize("override", [{"workflow_id": "not-an-id"}, {"workflow_root": "/unrelated/workflow-pi-20260906T190000000Z"}, {"pid": 0}, {"action": "verify"}, {"state": "completed"}])
def test_malformed_launch_acknowledgement_cannot_bind_or_inherit(tmp_path, boundary, override):
    with deployed(tmp_path, environment=boundary) as rpc:
        bind(rpc, tmp_path / "runs" / NAME)
        (tmp_path / "ack-override.json").write_text(json.dumps(override))
        rpc.prompt("/goal A fresh requested job", approve)
        assert submission(rpc)["state"] == "uncertain-dispatch"
        assert "workflow" not in submission(rpc)
        assert result(talk(rpc, "Job status"))["details"]["state"] == "uncertain-dispatch"
        ordinary(rpc, tmp_path)


def test_review_identity_change_before_dispatch_requires_fresh_approval(tmp_path, boundary):
    def change_after_review(event):
        answer = approve(event)
        if event["method"] == "confirm":
            Path(boundary["METERING_EVOLUTION_HARNESS_DESCRIPTOR"]).write_text("changed after review")
        return answer
    with deployed(tmp_path, environment=boundary) as rpc:
        events = rpc.prompt("/goal A reviewed task", change_after_review)
        assert any("configuration changed during review" in e.get("message", "") for e in events)
        assert submission(rpc)["state"] == "not-launched"
        assert not (tmp_path / "dispatched").exists()
        ordinary(rpc, tmp_path)


def test_goal_without_text_records_failure_instead_of_showing_previous_job(tmp_path, boundary):
    with deployed(tmp_path, environment=boundary) as rpc:
        bind(rpc, tmp_path / "runs" / NAME)
        rpc.prompt("/goal")
        assert submission(rpc)["state"] == "not-launched"
        assert "workflow" not in submission(rpc)
        assert "Usage: /goal" in result(talk(rpc, "Job status"))["content"][0]["text"]
        assert not (tmp_path / "dispatched").exists()


@pytest.mark.parametrize("initial", ["preparing", "uncertain-dispatch"])
def test_interrupted_submission_restores_without_restarting(tmp_path, boundary, initial):
    with deployed(tmp_path, environment=boundary) as rpc:
        data = {"schema": "agentvolve-submission-v1", "attemptId": "interrupted", "state": initial}
        rpc.prompt("/job-test-record " + json.dumps(data))
        rpc.prompt("/job-test-reload")
        assert result(talk(rpc, "Job status"))["details"]["state"] == ("not-launched" if initial == "preparing" else initial)
        assert not (tmp_path / "dispatched").exists()
        ordinary(rpc, tmp_path)


@pytest.mark.parametrize("failure,state", [("review-failure", "failed"), ("dispatch-failure", "uncertain-dispatch"), ("cancel-review", "cancelled")])
def test_new_failed_or_cancelled_request_never_reports_old_result(tmp_path, boundary, failure, state):
    root = tmp_path / "runs" / NAME
    with deployed(tmp_path, environment=boundary) as rpc:
        bind(rpc, root)
        if failure != "cancel-review":
            (tmp_path / failure).touch()
        rpc.prompt("/goal A new requested job", lambda e: {"confirmed": False} if failure == "cancel-review" and e["method"] == "confirm" else {"cancelled": True} if e["method"] == "select" else approve(e))
        assert submission(rpc)["state"] == state
        assert "workflow" not in submission(rpc)
        assert result(talk(rpc, "Job status"))["details"]["state"] == state
        assert any(e.get("isError") for e in talk(rpc, "Verify job", error=True))
        ordinary(rpc, tmp_path)
        rpc.prompt("/job-test-reload")
        assert result(talk(rpc, "Job status"))["details"]["state"] == state
        assert (tmp_path / "dispatched").exists() is (failure == "dispatch-failure")


def test_restore_resume_tree_fork_and_legacy_output_do_not_restrict_main_pi(tmp_path, boundary):
    root = tmp_path / "runs" / NAME
    with deployed(tmp_path, environment=boundary) as rpc:
        rpc.prompt("/job-test-legacy")
        bind(rpc, root)
        ordinary(rpc, tmp_path)
        original = rpc.request({"id": "state", "type": "get_state"})[-1]["data"]
        rpc.prompt("/job-test-tools")
        metadata = [e["data"] for e in rpc.entries() if e.get("customType") == "job-test-tools"][-1]
        coding = next(t for t in metadata if t["name"] == "darwinian_coding")
        assert coding["parameters"]["properties"]["action"]["enum"] == ["workflow_from_session", "workflow_start", "workflow_status", "workflow_history", "workflow_verify", "workflow_manage", "workflow_configure"]
        rpc.request({"id": "clone", "type": "clone"})
        ordinary(rpc, tmp_path)
        assert result(talk(rpc, "Job status"))["details"]["status"] == "unbound"
        rpc.prompt("/job-test-reload")
        assert result(talk(rpc, "Job status"))["details"]["status"] == "unbound"
        rpc.request({"id": "resume", "type": "switch_session", "sessionPath": original["sessionFile"]})
        assert result(talk(rpc, "Job status"))["details"]["workflow_root"] == str(root)
        first = next(e for e in rpc.entries() if e.get("customType") == "agentvolve-mode")
        rpc.prompt("/job-test-tree " + first["id"])
        rpc.prompt("/job-test-reload")
        assert result(talk(rpc, "Job status"))["details"]["workflow_root"] == str(root)
        ordinary(rpc, tmp_path)
    with deployed(tmp_path, "--session", original["sessionFile"], environment=boundary) as rpc:
        assert result(talk(rpc, "Job status"))["details"]["workflow_root"] == str(root)
        ordinary(rpc, tmp_path)
    with deployed(tmp_path, "--fork", original["sessionFile"], environment=boundary) as rpc:
        ordinary(rpc, tmp_path)
        assert result(talk(rpc, "Job status"))["details"]["status"] == "unbound"
    assert not (tmp_path / "dispatched").exists()


@pytest.mark.parametrize("initial_refresh", [False, True])
@pytest.mark.parametrize("shutdown", [False, True])
@pytest.mark.parametrize("late_error", [False, True])
def test_inflight_monitor_invalidated_without_worker_or_evidence_effects(tmp_path, boundary, shutdown, late_error, initial_refresh):
    worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
    try:
        root = tmp_path / "runs" / NAME
        worker_view = projection(root)
        worker_view["worker"]["pid"] = worker.pid
        (tmp_path / "projection.json").write_text(json.dumps(worker_view))
        with deployed(tmp_path, environment=boundary) as rpc:
            if initial_refresh:
                (tmp_path / "pause").touch()
            bind(rpc, root, pid=worker.pid)
            evidence = root / "evidence.jsonl"
            evidence.write_bytes(b"immutable evidence\n")
            before = (evidence.read_bytes(), evidence.stat().st_mtime_ns)
            (tmp_path / "pause").touch()
            if late_error:
                (tmp_path / "late-error").touch()
            deadline = time.monotonic() + 15
            while not (tmp_path / "waiting").exists():
                assert time.monotonic() < deadline
                time.sleep(.02)
            if shutdown:
                rpc.request({"id": "new", "type": "new_session"})
            else:
                rpc.prompt("/goal New job cancelled before dispatch")
            (tmp_path / "release").touch()
            time.sleep(.2)
            events = talk(rpc, "Inspect job boundary")
            assert not any("Agentvolve finished" in e.get("message", "") for e in events)
            assert not [e for e in rpc.entries() if e.get("customType") == "agentvolve-stage-report" and e["data"]["stage"] == 6]
            count = len((tmp_path / "execs").read_text().splitlines())
            time.sleep(2.2)
            rpc.request({"id": "drain", "type": "get_state"})
            assert len((tmp_path / "execs").read_text().splitlines()) == count
            ordinary(rpc, tmp_path)
            assert worker.poll() is None
            assert (evidence.read_bytes(), evidence.stat().st_mtime_ns) == before
            calls = [json.loads(line) for line in (tmp_path / "execs").read_text().splitlines()]
            assert all(tuple(args[3:5]) in {
                ("apps.coding_agent.agentvolve_worker", "registry"),
                ("apps.coding_agent.operator_view", "progress"),
                ("apps.coding_agent.operator_view", "trace"),
            } for args in calls), calls
        assert worker.poll() is None
    finally:
        worker.terminate()
        worker.wait(timeout=10)


@pytest.mark.parametrize("shutdown", [False, True])
def test_inflight_progress_view_cannot_publish_after_submission_or_session_change(tmp_path, boundary, shutdown):
    root = tmp_path / "runs" / NAME
    with deployed(tmp_path, environment=boundary) as rpc:
        bind(rpc, root)
        (tmp_path / "pause").touch()
        rpc.send({"id": "paused-progress", "type": "prompt", "message": "/progress"})
        deadline = time.monotonic() + 15
        while not (tmp_path / "waiting").exists():
            assert time.monotonic() < deadline
            time.sleep(.02)
        if shutdown:
            rpc.request({"id": "new", "type": "new_session"})
        else:
            rpc.prompt("/goal A new request")
        (tmp_path / "release").touch()
        time.sleep(.2)
        assert not [e for e in rpc.entries() if e.get("customType") in {"agentvolve-progress-view", "agentvolve-trace-view"}]
        count = len((tmp_path / "execs").read_text().splitlines())
        time.sleep(2.2)
        assert len((tmp_path / "execs").read_text().splitlines()) == count
        ordinary(rpc, tmp_path)


@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_mismatched_reference_never_falls_back(tmp_path, boundary, missing):
    root = tmp_path / "runs" / NAME
    with deployed(tmp_path, environment=boundary) as rpc:
        bind(rpc, root)
        (tmp_path / "runs/workflow-pi-20260909T190000000Z").mkdir()
        if missing:
            root.rmdir()
        else:
            (tmp_path / "projection.json").write_text(json.dumps(projection(root, identity="d" * 64)))
        events = talk(rpc, "Job status", error=True)
        assert any(e.get("isError") for e in events)
        assert submission(rpc)["workflow"]["workflow_root"] == str(root)
        ordinary(rpc, tmp_path)


def test_missing_explicit_harness_refuses_newest_guessing_without_setup(tmp_path, boundary):
    boundary.pop("METERING_EVOLUTION_HARNESS_DESCRIPTOR")
    newest = tmp_path / "runs/harness-pi-20260909T190000000Z"
    newest.mkdir(parents=True)
    (newest / "selected-harness.json").write_text("incompatible newest seal")
    with deployed(tmp_path, environment=boundary) as rpc:
        events = rpc.prompt("/goal New job", lambda e: {"value": "1"} if e.get("title", "").startswith("Enter the exact") else {"cancelled": True})
        assert any("separately approved/budgeted Level-2 setup" in e.get("message", "") for e in events)
        assert submission(rpc)["state"] == "not-launched"
        assert not (tmp_path / "dispatched").exists()
        assert not (tmp_path / "tasks").exists()
        ordinary(rpc, tmp_path)


def test_local_readiness_failure_never_restarts_shared_service(tmp_path, boundary):
    runtime = Path(boundary["METERING_EVOLUTION_RUNTIME_MANIFEST"])
    runtime.write_text(json.dumps({"model": {"provider": "llamacpp", "model": "local", "reasoning": "medium"}}))
    (tmp_path / 'model-unready').touch()
    service_log = tmp_path / "service-called"
    systemctl = tmp_path / "bin/systemctl"
    systemctl.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(service_log)!r}).touch()\n")
    systemctl.chmod(0o755)
    with deployed(tmp_path, environment=boundary) as rpc:
        events = rpc.prompt("/goal New job", approve)
        assert any("Arrange safe startup separately" in e.get("message", "") for e in events)
        assert submission(rpc)["state"] == "not-launched"
        assert not service_log.exists() and not (tmp_path / "dispatched").exists()
        assert not (tmp_path / 'tasks').exists(), 'Readiness must fail before draft/registration effects'
        assert not any(entry.get('customType') == 'agentvolve-preparation-draft' for entry in rpc.entries())
        ordinary(rpc, tmp_path)


def test_excluded_tools_are_not_enabled_by_legacy_restore(tmp_path):
    with deployed(tmp_path, "--exclude-tools", "write,edit") as rpc:
        rpc.prompt("/job-test-legacy")
        rpc.prompt("/job-test-reload")
        talk(rpc, "Inspect configuration")
        snapshot = json.loads((tmp_path / "prompts.jsonl").read_text().splitlines()[-1])
        assert not {"write", "edit"} & set(snapshot["tools"])
        assert {"read", "bash", "darwinian_coding"} <= set(snapshot["tools"])
