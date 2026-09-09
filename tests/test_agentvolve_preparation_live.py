"""Opt-in real-model preparation smoke: always DECLINE task execution.

This tests the repaired drafting path, not solution evolution or final success.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from test_agentvolve_goal import EXTENSION, RPC
from test_task_profile_tool import git


@pytest.mark.live_agents
@pytest.mark.skipif(os.environ.get("METERING_RUN_AGENTVOLVE_PREPARATION_LIVE") != "1", reason="explicit real-model preparation smoke opt-in required")
def test_real_model_reads_referenced_input_before_task_review(tmp_path: Path):
    assert shutil.which("pi"), "Pi is required"
    source = tmp_path / "source"
    source.mkdir()
    token = "source-token-" + uuid.uuid4().hex
    payload = json.dumps({"token": token}).encode()
    (source / "settings.json").write_bytes(payload)
    (source / "solver.py").write_bytes(b"")
    for args in (["init", "-q"], ["add", "."], ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "Preparation fixture"]):
        git(source, *args)
    commit = git(source, "rev-parse", "HEAD")
    runs, tasks = tmp_path / "runs", tmp_path / "tasks"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("METERING_EVOLUTION_")}
    for name in ("METERING_EVOLUTION_RUNTIME_MANIFEST", "METERING_EVOLUTION_HARNESS_DESCRIPTOR"):
        assert os.environ.get(name), f"{name} must explicitly select the reviewed execution setup"
        environment[name] = os.environ[name]
    environment.update({"METERING_EVOLUTION_RUNS_DIR": str(runs), "METERING_EVOLUTION_TASKS_DIR": str(tasks)})
    provider = os.environ.get("METERING_PREPARATION_LIVE_PROVIDER", "llamacpp")
    model = os.environ.get("METERING_PREPARATION_LIVE_MODEL", "local")
    process = subprocess.Popen(["pi", "--mode", "rpc", "--no-session", "--no-extensions", "-e", str(EXTENSION), "--provider", provider, "--model", model],
        cwd=tmp_path, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    events, reviews = [], []
    try:
        rpc = RPC(process)
        # A fixture-only review cap. Confirmation is always false: no workflow
        # budget, registration, worker or candidate execution is authorized here.
        rpc.prompt("/limit 1")
        goal = f"Read {source / 'settings.json'} and implement solver.py solve() to return that file's token. Keep settings.json unchanged. Check the literal expected token using stdout-json-v1 externally compared output. Propose a 100000-second development timeout-reservation budget."
        rpc.send({"id": "live-draft", "type": "prompt", "message": "/goal " + goal})
        deadline = time.monotonic() + 240
        while True:
            event = rpc.event(deadline)
            events.append(event)
            if event.get("type") == "extension_ui_request":
                if event.get("method") == "confirm":
                    assert event["title"] == "Register and run this reviewed task?", event
                    reviews.append(event)
                    rpc.send({"type": "extension_ui_response", "id": event["id"], "confirmed": False})
                elif event.get("method") == "input" and event.get("title", "").startswith("Enter the exact"):
                    rpc.send({"type": "extension_ui_response", "id": event["id"], "value": "1"})
                elif event.get("method") in {"input", "select", "editor"}:
                    # Do not patch/retry the model's proposal to manufacture a pass.
                    rpc.send({"type": "extension_ui_response", "id": event["id"], "cancelled": True})
            if event.get("type") == "response" and event.get("id") == "live-draft":
                assert event["success"], event
                break
        assert reviews, events
        review = reviews[0]["message"]
        assert token in review, "The unknown source token must reach the model-authored check"
        assert hashlib.sha256(payload).hexdigest() in review and commit in review
        assert "stdout-json-v1" in review and "Read-only inputs: [\"settings.json\"]" in review
        assert not runs.exists() and not tasks.exists(), "Declined preparation must create no task or run"
        assert (source / "solver.py").read_bytes() == b"" and (source / "settings.json").read_bytes() == payload
        assert git(source, "status", "--porcelain") == ""
    finally:
        (tmp_path / "preparation-events.json").write_text(json.dumps({"provider": provider, "model": model, "events": events}, indent=2))
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr is not None
        stderr = process.stderr.read().decode(errors="replace")
        (tmp_path / "preparation-stderr.txt").write_text(stderr)
        assert not stderr, stderr
