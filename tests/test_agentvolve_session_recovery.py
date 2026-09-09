"""Deploy the extension and exercise recovery through real Pi tool calls/RPC review."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_agentvolve_goal import EXTENSION, RPC
from test_agentvolve_recovery import launch  # noqa: F401 -- shared fixture
from apps.coding_agent import agentvolve_worker as worker


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
def test_session_management_and_goal_recovery_require_direct_approval(tmp_path, launch, monkeypatch):  # noqa: F811
    root = Path(launch()["workflow_root"])
    # End the fixture's subprocess patch before actually deploying Pi.
    monkeypatch.undo()
    request = worker.load_workflow_request(root)
    solution = Path(request["solution_run_root"])
    pending = solution / "state/pending/round-intent.json"
    pending.parent.mkdir(parents=True)
    pending.write_text('{"controller_receipt":null,"stage":"controller_pending"}\n')
    snapshot = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    provider = tmp_path / "provider.ts"
    provider.write_text('''import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";
export default function(pi: any) {
  pi.registerProvider("recovery-fixture", {
    baseUrl:"http://localhost.invalid", apiKey:"fixture", api:"recovery-fixture-api",
    models:[{id:"fixture", name:"Fixture", reasoning:false, input:["text"],
      cost:{input:0, output:0, cacheRead:0, cacheWrite:0}, contextWindow:100000, maxTokens:4000}],
    streamSimple(model: any, context: any) {
      const stream = createAssistantMessageEventStream();
      queueMicrotask(() => {
        const call = context.messages.at(-1)?.role === "user";
        const block = call ? {type:"toolCall", id:"manage", name:"darwinian_coding", arguments:{action:"workflow_manage"}}
          : {type:"text", text:"Management result received."};
        const message: any = {role:"assistant", content:[block], api:model.api, provider:model.provider, model:model.id,
          stopReason:call ? "toolUse" : "stop", timestamp:Date.now(), usage:{input:0, output:0, cacheRead:0, cacheWrite:0,
          totalTokens:0, cost:{input:0, output:0, cacheRead:0, cacheWrite:0, total:0}}};
        stream.push({type:"start", partial:message});
        if (call) { stream.push({type:"toolcall_start", contentIndex:0, partial:message});
          stream.push({type:"toolcall_end", contentIndex:0, toolCall:block, partial:message}); }
        stream.push({type:"done", reason:message.stopReason, message}); stream.end();
      }); return stream;
    }
  });
}
''')
    # Only inference/runtime launch is doubled. Registry, locks, closure, and views are real.
    log = tmp_path / "effects.jsonl"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv = bindir / "uv"
    real_uv = shutil.which("uv")
    uv.write_text(f'''#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
if args[:4] == ["run", "python", "-m", "connectors.fixed.pi.runtime"]:
    with open({str(log)!r}, "a") as output: output.write(json.dumps(args) + "\\n")
    if args[4] == "check": print('{{}}')
    else: print(json.dumps({{"worker_response_schema":"agentvolve-worker-response-v1", "workflow_id":{request["workflow_id"]!r},
        "workflow_root":args[5], "action":args[4], "pid":12345, "state":"queued"}}))
else: os.execv({real_uv!r}, [{real_uv!r}, *args])
''')
    uv.chmod(0o755)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("METERING_EVOLUTION_")}
    environment.update({"PATH": str(bindir) + os.pathsep + os.environ["PATH"],
        "METERING_EVOLUTION_RUNS_DIR": str(tmp_path / "runs"),
        # Recovery must use the original manifest, NOT this deliberately absent current setting.
        "METERING_EVOLUTION_RUNTIME_MANIFEST": str(tmp_path / "wrong-runtime.json")})
    process = subprocess.Popen(["pi", "--mode", "rpc", "--no-session", "--no-extensions", "-e", str(EXTENSION),
        "-e", str(provider), "--provider", "recovery-fixture", "--model", "fixture"], cwd=tmp_path, env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        rpc = RPC(process)

        def manage(dialog):
            rpc.prompt("Please manage the interrupted Agentvolve workflow", dialog)
            deadline = time.monotonic() + 30
            while True:
                event = rpc.event(deadline)
                if event.get("type") == "extension_ui_request" and event.get("method") in {"input", "select", "confirm"}:
                    rpc.send({"type": "extension_ui_response", "id": event["id"], **dialog(event)})
                if event.get("type") == "agent_end":
                    result = [message for message in event["messages"] if message.get("role") == "toolResult"][-1]
                    assert result["isError"] is False, result
                    return result

        def retry_review(approved):
            def dialog(event):
                if event["method"] == "select":
                    options = event["options"]
                    if event["title"].startswith("Manage an Agentvolve"):
                        return {"value": options[0]}
                    assert "Resume workflow" not in options
                    return {"value": "Retry one reserved attempt"}
                if event["method"] == "input":
                    return {"value": "Operator approves exactly one fixture retry"}
                assert event["method"] == "confirm"
                assert str(root) in event["message"]
                assert request["runtime_manifest"] in event["message"]
                assert "remaining reserved call/time budget" in event["message"]
                assert not log.exists(), "Runtime effects occurred before direct approval"
                return {"confirmed": approved}
            return dialog

        assert manage(retry_review(False))["details"]["status"] == "cancelled"
        assert not log.exists()
        assert all(path.read_bytes() == payload for path, payload in snapshot.items())
        assert manage(retry_review(True))["details"]["status"] == "queued"
        effects = [json.loads(line) for line in log.read_text().splitlines()]
        # The recovery launcher resolves the job-owned pin; the adapter must not
        # first resolve a potentially different ambient interactive Pi command.
        assert [effect[4:] for effect in effects] == [["retry", str(root), "Operator approves exactly one fixture retry"]]
        assert len(list((root / "jobs").glob("*.json"))) == 1, "Runtime launch is a double, not live recovery"
        log.unlink()

        # /goal handles blockers before task/model preparation; cancelling cannot retire a run.
        rpc.prompt("/limit 2")
        events = rpc.prompt("/goal A different task", lambda e: {"value": "2"} if e.get("title", "").startswith("Enter the exact") else {"cancelled": True})
        assert any(event.get("title", "").startswith("Agentvolve workflow:") for event in events)
        assert not (root / "closed.json").exists()
        assert not log.exists()

        def close_review(event):
            if event["method"] == "select":
                return {"value": "Close as incomplete (keep evidence)"}
            if event["method"] == "input":
                if event["title"].startswith("Agentvolve worker runtime"):
                    return {"cancelled": True}  # The next task needs its own worker setup.
                return {"value": "2" if event["title"].startswith("Enter the exact") else "Operator leaves the old failed task in history"}
            assert event["method"] == "confirm"
            assert "INCOMPLETE, not successful" in event["message"]
            assert not (root / "closed.json").exists()
            return {"confirmed": True}

        rpc.prompt("/goal", close_review)
        assert worker.load_workflow_closure(root) is not None
        assert all(path.read_bytes() == payload for path, payload in snapshot.items())
        assert pending.read_text() == '{"controller_receipt":null,"stage":"controller_pending"}\n'
        assert worker.registry_status(tmp_path / "runs")["blocker"] is None
        # Recovery completes; cancel the next task's session-native worker configuration.
        assert not log.exists()
        assert len(list((tmp_path / "runs").glob("workflow-*"))) == 1
        assert manage(lambda event: {"value": event["options"][0]})["details"]["status"] == "closed-incomplete"
    finally:
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr is not None
        assert process.stderr.read() == b""
