"""Existing operator targets are revalidated without mandatory path dialogs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_agentvolve_goal import EXTENSION, RPC


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
@pytest.mark.parametrize("target_kind", ["missing", "dirty", "untracked", "unborn", "bare", "mismatch"])
def test_existing_target_errors_do_not_draft_or_start(tmp_path: Path, target_kind: str):
    target = tmp_path / "target"
    if target_kind != "missing":
        subprocess.run(["git", "init", "-q", *(["--bare"] if target_kind == "bare" else []), str(target)], check=True, capture_output=True)
    if target_kind in {"dirty", "untracked", "mismatch"}:
        (target / "main.py").write_text("print('ok')\n")
        for args in (["add", "main.py"], ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"]):
            subprocess.run(["git", *args], cwd=target, check=True, capture_output=True)
    if target_kind == "dirty":
        (target / "main.py").write_text("uncommitted tracked change\n")
    if target_kind == "untracked":
        (target / "new.py").write_text("untracked file\n")
    tasks, runs = tmp_path / "tasks", tmp_path / "runs"
    session = tmp_path / "session.jsonl"
    session.write_text("\n".join(json.dumps(entry) for entry in [
        {"type": "session", "version": 3, "id": "repo-errors", "timestamp": "2026-09-09T00:00:00Z", "cwd": str(tmp_path)},
        {"type": "custom", "id": "1234abcd", "parentId": None, "timestamp": "2026-09-09T00:00:00Z",
         "customType": "agentvolve-workflow-configuration", "data": {"repository": str(target), "maxRounds": 2}},
    ]) + "\n")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("METERING_EVOLUTION_")}
    environment.update({"METERING_EVOLUTION_TASKS_DIR": str(tasks), "METERING_EVOLUTION_RUNS_DIR": str(runs)})
    if target_kind == "mismatch":
        profile = tmp_path / "configured.task.json"
        profile.write_text(json.dumps({"repository": {"path": str(tmp_path / "other")}}))
        environment["METERING_EVOLUTION_TASK_PROFILE"] = str(profile)
    process = subprocess.Popen(
        ["pi", "--mode", "rpc", "--session", str(session), "--no-extensions", "-e", str(EXTENSION)],
        cwd=tmp_path, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        rpc = RPC(process)
        events = rpc.prompt("/goal Test the selected project")
        diagnostic = {
            "dirty": "uncommitted changes", "untracked": "uncommitted changes",
            "unborn": "readable committed HEAD", "mismatch": "configured task belongs to another repository",
        }.get(target_kind, "Cannot open Git repository")
        assert any(diagnostic in event.get("message", "") for event in events), events
        assert not any(event.get("method") in {"input", "select"} for event in events)
        assert all(event.get("title") == "Use a new private workspace instead?" for event in events if event.get("method") == "confirm")
        assert not tasks.exists() and not runs.exists()
        if target_kind == "dirty":
            assert (target / "main.py").read_text() == "uncommitted tracked change\n"
        if target_kind == "untracked":
            assert (target / "new.py").read_text() == "untracked file\n"
    finally:
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr is not None
        assert process.stderr.read() == b""
