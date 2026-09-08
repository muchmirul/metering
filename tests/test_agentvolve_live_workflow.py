"""Opt-in deployed-Pi acceptance for the complete Agentvolve workflow."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / ".pi" / "extensions" / "population-evolution.ts"
SOLUTION = ROOT / "apps" / "coding_agent" / "solution_experiment.py"
DEFAULT_RUNTIME = (
    Path.home() / ".config" / "metering" / "harness" / "runtime.pi.local.json"
)


def required_path(name: str, fallback: Path | None = None) -> Path:
    raw = os.environ.get(name)
    path = Path(raw).expanduser().absolute() if raw else fallback
    assert path is not None and path.is_file(), f"{name} must name an existing file"
    return path


def rpc_request(
    process: subprocess.Popen[str],
    request: dict[str, Any],
    *,
    timeout: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assert process.stdin is not None
    assert process.stdout is not None
    request_id = str(request["id"])
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    deadline = time.monotonic() + timeout
    events: list[dict[str, Any]] = []
    buffer = getattr(process, "_agentvolve_rpc_buffer", b"")
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"Pi RPC exited with {process.returncode}: {stderr}")
        if b"\n" not in buffer:
            ready, _, _ = select.select(
                [process.stdout], [], [], max(0.0, min(1.0, deadline - time.monotonic()))
            )
            if not ready:
                continue
            buffer += os.read(process.stdout.fileno(), 65536)
            if b"\n" not in buffer:
                continue
        line, buffer = buffer.split(b"\n", 1)
        event = json.loads(line)
        events.append(event)
        if event.get("type") == "extension_ui_request" and event.get("method") == "confirm":
            # This opt-in test is authorized only for the exact operator-approved profile.
            assert event["title"] == "Run this reviewed Agentvolve task?", event
            expected_goal = getattr(process, "_agentvolve_reviewed_goal")
            expected_rounds = getattr(process, "_agentvolve_reviewed_rounds")
            assert json.dumps(expected_goal, ensure_ascii=False) in event["message"]
            assert f"{expected_rounds} generations" in event["message"]
            process.stdin.write(json.dumps({"type": "extension_ui_response", "id": event["id"], "confirmed": True}) + "\n")
            process.stdin.flush()
        elif event.get("type") == "extension_ui_request" and event.get("method") in {"input", "select", "editor"}:
            raise AssertionError(f"unexpected task ambiguity in approved live fixture: {event}")
        if event.get("type") == "response" and event.get("id") == request_id:
            setattr(process, "_agentvolve_rpc_buffer", buffer)
            return event, events
    raise AssertionError(f"timed out waiting for Pi RPC response {request_id!r}")


def rpc_prompt(
    process: subprocess.Popen[str],
    request_id: str,
    text: str,
    *,
    timeout: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return rpc_request(
        process,
        {"type": "prompt", "id": request_id, "message": text},
        timeout=timeout,
    )


def close_rpc(process: subprocess.Popen[str]) -> None:
    if process.stdin is not None:
        process.stdin.close()
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def workflow_error(events: list[dict[str, Any]]) -> str:
    messages = [
        str(event.get("message", ""))
        for event in events
        if event.get("type") == "extension_ui_request"
        and event.get("method") == "notify"
        and event.get("notifyType") == "error"
    ]
    return "\n".join(messages)


@pytest.mark.live_agents
@pytest.mark.skipif(
    os.environ.get("METERING_RUN_AGENTVOLVE_E2E") != "1",
    reason="set METERING_RUN_AGENTVOLVE_E2E=1 for multi-task local inference",
)
def test_deployed_agentvolve_solves_and_verifies_three_local_tasks(
    tmp_path: Path,
) -> None:
    profiles = [
        Path(value).expanduser().absolute()
        for value in os.environ.get("METERING_EVOLUTION_LIVE_TASK_PROFILES", "").split(
            os.pathsep
        )
        if value
    ]
    assert len(profiles) >= 3, (
        "METERING_EVOLUTION_LIVE_TASK_PROFILES must contain at least three "
        f"operator-approved profiles separated by {os.pathsep!r}"
    )
    assert all(path.is_file() for path in profiles)
    runtime = required_path("METERING_EVOLUTION_RUNTIME_MANIFEST", DEFAULT_RUNTIME)
    harness = required_path("METERING_EVOLUTION_LIVE_HARNESS")
    runtime_document = json.loads(runtime.read_text(encoding="ascii"))
    assert runtime_document["model"]["connector"] == "pi-v1"
    assert runtime_document["model"]["provider"] == "llamacpp"
    max_retries = int(os.environ.get("METERING_EVOLUTION_LIVE_MAX_RETRIES", "0"))
    retry_reason = os.environ.get("METERING_EVOLUTION_LIVE_RETRY_REASON", "").strip()
    assert max_retries >= 0
    if max_retries:
        assert retry_reason, (
            "METERING_EVOLUTION_LIVE_RETRY_REASON is required when live retries "
            "are authorized"
        )

    # The operator may be newer than the exact worker pin. Probe without inference.
    checked = subprocess.run(
        [sys.executable, "-m", "connectors.fixed.pi.runtime", "check", str(runtime)],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert checked.returncode == 0, checked.stderr
    pi_bin = os.environ.get("METERING_EVOLUTION_OPERATOR_PI_BIN", "pi")
    deployed = subprocess.run(
        [pi_bin, "-e", str(EXTENSION), "--list-models"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert deployed.returncode == 0, deployed.stderr
    assert "llamacpp" in deployed.stdout

    tasks_directory = tmp_path / "tasks"
    tasks_directory.mkdir()
    for index, profile in enumerate(profiles):
        shutil.copy2(profile, tasks_directory / f"task-{index}.task.json")
    runs_directory = tmp_path / "runs"
    runs_directory.mkdir()

    for index, source_profile in enumerate(profiles):
        profile = json.loads(source_profile.read_text(encoding="ascii"))
        repository = Path(profile["repository"]["path"])
        goal = str(profile["goal"])
        rounds = int(profile["limits"]["max_rounds"])
        before = set(runs_directory.glob("workflow-pi-*"))
        environment = {
            **os.environ,
            "METERING_EVOLUTION_HARNESS_DESCRIPTOR": str(harness),
            "METERING_EVOLUTION_RUNS_DIR": str(runs_directory),
            "METERING_EVOLUTION_RUNTIME_MANIFEST": str(runtime),
            "METERING_EVOLUTION_TASKS_DIR": str(tasks_directory),
            "METERING_EVOLUTION_TASK_PROFILE": str(source_profile),
        }
        process = subprocess.Popen(
            [pi_bin, "--mode", "rpc", "--no-session", "-e", str(EXTENSION)],
            cwd=repository,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=environment,
        )
        setattr(process, "_agentvolve_reviewed_goal", goal)
        setattr(process, "_agentvolve_reviewed_rounds", rounds)
        try:
            limit_response, limit_events = rpc_prompt(
                process,
                f"limit-{index}",
                f"/limit {rounds} generations",
                timeout=120,
            )
            assert limit_response.get("success") is True, limit_response
            assert not workflow_error(limit_events), workflow_error(limit_events)
            run_response, run_events = rpc_prompt(
                process, f"run-{index}", f"/goal {goal}", timeout=600
            )
            assert run_response.get("success") is True, run_response
            assert not workflow_error(run_events), workflow_error(run_events)
            assert any(event.get("method") == "confirm" for event in run_events)

            created = set(runs_directory.glob("workflow-pi-*")) - before
            assert len(created) == 1, workflow_error(run_events)
            workflow_root = created.pop()
            request = json.loads((workflow_root / "workflow.json").read_text())
            run_root = Path(request["solution_run_root"])
            retries = 0
            deadline = time.monotonic() + 2 * 60 * 60
            while True:
                status = json.loads((workflow_root / "worker-status.json").read_text())
                if status["state"] in {"completed", "verified"}:
                    break
                assert time.monotonic() < deadline, status
                if status["state"] == "waiting-retry":
                    assert retries < max_retries, status
                    retries += 1
                    retry = subprocess.run(
                        [sys.executable, "-m", "connectors.fixed.pi.runtime", "retry", str(workflow_root),
                         f"{retry_reason} (task {index + 1}, retry {retries})"],
                        cwd=ROOT, capture_output=True, text=True, timeout=120, env=environment,
                    )
                    assert retry.returncode == 0, retry.stderr
                else:
                    assert status["state"] in {"queued", "running"}, status
                time.sleep(2)

            report = json.loads(
                (run_root / "experiment-report.json").read_text(encoding="ascii")
            )
            assert report["final"]["passed_count"] == report["final"]["task_count"]
            entries_response, _ = rpc_request(
                process,
                {"type": "get_entries", "id": f"entries-{index}"},
                timeout=120,
            )
            configurations = [
                entry["data"]
                for entry in entries_response["data"]["entries"]
                if entry.get("type") == "custom"
                and entry.get("customType")
                == "agentvolve-workflow-configuration"
            ]
            assert configurations[-1] == {"maxRounds": rounds}
            assert (run_root / "selected-solution.json").is_file()
            assert (run_root / "selected.patch").is_file()

            verified = subprocess.run(
                [sys.executable, str(SOLUTION), "verify", str(run_root)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
                env=environment,
            )
            assert verified.returncode == 0, verified.stderr
            assert json.loads(verified.stdout)["status"] == "verified"

            # Inspect actual local-model descendants, not a synthetic projection fixture.
            from apps.coding_agent.candidate_view import report_view, tree_view

            nodes = []
            offset = 0
            while True:
                page = tree_view(runs_directory, workflow_root.name, offset)
                nodes.extend(page["items"])
                if page["next_offset"] is None:
                    break
                offset = page["next_offset"]
            assert any(node["label"].startswith("S") and node["parent_label"] for node in nodes)
            assert any(node["label"].startswith("H") and node["reused"] for node in nodes)
            for node in nodes:
                event_offset = 0
                diff_offset = 0
                while True:
                    candidate = report_view(runs_directory, workflow_root.name, node["label"], event_offset, diff_offset)
                    assert candidate["node"]["candidate_id"] == node["candidate_id"]
                    if node["status"] != "selected":
                        assert candidate["evidence"]["final"] is None
                    if node["parent_label"]:
                        assert candidate["diff"]["available"], candidate["diff"]
                    if candidate["next_offset"] is not None:
                        event_offset = candidate["next_offset"]
                    elif candidate["diff"]["next_offset"] is not None:
                        diff_offset = candidate["diff"]["next_offset"]
                    else:
                        break
            selected = next(node for node in nodes if node["kind"] == "solution" and node["status"] == "selected")
            assert selected["candidate_id"] == report["selected_solution"]["candidate_id"]

            # The graphical trace must resolve the actual local-model commits and files.
            from apps.coding_agent.file_view import path_key
            from apps.coding_agent.trace_view import TraceSnapshot

            trace = TraceSnapshot(runs_directory, workflow_root.name)
            assert {node["candidate_id"] for node in trace.graph()["nodes"]} == {node["candidate_id"] for node in nodes}
            for node in nodes:
                files = trace.files[node["kind"]]
                inventory = files.inventory(node["candidate_id"])
                assert inventory
                entrypoint = path_key(node["entrypoint"].encode("utf-8"))
                assert entrypoint in inventory
                assert isinstance(files.blob(node["candidate_id"], entrypoint), bytes)
                history = trace.file_history(node["kind"], entrypoint)
                assert any(item["candidate_id"] == node["candidate_id"] and item["file"] for item in history["items"])
        finally:
            close_rpc(process)
