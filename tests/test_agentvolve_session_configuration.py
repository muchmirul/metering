"""Session-native worker selection using deployed Pi and deterministic boundaries."""
import json
from pathlib import Path
import shutil
import time

import pytest

from test_agentvolve_jobs import (NAME, approve, bind, deployed, ordinary,
                                 result, submission, talk)
from test_agentvolve_jobs import boundary as boundary

pytestmark = pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
KEYS = ("METERING_EVOLUTION_RUNTIME_MANIFEST", "METERING_EVOLUTION_HARNESS_DESCRIPTOR", "METERING_PI_CONFIG_DIR")


def without_defaults(boundary):
    return {key: value for key, value in boundary.items() if key not in KEYS}


def selections(boundary):
    return dict(zip(("manifest", "harness", "configuration"), (boundary[key] for key in KEYS)))


def records(rpc):
    return [entry["data"] for entry in rpc.entries() if entry.get("customType") == "agentvolve-execution-configuration"]


def configure_dialog(paths):
    def dialog(event):
        title = event.get("title", "")
        if event["method"] == "input":
            key = "manifest" if title.startswith("Agentvolve worker runtime") else "harness" if title.startswith("Agentvolve compatible sealed") else "configuration"
            assert title.startswith("Agentvolve"), event
            return {"value": '"' + paths[key] + '"'}
        assert event["method"] == "confirm" and title == "Save Agentvolve worker configuration for this session?", event
        assert "No main-Pi restart" in event["message"]
        assert "does not start a worker" in event["message"]
        assert "PRIVATE_WORKER_TOKEN" not in event["message"]
        return {"confirmed": True}
    return dialog


def test_configure_and_delegate_without_exports_restart_or_main_environment_changes(tmp_path, boundary):
    paths = selections(boundary)
    alternate = tmp_path / "worker config ; NO_SHELL"
    shutil.copytree(paths["configuration"], alternate)
    paths["configuration"] = str(alternate)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        initial = rpc.request({"id": "initial", "type": "get_state"})[-1]["data"]
        ordinary(rpc, tmp_path)
        configured = result(talk(rpc, "Configure worker", dialog=configure_dialog(paths)))
        assert configured["details"] == {"status": "configured", **paths}
        assert not (tmp_path / "dispatched").exists()
        assert not (tmp_path / "tasks").exists()
        record = records(rpc)[-1]
        assert record == {"schema": "agentvolve-execution-configuration-v1", "sessionId": initial["sessionId"], **paths}
        rpc.prompt("/goal Build the independently reviewed result", approve)
        owned = submission(rpc)
        assert owned["state"] == "launched"
        dispatch = json.loads((tmp_path / "dispatch-record.json").read_text())
        assert dispatch["args"][7:10] == [paths["manifest"], paths["harness"], paths["configuration"]]
        assert dispatch["approved"]["worker_configuration"] == paths["configuration"]
        assert not Path(dispatch["args"][10]).exists(), "Disposable approval transport should be cleaned, not evidence"
        assert (Path(owned["workflow"]["workflow_root"]) / "evidence.jsonl").exists()
        ordinary(rpc, tmp_path)
        now = rpc.request({"id": "now", "type": "get_state"})[-1]["data"]
        assert now["sessionId"] == initial["sessionId"] and rpc.process.poll() is None
        for snapshot in map(json.loads, (tmp_path / "prompts.jsonl").read_text().splitlines()):
            assert snapshot["environment"]["PI_CODING_AGENT_DIR"] == str(tmp_path / "interactive-config")
            assert all(snapshot["environment"][key] is None for key in KEYS)
        assert "PRIVATE_WORKER_TOKEN" not in json.dumps(rpc.entries())
        assert "PRIVATE_WORKER_TOKEN" not in (tmp_path / "execs").read_text()


def test_goal_offers_configuration_inline_when_defaults_absent(tmp_path, boundary):
    dialog = configure_dialog(selections(boundary))
    def review(event):
        if event.get("title", "").startswith("Agentvolve") or event.get("title") == "Save Agentvolve worker configuration for this session?":
            return dialog(event)
        return approve(event)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        rpc.prompt("/goal Build the reviewed task", review)
        assert records(rpc) and submission(rpc)["state"] == "launched"
        ordinary(rpc, tmp_path)


@pytest.mark.parametrize("cancel_at", [0, 1, 2, 3, "failure"])
def test_cancelled_or_failed_configuration_preserves_selection_and_existing_job(tmp_path, boundary, cancel_at):
    paths = selections(boundary)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        talk(rpc, "Configure worker", dialog=configure_dialog(paths))
        bind(rpc, tmp_path / "runs" / NAME)
        before = submission(rpc)
        count = 0
        if cancel_at == "failure":
            (tmp_path / "review-failure").touch()
        def cancel(event):
            nonlocal count
            current = count
            count += 1
            return {"cancelled": True} if current == cancel_at else configure_dialog(paths)(event)
        events = talk(rpc, "Configure worker", dialog=cancel, error=cancel_at == "failure")
        if cancel_at == "failure":
            assert any(e.get("isError") for e in events)
        assert len(records(rpc)) == 1 and submission(rpc) == before
        assert not (tmp_path / "dispatched").exists()
        ordinary(rpc, tmp_path)


def test_new_configuration_only_affects_future_jobs_not_bound_status_or_verification(tmp_path, boundary):
    paths = selections(boundary)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        talk(rpc, "Configure worker", dialog=configure_dialog(paths))
        rpc.prompt("/goal Initial reviewed task", approve)
        before = submission(rpc)
        alternate = tmp_path / "future-worker"
        shutil.copytree(paths["configuration"], alternate)
        paths["configuration"] = str(alternate)
        talk(rpc, "Configure worker", dialog=configure_dialog(paths))
        assert records(rpc)[-1]["configuration"] == str(alternate)
        assert submission(rpc) == before
        assert result(talk(rpc, "Job status"))["details"]["workflow_root"] == before["workflow"]["workflow_root"]
        assert result(talk(rpc, "Verify job"))["details"]["workflow_root"] == before["workflow"]["workflow_root"]
        assert json.loads((tmp_path / "dispatch-record.json").read_text())["args"][9] == boundary["METERING_PI_CONFIG_DIR"]


def test_configuration_restores_across_tree_reload_resume_but_not_clone_or_fork(tmp_path, boundary):
    environment = without_defaults(boundary)
    paths = selections(boundary)
    with deployed(tmp_path, environment=environment) as rpc:
        rpc.prompt("/job-test-legacy")
        first = next(e["id"] for e in rpc.entries() if e.get("customType") == "agentvolve-mode")
        talk(rpc, "Configure worker", dialog=configure_dialog(paths))
        original = rpc.request({"id": "original", "type": "get_state"})[-1]["data"]
        rpc.prompt("/job-test-tree " + first)
        rpc.prompt("/job-test-reload")
        rpc.prompt("/goal Using append-ordered worker configuration", approve)
        assert submission(rpc)["state"] == "launched"
        rpc.request({"id": "clone", "type": "clone"})
        events = rpc.prompt("/goal Fork must configure independently", lambda e: {"value": "1"} if e.get("title", "").startswith("Enter the exact") else {"cancelled": True})
        assert any(e.get("title", "").startswith("Agentvolve worker runtime") for e in events)
        rpc.prompt("/job-test-reload")
        events = rpc.prompt("/goal Still independent after reload", lambda e: {"value": "1"} if e.get("title", "").startswith("Enter the exact") else {"cancelled": True})
        assert any(e.get("title", "").startswith("Agentvolve worker runtime") for e in events)
    with deployed(tmp_path, "--session", original["sessionFile"], environment=environment) as rpc:
        rpc.prompt("/goal Resumed original configuration", approve)
        assert submission(rpc)["state"] == "launched"
    with deployed(tmp_path, "--fork", original["sessionFile"], environment=environment) as rpc:
        events = rpc.prompt("/goal CLI fork needs its own configuration", lambda e: {"value": "1"} if e.get("title", "").startswith("Enter the exact") else {"cancelled": True})
        assert any(e.get("title", "").startswith("Agentvolve worker runtime") for e in events)


@pytest.mark.parametrize("corruption", ["null", "schema", "relative"])
def test_malformed_latest_selection_never_restores_older_selection_or_defaults(tmp_path, boundary, corruption):
    with deployed(tmp_path, environment=boundary) as rpc:
        talk(rpc, "Configure worker", dialog=configure_dialog(selections(boundary)))
        record = records(rpc)[-1]
        if corruption == "null":
            record = None
        elif corruption == "schema":
            record["schema"] = "unknown"
        else:
            record["configuration"] = "relative"
        rpc.prompt("/job-test-configuration-record " + json.dumps(record))
        rpc.prompt("/job-test-reload")
        asked = []
        def cancel_setup(event):
            if event["title"].startswith("Enter the exact"):
                return {"value": "1"}
            asked.append(event)
            assert event["title"] == "Agentvolve worker runtime manifest"
            return {"cancelled": True}
        rpc.prompt("/goal Repair the fixture", cancel_setup)
        assert len(asked) == 1 and submission(rpc)["state"] == "not-launched"
        assert not (tmp_path / "dispatched").exists()


def test_configuring_worker_never_enables_excluded_ordinary_tools(tmp_path, boundary):
    with deployed(tmp_path, "--tools", "read,darwinian_coding", environment=without_defaults(boundary)) as rpc:
        talk(rpc, "Configure worker", dialog=configure_dialog(selections(boundary)))
        talk(rpc, "Write normal file", error=True)
        assert not (tmp_path / "normal.txt").exists()
        for prompt in (tmp_path / "prompts.jsonl").read_text().splitlines():
            assert "write" not in json.loads(prompt)["tools"]


def test_session_switch_during_configuration_never_saves_to_replacement_session(tmp_path, boundary):
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        (tmp_path / "review-pause").touch()
        dialog = configure_dialog(selections(boundary))
        rpc.prompt("Configure worker", dialog)
        deadline = time.monotonic() + 15
        while not (tmp_path / "review-waiting").exists():
            assert time.monotonic() < deadline
            rpc.request({"id": "drain", "type": "get_state"}, dialog)
            time.sleep(.02)
        rpc.request({"id": "new", "type": "new_session"})
        (tmp_path / "review-release").touch()
        ordinary(rpc, tmp_path)
        assert records(rpc) == []
        assert not (tmp_path / "dispatched").exists()


@pytest.mark.parametrize("source", ["manifest", "harness", "models.json", "auth.json", "private.txt"])
def test_session_selected_worker_inputs_are_never_task_source_context(tmp_path, boundary, source):
    paths = selections(boundary)
    private = Path(paths["configuration"]) / "private.txt"
    private.write_text("PRIVATE_WORKER_TOKEN")
    reference = paths[source] if source in {"manifest", "harness"} else str(Path(paths["configuration"]) / source)
    Path(boundary["JOB_DRAFT"]).write_text(json.dumps({"read_files": [reference]}))
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        talk(rpc, "Configure worker", dialog=configure_dialog(paths))
        events = rpc.prompt("/goal Use the contents of " + reference, approve)
        assert any("Protected/operator" in e.get("message", "") for e in events)
        assert not (tmp_path / "dispatched").exists() and not (tmp_path / "tasks").exists()
        assert "PRIVATE_WORKER_TOKEN" not in json.dumps(rpc.entries())
        ordinary(rpc, tmp_path)
