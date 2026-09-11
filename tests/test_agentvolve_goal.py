"""Deployed /goal background-start contract; inference and worker launch are doubles."""

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

    def request(
        self, value: dict, dialog: Callable[[dict], dict] | None = None
    ) -> list[dict]:
        self.send(value)
        events = []
        deadline = time.monotonic() + 60
        while True:
            event = self.event(deadline)
            events.append(event)
            if event.get("type") == "extension_ui_request" and event.get("method") in {
                "input",
                "confirm",
                "select",
                "editor",
            }:
                answer = dialog(event) if dialog else {"cancelled": True}
                self.send(
                    {"type": "extension_ui_response", "id": event["id"], **answer}
                )
            if event.get("type") == "response" and event.get("id") == value["id"]:
                assert event["success"], event
                return events

    def prompt(
        self, text: str, dialog: Callable[[dict], dict] | None = None
    ) -> list[dict]:
        return self.request({"id": text, "type": "prompt", "message": text}, dialog)

    def entries(self) -> list[dict]:
        return self.request({"id": "entries", "type": "get_entries"})[-1]["data"][
            "entries"
        ]


def _wait_for(path: Path, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, f"Timed out waiting for {path}"
        time.sleep(0.02)


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
def test_goal_uses_saved_validated_fields_without_modal_approval(tmp_path: Path):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "main.py").write_text("print('ok')\n")
    for args in (
        ["init", "-q"],
        ["add", "main.py"],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
    ):
        subprocess.run(
            ["git", *args], cwd=repository, check=True, capture_output=True
        )
    tasks = tmp_path / "tasks"
    runs = tmp_path / "runs"
    launch_log = tmp_path / "launches.jsonl"
    prompt_log = tmp_path / "draft-prompts.jsonl"
    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps(
            {"model": {"provider": "fixture", "model": "fixture", "reasoning": "off"}}
        )
    )
    draft = {
        "draft_schema": "agentvolve-session-task-draft-v1",
        "schema_version": 1,
        "name": "goal-fixture",
        "repository_path": str(repository),
        "goal": "MODEL MUST NOT OVERRIDE USER GOAL",
        "entrypoint": "main.py",
        "allowed_paths": ["main.py"],
        "development_checks": [
            {"argv": ["python3", "main.py"], "case_id": "main", "timeout_ms": 1000}
        ],
        "limits": {
            "max_rounds": 99,
            "max_proposal_calls": 99,
            "max_wall_seconds": 100000,
        },
        "stopping": {
            "type": "all-development-cases-pass-v1",
            "minimum_replicates": 1,
        },
        "final_policy": "replay-development-checks-v1",
    }
    provider = tmp_path / "provider.ts"
    provider.write_text(
        '''import { appendFileSync } from "node:fs";
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
        const text = drafting ? process.env.GOAL_DRAFT! : "ordinary response";
        const message: any = {role:"assistant", content:[{type:"text", text}], api:model.api,
          provider:model.provider, model:model.id, stopReason:"stop", timestamp:Date.now(),
          usage:{input:0, output:0, cacheRead:0, cacheWrite:0, totalTokens:0,
            cost:{input:0, output:0, cacheRead:0, cacheWrite:0, total:0}}};
        stream.push({type:"start", partial:message});
        stream.push({type:"text_start", contentIndex:0, partial:message});
        stream.push({type:"text_end", contentIndex:0, content:text, partial:message});
        stream.push({type:"done", reason:"stop", message}); stream.end();
      }); return stream;
    }
  });
}
'''
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv = bindir / "uv"
    uv.write_text(
        f'''#!{sys.executable}
import json, os, pathlib, sys
args = sys.argv[1:]
if args[:5] == ["run", "python", "-m", "connectors.fixed.pi.runtime", "prepare-registry"]:
    pathlib.Path(args[5]).mkdir(parents=True, exist_ok=True)
    print(json.dumps({{"registry_schema":"agentvolve-private-registry-v1", "runs_directory":args[5], "mode":"0700", "inference_performed":False}}))
elif args[:5] == ["run", "python", "-m", "connectors.fixed.pi.runtime", "review-configured"]:
    print(json.dumps({{"review_schema":"agentvolve-execution-review-v1", "authority":"diagnostic-only", "runtime_id":"a"*64, "harness_candidate_id":"b"*64, "worker_configuration":"/validated/worker", "runs_directory":args[8], "command":["/pinned/pi"], "model":{{"provider":"fixture", "model":"worker", "implementation_version":"0.84.4"}}}}))
elif args[:5] == ["run", "python", "-m", "connectors.fixed.pi.runtime", "ready-configured"]:
    print(json.dumps({{"readiness_schema":"agentvolve-worker-readiness-v1", "authority":"diagnostic-only", "provider":"fixture", "model":"fixture", "state":"ready", "inference_performed":False}}))
elif args[:5] == ["run", "python", "-m", "connectors.fixed.pi.runtime", "start-configured"]:
    with open(os.environ["GOAL_LAUNCH_LOG"], "a") as log: log.write(json.dumps(args) + "\\n")
    print(json.dumps({{"worker_response_schema":"agentvolve-worker-response-v1", "action":"start", "pid":12345, "state":"queued", "workflow_id":"a"*64, "workflow_root":args[5]+"/workflow-pi-20260906T190000000Z"}}))
elif args[:5] == ["run", "python", "-m", "apps.coding_agent.agentvolve_worker", "registry"]:
    print(json.dumps({{"registry_schema":"agentvolve-registry-status-v1", "authority":"projection-only", "blocker":None, "legacy_unfinished_count":0}}))
else:
    os.execv({str(shutil.which("uv"))!r}, [{str(shutil.which("uv"))!r}, *args])
'''
    )
    uv.chmod(0o755)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("METERING_EVOLUTION_")
    }
    environment.update(
        {
            "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
            "METERING_EVOLUTION_TASKS_DIR": str(tasks),
            "METERING_EVOLUTION_RUNS_DIR": str(runs),
            "METERING_EVOLUTION_RUNTIME_MANIFEST": str(runtime),
            "METERING_EVOLUTION_HARNESS_DESCRIPTOR": str(runtime),
            "METERING_PI_CONFIG_DIR": "/validated/worker",
            "GOAL_LAUNCH_LOG": str(launch_log),
            "GOAL_PROMPT_LOG": str(prompt_log),
            "GOAL_DRAFT": json.dumps(draft),
        }
    )
    session = tmp_path / "session.jsonl"
    process = subprocess.Popen(
        [
            "pi",
            "--mode",
            "rpc",
            "--session",
            str(session),
            "--no-extensions",
            "-e",
            str(EXTENSION),
            "-e",
            str(provider),
            "--provider",
            "goal-fixture",
            "--model",
            "fixture",
        ],
        cwd=repository,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        rpc = RPC(process)
        missing = rpc.prompt("/goal Make main pass the validated check")
        assert not [event for event in missing if event.get("method") in {"input", "select", "confirm", "editor"}]
        time.sleep(0.1)
        assert not launch_log.exists() and not prompt_log.exists()
        for invalid in ("0", "257", "2.5", "-1", "NaN", "1 extra"):
            events = rpc.prompt(f"/limit {invalid}")
            assert any("1 through 256" in str(event) for event in events)

        rpc.prompt("/limit 2")
        events = rpc.prompt("/goal Make main pass the validated check")
        assert not [event for event in events if event.get("method") in {"input", "select", "confirm", "editor"}]
        _wait_for(launch_log)
        launches = [json.loads(line) for line in launch_log.read_text().splitlines()]
        assert len(launches) == 1
        profile = json.loads(Path(launches[0][6]).read_text())
        assert profile["goal"] == "Make main pass the validated check"
        assert profile["repository"]["path"] == str(repository)
        assert profile["limits"]["max_rounds"] == 2
        assert profile["limits"]["max_proposal_calls"] == 2
        assert "MODEL MUST NOT OVERRIDE" not in json.dumps(profile)
        assert "Current /goal" in prompt_log.read_text()
        validations = [
            entry["data"]
            for entry in rpc.entries()
            if entry.get("customType") == "agentvolve-task-validation"
        ]
        assert validations and validations[-1]["authority"] == "validated-input-record"
    finally:
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr is not None
        assert process.stderr.read() == b""

    # Restoring the session changes no task and starts no process.
    before = launch_log.read_bytes()
    process = subprocess.Popen(
        [
            "pi",
            "--mode",
            "rpc",
            "--session",
            str(session),
            "--no-extensions",
            "-e",
            str(EXTENSION),
            "-e",
            str(provider),
            "--provider",
            "goal-fixture",
            "--model",
            "fixture",
        ],
        cwd=repository,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        rpc = RPC(process)
        rpc.entries()
        assert launch_log.read_bytes() == before
    finally:
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr is not None
        assert process.stderr.read() == b""
