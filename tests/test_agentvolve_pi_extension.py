"""Deployed Pi-extension checks with no network model calls."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import TextIO

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / ".pi" / "extensions" / "population-evolution.ts"


def send(stream: TextIO, document: dict[str, object]) -> None:
    stream.write(json.dumps(document, separators=(",", ":")) + "\n")
    stream.flush()


def response(
    stream: TextIO,
    request_id: str,
    events: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    for line in stream:
        event = json.loads(line)
        if events is not None:
            events.append(event)
        if event.get("type") == "response" and event.get("id") == request_id:
            return event
    raise AssertionError(f"Pi RPC ended before response {request_id}")


def emitted_event(stream: TextIO, event_type: str) -> dict[str, object]:
    for line in stream:
        event = json.loads(line)
        if event.get("type") == event_type:
            return event
    raise AssertionError(f"Pi RPC ended before event {event_type}")


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
def test_goal_and_limit_are_persisted_by_deployed_extension(tmp_path: Path):
    runs = tmp_path / "runs"
    tasks = tmp_path / "tasks"
    stale = runs / "harness-pi-20260904T111122200Z"
    stale.mkdir(parents=True)
    tasks.mkdir()
    (stale / "process-status.json").write_text(
        json.dumps(
            {
                "authority": "projection-only",
                "display": "[2/6] Evolving harness",
                "process_schema": "darwinian-coding-process-v1",
                "run_kind": "harness",
                "stage": 2,
                "stage_label": "Evolving harness",
                "total_stages": 6,
            }
        ),
        encoding="utf-8",
    )
    inspector = tmp_path / "inspect-agentvolve-tool.ts"
    inspector.write_text(
        """import type { ExtensionAPI } from \"@earendil-works/pi-coding-agent\";
export default function (pi: ExtensionAPI) {
  pi.registerCommand(\"inspect-agentvolve-tool\", {
    description: \"Persist the deployed Agentvolve tool metadata for this test\",
    handler: async () => {
      const tool = pi.getAllTools().find((candidate) => candidate.name === \"darwinian_coding\");
      pi.appendEntry(\"agentvolve-tool-inspection\", tool ?? null);
    },
  });
}
""",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [
            "pi",
            "--mode",
            "rpc",
            "--no-session",
            "-e",
            str(EXTENSION),
            "-e",
            str(inspector),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "METERING_EVOLUTION_RUNS_DIR": str(runs),
            "METERING_EVOLUTION_TASKS_DIR": str(tasks),
        },
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
        assert {
            "agentvolve",
            "agentvolve-resume",
            "agentvolve-retry",
            "agentvolve-stop",
            "agentvolve-verify",
            "evolve-start",
            "goal",
            "limit",
            "view-history",
            "view-progress",
        } <= names

        send(
            process.stdin,
            {"id": "incomplete", "type": "prompt", "message": "/agentvolve"},
        )
        monitor_events: list[dict[str, object]] = []
        assert response(process.stdout, "incomplete", monitor_events)["success"] is True

        send(
            process.stdin,
            {"id": "goal", "type": "prompt", "message": "/goal solve the task"},
        )
        assert response(process.stdout, "goal", monitor_events)["success"] is True
        send(
            process.stdin,
            {"id": "limit", "type": "prompt", "message": '/limit "100 generations"'},
        )
        assert response(process.stdout, "limit", monitor_events)["success"] is True
        send(process.stdin, {"id": "entries", "type": "get_entries"})
        entries_response = response(process.stdout, "entries", monitor_events)
        entries = entries_response["data"]["entries"]  # type: ignore[index]
        active_widgets = [
            event
            for event in monitor_events
            if event.get("type") == "extension_ui_request"
            and event.get("method") == "setWidget"
            and "widgetLines" in event
        ]
        assert active_widgets == []
        assert str(stale) not in json.dumps(monitor_events)
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
        mode_entries = [
            entry["data"]
            for entry in entries
            if entry.get("type") == "custom"
            and entry.get("customType") == "agentvolve-mode"
        ]
        assert mode_entries[-1] == {"active": True, "modelMode": "routed"}

        current = runs / "workflow-pi-20260906T190000000Z"
        current.mkdir()
        (current / "worker-status.json").write_text(
            json.dumps(
                {
                    "authority": "projection-only",
                    "stage": 1,
                    "stage_label": "Task and runtime configured",
                    "state": "queued",
                    "status_schema": "agentvolve-worker-status-v1",
                    "updated_unix_ns": time.time_ns(),
                    "workflow_id": "active-test",
                }
            ),
            encoding="utf-8",
        )
        time.sleep(2.2)
        send(process.stdin, {"id": "active-widget", "type": "get_entries"})
        active_events: list[dict[str, object]] = []
        assert response(process.stdout, "active-widget", active_events)["success"] is True
        widgets = [
            event
            for event in active_events
            if event.get("type") == "extension_ui_request"
            and event.get("method") == "setWidget"
            and "widgetLines" in event
        ]
        assert len(widgets) == 1
        assert str(current) in json.dumps(widgets[0])
        assert str(stale) not in json.dumps(widgets[0])

        current_status = json.loads((current / "worker-status.json").read_text())
        current_status["state"] = "completed"
        current_status["updated_unix_ns"] = time.time_ns()
        (current / "worker-status.json").write_text(
            json.dumps(current_status),
            encoding="utf-8",
        )
        time.sleep(2.2)
        send(process.stdin, {"id": "cleared-widget", "type": "get_entries"})
        cleared_events: list[dict[str, object]] = []
        assert response(process.stdout, "cleared-widget", cleared_events)["success"] is True
        widget_updates = [
            event
            for event in cleared_events
            if event.get("type") == "extension_ui_request"
            and event.get("method") == "setWidget"
        ]
        assert widget_updates
        assert all("widgetLines" not in event for event in widget_updates)

        send(
            process.stdin,
            {
                "id": "inspect-tool",
                "type": "prompt",
                "message": "/inspect-agentvolve-tool",
            },
        )
        assert response(process.stdout, "inspect-tool")["success"] is True
        send(process.stdin, {"id": "tool-entries", "type": "get_entries"})
        tool_entries = response(process.stdout, "tool-entries")["data"][  # type: ignore[index]
            "entries"
        ]
        tool_metadata = [
            entry["data"]
            for entry in tool_entries
            if entry.get("type") == "custom"
            and entry.get("customType") == "agentvolve-tool-inspection"
        ][-1]
        encoded_tool = json.dumps(tool_metadata, sort_keys=True)
        for action in (
            "workflow_activate",
            "workflow_from_session",
            "workflow_start",
            "workflow_status",
            "workflow_history",
            "workflow_verify",
        ):
            assert action in encoded_tool
        assert "action schema accepts no" in encoded_tool
    finally:
        process.terminate()
        process.wait(timeout=10)
        stderr = process.stderr.read() if process.stderr is not None else ""
        assert stderr == ""


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
def test_model_facing_controls_execute_without_starting_a_workflow(tmp_path: Path):
    provider = tmp_path / "fake-agentvolve-provider.ts"
    provider.write_text(
        """import type { ExtensionAPI } from \"@earendil-works/pi-coding-agent\";
import { createAssistantMessageEventStream } from \"@earendil-works/pi-ai\";

function assistant(model: any) {
  return {
    role: \"assistant\", content: [], api: model.api, provider: model.provider,
    model: model.id, stopReason: \"pending\", timestamp: Date.now(),
    usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
  };
}

function streamFake(model: any, context: any) {
  const stream = createAssistantMessageEventStream();
  queueMicrotask(() => {
    const message = assistant(model);
    stream.push({ type: \"start\", partial: message });
    const last = context.messages.at(-1);
    if (last?.role === \"user\") {
      const request = JSON.stringify(last);
      const action = request.includes(\"history\") ? \"workflow_history\"
        : request.includes(\"progress\") ? \"workflow_status\"
        : request.includes(\"start\") ? \"workflow_start\"
        : \"workflow_activate\";
      const call = { type: \"toolCall\", id: `${action}-1`, name: \"darwinian_coding\",
        arguments: { action } };
      message.content.push(call);
      stream.push({ type: \"toolcall_start\", contentIndex: 0, partial: message });
      stream.push({ type: \"toolcall_end\", contentIndex: 0, toolCall: call, partial: message });
      message.stopReason = \"toolUse\";
    } else {
      const block = { type: \"text\", text: \"Agentvolve is active.\" };
      message.content.push(block);
      stream.push({ type: \"text_start\", contentIndex: 0, partial: message });
      stream.push({ type: \"text_delta\", contentIndex: 0, delta: block.text, partial: message });
      stream.push({ type: \"text_end\", contentIndex: 0, content: block.text, partial: message });
      message.stopReason = \"stop\";
    }
    stream.push({ type: \"done\", reason: message.stopReason, message });
    stream.end();
  });
  return stream;
}

export default function (pi: ExtensionAPI) {
  pi.registerProvider(\"fake-agentvolve\", {
    baseUrl: \"http://localhost.invalid\", apiKey: \"test\", api: \"fake-agentvolve-api\" as any,
    models: [{ id: \"fake\", name: \"Fake\", reasoning: false, input: [\"text\"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 100000, maxTokens: 1000 }],
    streamSimple: streamFake as any,
  });
}
""",
        encoding="utf-8",
    )
    runs = tmp_path / "runs"
    tasks = tmp_path / "tasks"
    runs.mkdir()
    tasks.mkdir()
    process = subprocess.Popen(
        [
            "pi",
            "--mode",
            "rpc",
            "--no-session",
            "-e",
            str(EXTENSION),
            "-e",
            str(provider),
            "--provider",
            "fake-agentvolve",
            "--model",
            "fake",
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "METERING_EVOLUTION_RUNS_DIR": str(runs),
            "METERING_EVOLUTION_TASKS_DIR": str(tasks),
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        send(
            process.stdin,
            {"id": "activate", "type": "prompt", "message": "activate Agentvolve"},
        )
        assert response(process.stdout, "activate")["success"] is True
        completed = emitted_event(process.stdout, "agent_end")
        messages = completed["messages"]  # type: ignore[index]
        tool_calls = [
            block
            for message in messages
            if message.get("role") == "assistant"
            for block in message.get("content", [])
            if block.get("type") == "toolCall"
        ]
        assert tool_calls == [
            {
                "type": "toolCall",
                "id": "workflow_activate-1",
                "name": "darwinian_coding",
                "arguments": {"action": "workflow_activate"},
            }
        ]
        tool_results = [message for message in messages if message.get("role") == "toolResult"]
        assert tool_results[-1]["isError"] is False
        assert tool_results[-1]["details"]["status"] == "operator-mode"
        assert "No task or worker was started" in tool_results[-1]["content"][0]["text"]

        for request_id, request_text, action, detail_key, detail_value in (
            ("progress", "show progress", "workflow_status", "status", "idle"),
            ("history", "show history", "workflow_history", "runs", []),
            (
                "start",
                "start the workflow",
                "workflow_start",
                "status",
                "needs-task-clarification",
            ),
        ):
            send(
                process.stdin,
                {"id": request_id, "type": "prompt", "message": request_text},
            )
            assert response(process.stdout, request_id)["success"] is True
            completed = emitted_event(process.stdout, "agent_end")
            messages = completed["messages"]  # type: ignore[index]
            latest_call = [
                block
                for message in messages
                if message.get("role") == "assistant"
                for block in message.get("content", [])
                if block.get("type") == "toolCall"
            ][-1]
            latest_result = [
                message for message in messages if message.get("role") == "toolResult"
            ][-1]
            assert latest_call["arguments"] == {"action": action}
            assert latest_result["isError"] is False
            assert latest_result["details"][detail_key] == detail_value

        send(process.stdin, {"id": "entries", "type": "get_entries"})
        entries = response(process.stdout, "entries")["data"]["entries"]  # type: ignore[index]
        mode_entries = [
            entry["data"]
            for entry in entries
            if entry.get("type") == "custom"
            and entry.get("customType") == "agentvolve-mode"
        ]
        assert mode_entries[-1] == {"active": True, "modelMode": "routed"}
        assert list(runs.iterdir()) == []
    finally:
        process.terminate()
        process.wait(timeout=10)
        stderr = process.stderr.read() if process.stderr is not None else ""
        assert stderr == ""
