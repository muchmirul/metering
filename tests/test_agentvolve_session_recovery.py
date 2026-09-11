"""Exercise explicit, non-modal recovery through deployed Pi tool calls."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_agentvolve_goal import EXTENSION, RPC
from test_agentvolve_recovery import launch as launch_fixture  # noqa: F401 -- fixture
from apps.coding_agent import agentvolve_worker as worker


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
def test_session_management_uses_explicit_arguments_without_modal_approval(
    tmp_path, launch_fixture, monkeypatch  # noqa: F811
):
    root = Path(launch_fixture()["workflow_root"])
    monkeypatch.undo()
    request = worker.load_workflow_request(root)
    solution = Path(request["solution_run_root"])
    pending = solution / "state/pending/round-intent.json"
    pending.parent.mkdir(parents=True)
    pending.write_text('{"controller_receipt":null,"stage":"controller_pending"}\n')
    snapshot = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    provider = tmp_path / "provider.ts"
    provider.write_text(
        '''import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";
export default function(pi: any) {
  pi.registerProvider("recovery-fixture", {
    baseUrl:"http://localhost.invalid", apiKey:"fixture", api:"recovery-fixture-api",
    models:[{id:"fixture", name:"Fixture", reasoning:false, input:["text"],
      cost:{input:0, output:0, cacheRead:0, cacheWrite:0}, contextWindow:100000, maxTokens:4000}],
    streamSimple(model: any, context: any) {
      const stream = createAssistantMessageEventStream();
      queueMicrotask(() => {
        const call = context.messages.at(-1)?.role === "user";
        const request = call ? JSON.stringify(context.messages.at(-1).content) : "";
        const management_action = request.includes("retry") ? "retry"
          : request.includes("close") ? "close" : undefined;
        const reason = management_action === "retry" ? "Operator authorizes exactly one fixture retry"
          : management_action ? "Operator leaves the old failed task in history" : undefined;
        const args = {action:"workflow_manage", workflow:process.env.RECOVERY_ROOT,
          ...(management_action ? {management_action, reason} : {})};
        const block = call ? {type:"toolCall", id:"manage", name:"darwinian_coding", arguments:args}
          : {type:"text", text:"Management result received."};
        const message: any = {role:"assistant", content:[block], api:model.api, provider:model.provider,
          model:model.id, stopReason:call ? "toolUse" : "stop", timestamp:Date.now(),
          usage:{input:0, output:0, cacheRead:0, cacheWrite:0, totalTokens:0,
            cost:{input:0, output:0, cacheRead:0, cacheWrite:0, total:0}}};
        stream.push({type:"start", partial:message});
        if (call) { stream.push({type:"toolcall_start", contentIndex:0, partial:message});
          stream.push({type:"toolcall_end", contentIndex:0, toolCall:block, partial:message}); }
        stream.push({type:"done", reason:message.stopReason, message}); stream.end();
      }); return stream;
    }
  });
}
'''
    )
    log = tmp_path / "effects.jsonl"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv = bindir / "uv"
    real_uv = shutil.which("uv")
    uv.write_text(
        f'''#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
if args[:4] == ["run", "python", "-m", "connectors.fixed.pi.runtime"]:
    with open({str(log)!r}, "a") as output: output.write(json.dumps(args) + "\\n")
    print(json.dumps({{"worker_response_schema":"agentvolve-worker-response-v1", "workflow_id":{request["workflow_id"]!r},
        "workflow_root":args[5], "action":args[4], "pid":12345, "state":"queued"}}))
else: os.execv({real_uv!r}, [{real_uv!r}, *args])
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
            "RECOVERY_ROOT": str(root),
            "METERING_EVOLUTION_RUNS_DIR": str(tmp_path / "runs"),
            "METERING_EVOLUTION_RUNTIME_MANIFEST": str(tmp_path / "wrong-runtime.json"),
        }
    )
    process = subprocess.Popen(
        [
            "pi",
            "--mode",
            "rpc",
            "--no-session",
            "--no-extensions",
            "-e",
            str(EXTENSION),
            "-e",
            str(provider),
            "--provider",
            "recovery-fixture",
            "--model",
            "fixture",
        ],
        cwd=tmp_path,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        rpc = RPC(process)

        def manage(instruction):
            events = rpc.prompt(instruction)
            assert not [
                event
                for event in events
                if event.get("method") in {"input", "select", "confirm", "editor"}
            ]
            deadline = time.monotonic() + 30
            while True:
                event = rpc.event(deadline)
                assert event.get("type") != "extension_ui_request" or event.get(
                    "method"
                ) not in {"input", "select", "confirm", "editor"}
                if event.get("type") == "agent_end":
                    value = [
                        message
                        for message in event["messages"]
                        if message.get("role") == "toolResult"
                    ][-1]
                    assert value["isError"] is False, value
                    return value

        choices = manage("Please inspect the interrupted Agentvolve workflow")
        assert choices["details"]["status"] == "needs-action"
        assert set(choices["details"]["actions"]) >= {"retry", "close"}
        assert not log.exists()
        assert all(path.read_bytes() == payload for path, payload in snapshot.items())

        retried = manage("Please retry the interrupted Agentvolve workflow")
        assert retried["details"]["status"] == "queued"
        effects = [json.loads(line) for line in log.read_text().splitlines()]
        assert [effect[4:] for effect in effects] == [
            ["retry", str(root), "Operator authorizes exactly one fixture retry"]
        ]
        assert len(list((root / "jobs").glob("*.json"))) == 1
        log.unlink()

        # A blocker is returned as data and cannot implicitly retire evidence.
        rpc.prompt("/limit 2")
        events = rpc.prompt("/goal A different task")
        assert not [
            event
            for event in events
            if event.get("method") in {"input", "select", "confirm", "editor"}
        ]
        deadline = time.monotonic() + 30
        while True:
            submissions = [
                entry["data"]
                for entry in rpc.entries()
                if entry.get("customType") == "agentvolve-submission"
            ]
            if submissions and submissions[-1]["state"] == "not-launched":
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert "call workflow_manage with an applicable action" in submissions[-1]["diagnostic"]
        assert not (root / "closed.json").exists() and not log.exists()

        closed = manage("Please close the interrupted Agentvolve workflow")
        assert closed["details"]["status"] == "closed-incomplete"
        assert worker.load_workflow_closure(root) is not None
        assert all(path.read_bytes() == payload for path, payload in snapshot.items())
        assert pending.read_text() == '{"controller_receipt":null,"stage":"controller_pending"}\n'
        assert worker.registry_status(tmp_path / "runs")["blocker"] is None
        assert len(list((tmp_path / "runs").glob("workflow-*"))) == 1
        assert (
            manage("Please inspect the interrupted Agentvolve workflow")["details"][
                "status"
            ]
            == "closed-incomplete"
        )
    finally:
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr is not None
        assert process.stderr.read() == b""
