"""Session-native, conversational worker configuration through the deployed Pi tool."""

import json
from pathlib import Path
import shutil
import time

import pytest

from test_agentvolve_jobs import (
    deployed,
    ordinary,
    result,
    submission,
    talk,
    wait_submission,
)
from test_agentvolve_jobs import boundary as boundary

pytestmark = pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
KEYS = (
    "METERING_EVOLUTION_RUNTIME_MANIFEST",
    "METERING_EVOLUTION_HARNESS_DESCRIPTOR",
    "METERING_PI_CONFIG_DIR",
)


def without_defaults(boundary):
    return {key: value for key, value in boundary.items() if key not in KEYS}


def selections(boundary):
    return {
        **dict(
            zip(
                ("manifest", "harness", "configuration"),
                (boundary[key] for key in KEYS),
            )
        ),
        "runs": boundary["METERING_EVOLUTION_RUNS_DIR"],
    }


def records(rpc):
    return [
        entry["data"]
        for entry in rpc.entries()
        if entry.get("customType") == "agentvolve-execution-configuration"
    ]


def configure_request(paths):
    return "Configure worker " + json.dumps(paths, separators=(",", ":"))


def blocking(events):
    return [
        event
        for event in events
        if event.get("method") in {"input", "select", "confirm", "editor"}
    ]


def test_assistant_configures_and_delegates_without_exports_restart_or_dialogs(
    tmp_path, boundary
):
    paths = selections(boundary)
    alternate = tmp_path / "worker config ; NO_SHELL"
    shutil.copytree(paths["configuration"], alternate)
    paths["configuration"] = str(alternate)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        initial = rpc.request({"id": "initial", "type": "get_state"})[-1]["data"]
        ordinary(rpc, tmp_path)
        events = talk(rpc, configure_request(paths))
        configured = result(events)
        assert configured["details"] == {"status": "configured", **paths}
        assert not blocking(events)
        assert not (tmp_path / "dispatched").exists()
        assert not (tmp_path / "tasks").exists()
        record = records(rpc)[-1]
        assert record == {
            "schema": "agentvolve-execution-configuration-v2",
            "sessionId": initial["sessionId"],
            **paths,
        }

        rpc.prompt("/limit 1")
        events = rpc.prompt("/goal Build the independently validated result")
        assert not blocking(events)
        owned = wait_submission(rpc, "launched")
        dispatch = json.loads((tmp_path / "dispatch-record.json").read_text())
        assert dispatch["args"][7:10] == [
            paths["manifest"],
            paths["harness"],
            paths["configuration"],
        ]
        assert dispatch["approved"]["worker_configuration"] == paths["configuration"]
        assert not Path(dispatch["args"][10]).exists()
        assert (Path(owned["workflow"]["workflow_root"]) / "evidence.jsonl").exists()
        ordinary(rpc, tmp_path)
        now = rpc.request({"id": "now", "type": "get_state"})[-1]["data"]
        assert now["sessionId"] == initial["sessionId"] and rpc.process.poll() is None
        for snapshot in map(
            json.loads, (tmp_path / "prompts.jsonl").read_text().splitlines()
        ):
            assert snapshot["environment"]["PI_CODING_AGENT_DIR"] == str(
                tmp_path / "interactive-config"
            )
            assert all(snapshot["environment"][key] is None for key in KEYS)
        assert "PRIVATE_WORKER_TOKEN" not in json.dumps(rpc.entries())
        assert "PRIVATE_WORKER_TOKEN" not in (tmp_path / "execs").read_text()


def test_start_with_absent_settings_returns_missing_fields_then_can_retry(
    tmp_path, boundary
):
    paths = selections(boundary)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        rpc.prompt("/limit 1")
        events = rpc.prompt("/goal Build the validated task")
        assert not blocking(events)
        stopped = wait_submission(rpc, "not-launched")
        assert "configuration fields" in stopped["diagnostic"]
        assert not (tmp_path / "dispatched").exists()

        configured = result(talk(rpc, configure_request(paths)))
        assert configured["details"]["status"] == "configured"
        rpc.prompt("/goal Build the validated task")
        assert wait_submission(rpc, "launched")["state"] == "launched"
        ordinary(rpc, tmp_path)


def test_new_configuration_only_affects_future_jobs_not_bound_status(
    tmp_path, boundary
):
    paths = selections(boundary)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        talk(rpc, configure_request(paths))
        rpc.prompt("/limit 1")
        rpc.prompt("/goal Initial validated task")
        before = wait_submission(rpc, "launched")

        alternate = tmp_path / "future-worker"
        shutil.copytree(paths["configuration"], alternate)
        paths["configuration"] = str(alternate)
        future_runs = tmp_path / "future-private-runs"
        future_runs.mkdir(mode=0o700)
        paths["runs"] = str(future_runs)
        talk(rpc, configure_request(paths))
        assert records(rpc)[-1]["configuration"] == str(alternate)
        assert records(rpc)[-1]["runs"] == str(future_runs)
        assert submission(rpc) == before
        assert (
            result(talk(rpc, "Job status"))["details"]["workflow_root"]
            == before["workflow"]["workflow_root"]
        )
        assert (
            result(talk(rpc, "Verify job"))["details"]["workflow_root"]
            == before["workflow"]["workflow_root"]
        )
        dispatched = json.loads((tmp_path / "dispatch-record.json").read_text())[
            "args"
        ]
        assert dispatched[9] == boundary["METERING_PI_CONFIG_DIR"]
        assert dispatched[5] == boundary["METERING_EVOLUTION_RUNS_DIR"]


@pytest.mark.parametrize("corruption", ["null", "schema", "legacy", "relative"])
def test_malformed_latest_selection_never_restores_older_or_defaults(
    tmp_path, boundary, corruption
):
    with deployed(tmp_path, environment=boundary) as rpc:
        talk(rpc, configure_request(selections(boundary)))
        record = records(rpc)[-1]
        if corruption == "null":
            record = None
        elif corruption == "schema":
            record["schema"] = "unknown"
        elif corruption == "legacy":
            record["schema"] = "agentvolve-execution-configuration-v1"
            record.pop("runs")
        else:
            record["configuration"] = "relative"
        rpc.prompt("/job-test-configuration-record " + json.dumps(record))
        rpc.prompt("/job-test-reload")
        rpc.prompt("/limit 1")
        events = rpc.prompt("/goal Repair the fixture")
        assert not blocking(events)
        assert wait_submission(rpc, "not-launched")["state"] == "not-launched"
        assert not (tmp_path / "dispatched").exists()


def test_configuring_worker_never_enables_excluded_ordinary_tools(tmp_path, boundary):
    with deployed(
        tmp_path,
        "--tools",
        "read,darwinian_coding",
        environment=without_defaults(boundary),
    ) as rpc:
        talk(rpc, configure_request(selections(boundary)))
        talk(rpc, "Write normal file", error=True)
        assert not (tmp_path / "normal.txt").exists()
        for prompt in (tmp_path / "prompts.jsonl").read_text().splitlines():
            assert "write" not in json.loads(prompt)["tools"]


def test_session_switch_aborts_inflight_configuration_without_saving(
    tmp_path, boundary
):
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        (tmp_path / "review-pause").touch()
        events = rpc.prompt(configure_request(selections(boundary)))
        assert not blocking(events)
        deadline = time.monotonic() + 15
        while not (tmp_path / "review-waiting").exists():
            assert time.monotonic() < deadline
            rpc.request({"id": "drain", "type": "get_state"})
            time.sleep(0.02)
        rpc.request({"id": "new", "type": "new_session"})
        (tmp_path / "review-release").touch()
        ordinary(rpc, tmp_path)
        assert records(rpc) == []
        assert not (tmp_path / "dispatched").exists()


@pytest.mark.parametrize(
    "source", ["manifest", "harness", "runs", "models.json", "auth.json", "private.txt"]
)
def test_worker_inputs_are_never_task_source_context(tmp_path, boundary, source):
    paths = selections(boundary)
    private = Path(paths["configuration"]) / "private.txt"
    private.write_text("PRIVATE_WORKER_TOKEN")
    reference = (
        paths[source]
        if source in {"manifest", "harness", "runs"}
        else str(Path(paths["configuration"]) / source)
    )
    Path(boundary["JOB_DRAFT"]).write_text(json.dumps({"read_files": [reference]}))
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        talk(rpc, configure_request(paths))
        rpc.prompt("/limit 1")
        events = rpc.prompt("/goal Use the contents of " + reference)
        assert not blocking(events)
        stopped = wait_submission(rpc, "failed")
        assert "Protected/operator" in stopped["diagnostic"]
        assert not (tmp_path / "dispatched").exists()
        assert not (tmp_path / "tasks").exists()
        assert "PRIVATE_WORKER_TOKEN" not in json.dumps(rpc.entries())
        ordinary(rpc, tmp_path)
