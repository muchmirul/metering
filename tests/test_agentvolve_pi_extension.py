"""Deployed Pi-extension checks that do not invoke a model."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import TextIO

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / ".pi" / "extensions" / "population-evolution.ts"


def send(stream: TextIO, document: dict[str, object]) -> None:
    stream.write(json.dumps(document, separators=(",", ":")) + "\n")
    stream.flush()


def response(stream: TextIO, request_id: str) -> dict[str, object]:
    for line in stream:
        event = json.loads(line)
        if event.get("type") == "response" and event.get("id") == request_id:
            return event
    raise AssertionError(f"Pi RPC ended before response {request_id}")


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
def test_goal_and_limit_are_persisted_by_deployed_extension(tmp_path: Path):
    process = subprocess.Popen(
        ["pi", "--mode", "rpc", "--no-session", "-e", str(EXTENSION)],
        cwd=tmp_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        send(process.stdin, {"id": "commands", "type": "get_commands"})
        commands = response(process.stdout, "commands")
        names = {
            command["name"]
            for command in commands["data"]["commands"]  # type: ignore[index]
        }
        assert {"agentvolve", "goal", "limit"} <= names

        send(
            process.stdin,
            {"id": "incomplete", "type": "prompt", "message": "/agentvolve"},
        )
        assert response(process.stdout, "incomplete")["success"] is True

        send(
            process.stdin,
            {"id": "goal", "type": "prompt", "message": "/goal solve the task"},
        )
        assert response(process.stdout, "goal")["success"] is True
        send(
            process.stdin,
            {"id": "limit", "type": "prompt", "message": '/limit "100 generations"'},
        )
        assert response(process.stdout, "limit")["success"] is True
        send(process.stdin, {"id": "entries", "type": "get_entries"})
        entries = response(process.stdout, "entries")["data"]["entries"]  # type: ignore[index]
        configurations = [
            entry["data"]
            for entry in entries
            if entry.get("type") == "custom"
            and entry.get("customType") == "agentvolve-workflow-configuration"
        ]
        assert configurations[-1] == {
            "goal": "solve the task",
            "maxRounds": 100,
        }
    finally:
        process.terminate()
        process.wait(timeout=10)
        stderr = process.stderr.read() if process.stderr is not None else ""
        assert stderr == ""
