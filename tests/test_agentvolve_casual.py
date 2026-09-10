"""Casual Pi sessions draft/review/start without any repository or path input."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_agentvolve_goal import EXTENSION, RPC
from test_workspace_profile import workspace_draft


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
@pytest.mark.parametrize("conversational", [False, True])
def test_casual_goal_prepares_only_after_approval_without_path_input(tmp_path: Path, conversational: bool):
    document, _, tasks = workspace_draft(tmp_path)
    raw_goal = "pls make answer.txt say done -- messy req, keep it simple"
    document["goal"] = raw_goal
    document["repository_path"] = "/model-must-not-choose-the-host-path"
    document["requirements"] = ["Write exactly done to answer.txt."]
    provider = tmp_path / "provider.ts"
    provider.write_text('''import { appendFileSync } from "node:fs";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";
export default function(pi: any) {
  pi.registerProvider("casual-fixture", {
    baseUrl:"http://localhost.invalid", apiKey:"fixture", api:"casual-fixture-api",
    models:[{id:"fixture", name:"Fixture", reasoning:false, input:["text"],
      cost:{input:0, output:0, cacheRead:0, cacheWrite:0}, contextWindow:100000, maxTokens:4000}],
    streamSimple(model: any, context: any) {
      const stream = createAssistantMessageEventStream();
      queueMicrotask(() => {
        const drafting = context.systemPrompt.startsWith("You create an Agentvolve task draft");
        if (drafting) appendFileSync(process.env.CASUAL_PROMPTS!, JSON.stringify(context) + "\\n");
        const tool = !drafting && context.messages.at(-1)?.role === "user";
        const block = tool ? {type:"toolCall", id:"casual-start", name:"darwinian_coding", arguments:{action:"workflow_from_session"}}
          : {type:"text", text:drafting ? process.env.CASUAL_DRAFT! : "Task review finished."};
        const message: any = {role:"assistant", content:[block], api:model.api, provider:model.provider,
          model:model.id, stopReason:tool ? "toolUse" : "stop", timestamp:Date.now(),
          usage:{input:0, output:0, cacheRead:0, cacheWrite:0, totalTokens:0,
            cost:{input:0, output:0, cacheRead:0, cacheWrite:0, total:0}}};
        stream.push({type:"start", partial:message});
        if (tool) {
          stream.push({type:"toolcall_start", contentIndex:0, partial:message});
          stream.push({type:"toolcall_end", contentIndex:0, toolCall:block, partial:message});
        } else {
          stream.push({type:"text_start", contentIndex:0, partial:message});
          stream.push({type:"text_delta", contentIndex:0, delta:block.text, partial:message});
          stream.push({type:"text_end", contentIndex:0, content:block.text, partial:message});
        }
        stream.push({type:"done", reason:message.stopReason, message}); stream.end();
      }); return stream;
    }
  });
}
''')
    bindir = tmp_path / "bin"
    bindir.mkdir()
    launch_log = tmp_path / "launches.jsonl"
    uv = bindir / "uv"
    real_uv = shutil.which("uv")
    uv.write_text(f'''#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
if args[:5] == ["run", "python", "-m", "connectors.fixed.pi.runtime", "check"]:
    print(json.dumps({{"runtime_selection_schema":"agentvolve-pi-runtime-selection-v1", "authority":"diagnostic-only"}}))
elif args[:5] == ["run", "python", "-m", "connectors.fixed.pi.runtime", "review-configured"]:
    print(json.dumps({{"review_schema":"agentvolve-execution-review-v1", "authority":"diagnostic-only", "runtime_id":"a"*64, "harness_candidate_id":"b"*64, "worker_configuration":"/reviewed/worker", "runs_directory":args[8], "command":["/pinned/pi"], "model":{{"provider":"fixture", "model":"worker", "implementation_version":"0.84.4"}}}}))
elif args[:5] == ["run", "python", "-m", "connectors.fixed.pi.runtime", "start-configured"]:
    with open(os.environ["CASUAL_LAUNCHES"], "a") as log:
        log.write(json.dumps(args) + "\\n")
    print(json.dumps({{"worker_response_schema":"agentvolve-worker-response-v1", "action":"start", "pid":12345,
        "state":"queued", "workflow_id":"a"*64, "workflow_root":args[5]+"/workflow-pi-20260906T190000000Z"}}))
else:
    os.execv({real_uv!r}, [{real_uv!r}, *args])
''')
    uv.chmod(0o755)
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({"model": {"provider": "fixture", "model": "fixture", "reasoning": "off"}}))
    environment = {key: value for key, value in os.environ.items() if not key.startswith("METERING_EVOLUTION_")}
    environment.update({
        "PATH": str(bindir) + os.pathsep + os.environ["PATH"], "METERING_EVOLUTION_TASKS_DIR": str(tasks),
        "METERING_EVOLUTION_RUNS_DIR": str(tmp_path / "runs"), "METERING_EVOLUTION_RUNTIME_MANIFEST": str(runtime),
        "METERING_EVOLUTION_HARNESS_DESCRIPTOR": str(runtime),  # review/launch double
        "METERING_PI_CONFIG_DIR": "/reviewed/worker",
        "CASUAL_DRAFT": json.dumps(document), "CASUAL_PROMPTS": str(tmp_path / "prompts.jsonl"), "CASUAL_LAUNCHES": str(launch_log),
    })
    process = subprocess.Popen(
        ["pi", "--mode", "rpc", "--no-session", "--no-extensions", "-e", str(EXTENSION), "-e", str(provider), "--provider", "casual-fixture", "--model", "fixture"],
        cwd=tmp_path, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        rpc = RPC(process)
        rpc.prompt("/limit 2")
        for approve in (False, True):
            reviews = []

            def review(event: dict) -> dict:
                if event["method"] == "input":
                    assert event["title"].startswith("Enter the exact"), "Casual tasks must not request a path"
                    return {"value": "2"}
                if event["method"] == "select":
                    assert event["title"] == "Task not approved"
                    return {"cancelled": True}
                assert event["method"] == "confirm"
                assert event["title"] == "Register and run this reviewed task?"
                assert "Requirements:" in event["message"] and "Inferred assumptions" in event["message"]
                assert "new empty seed" in event["message"] and raw_goal in event["message"]
                assert "2 generations" in event["message"]
                assert not launch_log.exists() and not tasks.exists(), "No setup effects before approval"
                reviews.append(event)
                return {"confirmed": approve}

            message = f"Agentvolve, solve this: {raw_goal}" if conversational else f"/goal {raw_goal}"
            events = rpc.prompt(message, review)
            if conversational:
                while True:
                    event = rpc.event(time.monotonic() + 60)
                    events.append(event)
                    if event.get("type") == "extension_ui_request" and event.get("method") in {"input", "select", "confirm", "editor"}:
                        rpc.send({"type": "extension_ui_response", "id": event["id"], **review(event)})
                    if event.get("type") == "agent_end":
                        break
            assert reviews, events
            if not approve:
                assert not tasks.exists() and not launch_log.exists()
        launches = [json.loads(line) for line in launch_log.read_text().splitlines()]
        assert len(launches) == 1
        profile = json.loads(Path(launches[0][6]).read_text())
        root = Path(profile["repository"]["path"])
        assert root.parent == tasks / "workspaces"
        assert not (tmp_path / ".git").exists(), "Pi's casual session directory must stay untouched"
        assert (root / "answer.txt").read_bytes() == b"", "Setup must not substitute an in-place solution"
        assert raw_goal in (root / "TASK.md").read_text()
        assert "Write exactly done" in (root / "TASK.md").read_text()
        assert profile["limits"]["max_rounds"] == 2
        assert profile["goal"] == raw_goal
        configurations = [entry["data"] for entry in rpc.entries() if entry.get("customType") == "agentvolve-workflow-configuration"]
        assert configurations[-1] == {"maxRounds": 2}, "A later unrelated task should get a fresh workspace"
    finally:
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr is not None
        assert process.stderr.read() == b""
