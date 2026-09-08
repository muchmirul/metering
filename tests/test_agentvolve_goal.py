"""Deployed /goal review/start contract; inference and worker launch are test doubles."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / ".pi/extensions/population-evolution.ts"


class RPC:
    def __init__(self, process: subprocess.Popen[bytes]):
        self.process = process
        self.buffer = b""

    def send(self, value: dict) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(value).encode() + b"\n")
        self.process.stdin.flush()

    def event(self, deadline: float) -> dict:
        assert self.process.stdout is not None
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            assert remaining > 0, "Pi RPC timed out"
            ready, _, _ = select.select([self.process.stdout], [], [], remaining)
            assert ready, "Pi RPC timed out"
            chunk = os.read(self.process.stdout.fileno(), 65536)
            assert chunk, "Pi RPC terminated"
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line)

    def request(self, value: dict, dialog: Callable[[dict], dict] | None = None) -> list[dict]:
        self.send(value)
        events = []
        deadline = time.monotonic() + 60
        while True:
            event = self.event(deadline)
            events.append(event)
            if event.get("type") == "extension_ui_request" and event.get("method") in {"input", "confirm", "select", "editor"}:
                answer = dialog(event) if dialog else {"cancelled": True}
                self.send({"type": "extension_ui_response", "id": event["id"], **answer})
            if event.get("type") == "response" and event.get("id") == value["id"]:
                assert event["success"], event
                return events

    def prompt(self, text: str, dialog: Callable[[dict], dict] | None = None) -> list[dict]:
        return self.request({"id": text, "type": "prompt", "message": text}, dialog)

    def entries(self) -> list[dict]:
        return self.request({"id": "entries", "type": "get_entries"})[-1]["data"]["entries"]


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
@pytest.mark.parametrize("legacy_history", [False, True])
@pytest.mark.parametrize("underfunded", [False, True])
def test_goal_requires_limit_and_approval_then_keeps_limit(tmp_path: Path, legacy_history: bool, underfunded: bool):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "main.py").write_text("print('ok')\n")
    for args in (["init", "-q"], ["add", "main.py"], ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"]):
        subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True)
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    runs = tmp_path / "runs"  # Reading an empty history must not create this.
    launch_log = tmp_path / "launches.jsonl"
    prompt_log = tmp_path / "draft-prompts.jsonl"
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({"model": {"provider": "fixture", "model": "fixture", "reasoning": "off"}}))
    draft = {
        "draft_schema": "agentvolve-session-task-draft-v1", "schema_version": 1,
        "name": "goal-fixture", "repository_path": str(repository),
        "goal": "MODEL MUST NOT OVERRIDE USER GOAL", "entrypoint": "main.py",
        "allowed_paths": ["main.py"],
        "development_checks": [{"argv": ["python3", "main.py"], "case_id": "main", "timeout_ms": 1000}],
        "limits": {"max_rounds": 99, "max_proposal_calls": 99, "max_wall_seconds": 1800 if underfunded else 100000},
        "stopping": {"type": "all-development-cases-pass-v1", "minimum_replicates": 1},
        "final_policy": "replay-development-checks-v1",
    }
    provider = tmp_path / "provider.ts"
    provider.write_text('''import { appendFileSync } from "node:fs";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";
export default function(pi: any) {
  pi.registerProvider("goal-fixture", {
    baseUrl:"http://localhost.invalid", apiKey:"fixture", api:"goal-fixture-api",
    models:[{id:"fixture", name:"Fixture", reasoning:false, input:["text"],
      cost:{input:0, output:0, cacheRead:0, cacheWrite:0}, contextWindow:100000, maxTokens:4000}],
    streamSimple(model: any, context: any) {
      const stream = createAssistantMessageEventStream();
      queueMicrotask(() => {
        const drafting = context.systemPrompt.startsWith("You create an Agentvolve task draft");
        if (drafting) appendFileSync(process.env.GOAL_PROMPT_LOG!, JSON.stringify(context) + "\\n");
        const text = drafting ? process.env.GOAL_DRAFT! : "ASSISTANT_ANSWER_MUST_NOT_BECOME_TASK";
        const message: any = {role:"assistant", content:[{type:"text", text}],
          api:model.api, provider:model.provider, model:model.id, stopReason:"stop", timestamp:Date.now(),
          usage:{input:0, output:0, cacheRead:0, cacheWrite:0, totalTokens:0,
            cost:{input:0, output:0, cacheRead:0, cacheWrite:0, total:0}}};
        stream.push({type:"start", partial:message});
        stream.push({type:"text_start", contentIndex:0, partial:message});
        stream.push({type:"text_delta", contentIndex:0, delta:text, partial:message});
        stream.push({type:"text_end", contentIndex:0, content:text, partial:message});
        stream.push({type:"done", reason:"stop", message}); stream.end();
      }); return stream;
    }
  });
}
''')
    # Only intercept the detached start boundary, not task derivation/registration or projections.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv = bindir / "uv"
    uv.write_text(f'''#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
if args[:5] == ["run", "python", "-m", "connectors.fixed.pi.runtime", "check"]:
    print(json.dumps({{"runtime_selection_schema":"agentvolve-pi-runtime-selection-v1", "authority":"diagnostic-only"}}))
elif args[:5] == ["run", "python", "-m", "connectors.fixed.pi.runtime", "start"]:
    with open(os.environ["GOAL_LAUNCH_LOG"], "a") as log:
        log.write(json.dumps(args) + "\\n")
    print(json.dumps({{"worker_response_schema":"agentvolve-worker-response-v1", "action":"start", "pid":12345, "state":"queued", "workflow_id":"fixture", "workflow_root":args[5]+"/workflow-pi-20260906T190000000Z"}}))
else:
    os.execv({str(shutil.which("uv"))!r}, [{str(shutil.which("uv"))!r}, *args])
''')
    uv.chmod(0o755)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("METERING_EVOLUTION_")}
    environment.update({
        "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
        "METERING_EVOLUTION_TASKS_DIR": str(tasks), "METERING_EVOLUTION_RUNS_DIR": str(runs),
        "METERING_EVOLUTION_RUNTIME_MANIFEST": str(runtime),
        "GOAL_LAUNCH_LOG": str(launch_log), "GOAL_PROMPT_LOG": str(prompt_log), "GOAL_DRAFT": json.dumps(draft),
    })
    session = tmp_path / "session.jsonl"

    def start() -> subprocess.Popen[bytes]:
        return subprocess.Popen(["pi", "--mode", "rpc", "--session", str(session), "--no-extensions",
            "-e", str(EXTENSION), "-e", str(provider), "--provider", "goal-fixture", "--model", "fixture"],
            cwd=repository, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    process = start()
    try:
        rpc = RPC(process)
        rpc.prompt("/progress")
        assert not runs.exists()
        if legacy_history:
            stale = runs / "harness-pi-20260902T200200234Z"
            stale.mkdir(parents=True)
            (stale / "old-evidence.txt").write_text("Preserve this interrupted experiment.\n")
        rpc.prompt("Prior user context, not the task")
        while rpc.event(time.monotonic() + 10).get("type") != "agent_end":
            pass
        rpc.prompt("/goal Make main pass the reviewed check")  # cancel missing limit
        assert not launch_log.exists() and not prompt_log.exists()
        for invalid in ("0", "257", "2.5", "-1", "NaN", "1 extra"):
            events = rpc.prompt(f"/limit {invalid}")
            assert any("1 through 256" in str(event) for event in events)
        reviews = []

        def decline(event: dict) -> dict:
            if event["method"] == "input":
                if event["title"].startswith("Agentvolve budget"):
                    assert underfunded and "3680" in event["title"] and "25760" in event["title"]
                    return {"value": "30000"}
                return {"value": "7 generations"}
            if event["method"] == "confirm":
                reviews.append(event)
                return {"confirmed": False}
            return {"cancelled": True}

        rpc.prompt("/goal Make main pass the reviewed check", decline)
        assert reviews, "No direct task review occurred"
        review = json.dumps(reviews[-1])
        assert "7 generations, 7 proposal calls" in review
        assert "Make main pass the reviewed check" in review
        assert "MODEL MUST NOT OVERRIDE" not in review
        assert not launch_log.exists() and list(tasks.iterdir()) == []
        recorded_prompt = prompt_log.read_text()
        assert "Current /goal" in recorded_prompt
        assert "Prior user context" in recorded_prompt
        assert "ASSISTANT_ANSWER_MUST_NOT_BECOME_TASK" not in recorded_prompt

        if underfunded:
            events = rpc.prompt("/goal")  # cancel the budget correction
            assert any(event.get("title", "").startswith("Agentvolve budget") for event in events)
            assert not launch_log.exists() and list(tasks.iterdir()) == []

        budget_inputs = 0

        def approve(event: dict) -> dict:
            nonlocal budget_inputs
            if event["method"] == "input":
                assert underfunded and event["title"].startswith("Agentvolve budget"), "Saved /limit was lost"
                budget_inputs += 1
                return {"value": {1: "1800", 2: "1.5"}.get(budget_inputs, "30000")}
            if event["method"] == "select":
                return {"value": event["options"][0]}
            assert event["method"] == "confirm"
            reviews.append(event)
            assert not launch_log.exists(), "Worker launched before approval"
            assert "3680 seconds per generation" in event["message"]
            assert "25760" in event["message"]
            assert ("30000" if underfunded else "100000") in event["message"]
            return {"confirmed": True}

        events = rpc.prompt("/goal", approve)
        assert launch_log.exists(), events
        if legacy_history:
            assert any("unfinished legacy runs remain unchanged" in event.get("message", "") for event in events)
        launches = [json.loads(line) for line in launch_log.read_text().splitlines()]
        assert len(launches) == 1
        profile = json.loads(Path(launches[0][6]).read_text())
        assert profile["goal"] == "Make main pass the reviewed check"
        assert profile["limits"]["max_rounds"] == 7
        assert profile["limits"]["max_proposal_calls"] == 7
        assert profile["limits"]["max_wall_seconds"] == (30000 if underfunded else 100000)
        assert budget_inputs == (3 if underfunded else 0)
        configurations = [entry["data"] for entry in rpc.entries() if entry.get("customType") == "agentvolve-workflow-configuration"]
        assert configurations[-1] == {"maxRounds": 7}
        rpc.prompt("/limit 3")
        assert json.loads(Path(launches[0][6]).read_text()) == profile
        rpc.prompt("/goal")  # no implicit restart after successful launch
        assert len(launch_log.read_text().splitlines()) == 1
    finally:
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr is not None
        assert process.stderr.read() == b""

    # Simulate a separately stored, pre-upgrade template with an impossible budget.
    # Its correction must create a new profile rather than modifying this source.
    legacy_template = None
    legacy_template_bytes = None
    if underfunded:
        template_document = json.loads(json.dumps(profile))
        template_document["limits"]["max_wall_seconds"] = 1800
        legacy_template = tasks / "000-underfunded.task.json"
        legacy_template_bytes = (json.dumps(template_document, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
        legacy_template.write_bytes(legacy_template_bytes)

    # Reloading/restoring configuration is not a launch. The next reviewed goal uses the saved limit.
    process = start()
    try:
        rpc = RPC(process)
        assert len(launch_log.read_text().splitlines()) == 1
        configurations = [entry["data"] for entry in rpc.entries() if entry.get("customType") == "agentvolve-workflow-configuration"]
        assert configurations[-1] == {"maxRounds": 3}
        seen = []

        def approve_template(event: dict) -> dict:
            seen.append(event)
            if event["method"] == "select":
                if underfunded:
                    assert "000-underfunded" in event["options"][0]
                return {"value": event["options"][0]}
            if event["method"] == "input":
                assert underfunded and event["title"].startswith("Agentvolve budget")
                assert "3680" in event["title"] and "11040" in event["title"]
                return {"value": "11040"}
            assert event["method"] == "confirm"
            assert "3 generations" in json.dumps(event)
            assert "New independently checked goal" in json.dumps(event)
            assert len(launch_log.read_text().splitlines()) == 1
            return {"confirmed": True}

        events = rpc.prompt("/goal New independently checked goal", approve_template)
        assert len(launch_log.read_text().splitlines()) == 2, events
        assert [event["method"] for event in seen] == (["select", "input", "confirm"] if underfunded else ["select", "confirm"])
        if underfunded:
            assert legacy_template.read_bytes() == legacy_template_bytes
            second = json.loads(launch_log.read_text().splitlines()[-1])
            assert Path(second[6]) != legacy_template
            assert json.loads(Path(second[6]).read_text())["limits"]["max_wall_seconds"] == 11040
        if legacy_history:
            assert list(runs.iterdir()) == [stale]
            assert (stale / "old-evidence.txt").read_text() == "Preserve this interrupted experiment.\n"
            assert list(stale.iterdir()) == [stale / "old-evidence.txt"]
        else:
            assert not runs.exists(), "Test double must not create real workflow state"
    finally:
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr is not None
        assert process.stderr.read() == b""
