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
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"Pi RPC exited with {process.returncode}: {stderr}")
        ready, _, _ = select.select(
            [process.stdout], [], [], max(0.0, min(1.0, deadline - time.monotonic()))
        )
        if not ready:
            continue
        line = process.stdout.readline()
        if not line:
            continue
        event = json.loads(line)
        events.append(event)
        if event.get("type") == "response" and event.get("id") == request_id:
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

    pi_bin = os.environ.get("PI_BIN", "pi")
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
        before = set(runs_directory.glob("solution-pi-*"))
        environment = {
            **os.environ,
            "METERING_EVOLUTION_HARNESS_DESCRIPTOR": str(harness),
            "METERING_EVOLUTION_RUNS_DIR": str(runs_directory),
            "METERING_EVOLUTION_RUNTIME_MANIFEST": str(runtime),
            "METERING_EVOLUTION_TASKS_DIR": str(tasks_directory),
            "PI_BIN": pi_bin,
        }
        environment.pop("METERING_EVOLUTION_TASK_PROFILE", None)
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
        try:
            goal_response, goal_events = rpc_prompt(
                process, f"goal-{index}", f"/goal {goal}", timeout=120
            )
            assert goal_response.get("success") is True, goal_response
            assert not workflow_error(goal_events), workflow_error(goal_events)
            limit_response, limit_events = rpc_prompt(
                process,
                f"limit-{index}",
                f"/limit {rounds} generations",
                timeout=120,
            )
            assert limit_response.get("success") is True, limit_response
            assert not workflow_error(limit_events), workflow_error(limit_events)
            run_response, run_events = rpc_prompt(
                process, f"run-{index}", "/agentvolve", timeout=2 * 60 * 60
            )
            assert run_response.get("success") is True, run_response

            created = set(runs_directory.glob("solution-pi-*")) - before
            assert len(created) == 1, workflow_error(run_events)
            run_root = created.pop()
            retries = 0
            while not (run_root / "experiment-report.json").is_file():
                pending = run_root / "state" / "pending" / "round-intent.json"
                assert retries < max_retries and pending.is_file(), workflow_error(
                    run_events
                )
                retries += 1
                retry_response, run_events = rpc_prompt(
                    process,
                    f"retry-{index}-{retries}",
                    (
                        "/evolve-code-retry "
                        f"{retry_reason} (task {index + 1}, retry {retries})"
                    ),
                    timeout=2 * 60 * 60,
                )
                assert retry_response.get("success") is True, retry_response

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
            assert configurations[-1] == {}
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
        finally:
            close_rpc(process)
