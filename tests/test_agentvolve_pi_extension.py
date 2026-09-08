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
    *,
    input_stream: TextIO | None = None,
) -> dict[str, object]:
    for line in stream:
        event = json.loads(line)
        if events is not None:
            events.append(event)
        if input_stream is not None:
            cancel_dialog(input_stream, event)
        if event.get("type") == "response" and event.get("id") == request_id:
            return event
    raise AssertionError(f"Pi RPC ended before response {request_id}")


def cancel_dialog(stream: TextIO, event: dict[str, object]) -> None:
    if event.get("type") == "extension_ui_request" and event.get("method") in {"input", "select", "confirm", "editor"}:
        send(stream, {"type": "extension_ui_response", "id": event["id"], "cancelled": True})


def emitted_event(stream: TextIO, event_type: str, input_stream: TextIO | None = None) -> dict[str, object]:
    for line in stream:
        event = json.loads(line)
        if input_stream is not None:
            cancel_dialog(input_stream, event)
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
            "--no-extensions",
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
        assert {"goal", "limit", "history", "progress"} <= names
        assert not any(name.startswith(("evolve", "agentvolve", "view-")) for name in names)
        extension_commands = {command["name"] for command in commands["data"]["commands"] if command.get("sourceInfo", {}).get("path") == str(EXTENSION)}  # type: ignore[index]
        assert extension_commands == {"goal", "limit", "history", "progress"}
        monitor_events: list[dict[str, object]] = []

        send(
            process.stdin,
            {"id": "goal", "type": "prompt", "message": "/goal solve the task"},
        )
        assert response(process.stdout, "goal", monitor_events, input_stream=process.stdin)["success"] is True
        assert any(event.get("method") == "input" for event in monitor_events)
        assert not list(runs.glob("workflow-*"))
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
            "workflow_manage",
        ):
            assert action in encoded_tool
        assert set(tool_metadata["parameters"]["properties"]) == {"action"}
        assert tool_metadata["parameters"]["additionalProperties"] is False
        assert "action schema accepts no" in encoded_tool
        assert "harness_run" not in encoded_tool
        assert "solution_run" not in encoded_tool
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
    const drafting = context.systemPrompt?.startsWith(\"You create an Agentvolve task draft\");
    if (!drafting && last?.role === \"user\") {
      const request = JSON.stringify(last);
      const action = request.includes(\"history\") ? \"workflow_history\"
        : request.includes(\"progress\") ? \"workflow_status\"
        : request.includes(\"start\") ? \"workflow_start\"
        : request.includes(\"session goal\") ? \"workflow_from_session\"
        : \"workflow_activate\";
      const call = { type: \"toolCall\", id: `${action}-1`, name: \"darwinian_coding\",
        arguments: { action } };
      message.content.push(call);
      stream.push({ type: \"toolcall_start\", contentIndex: 0, partial: message });
      stream.push({ type: \"toolcall_end\", contentIndex: 0, toolCall: call, partial: message });
      message.stopReason = \"toolUse\";
    } else {
      const block = { type: \"text\", text: drafting
        ? JSON.stringify({clarification: \"What independently checkable behavior should this task provide?\"})
        : \"Agentvolve is active.\" };
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
            "--no-extensions",
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

        send(process.stdin, {"id": "limit", "type": "prompt", "message": "/limit 2"})
        assert response(process.stdout, "limit")["success"] is True

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
            (
                "session-goal",
                "solve the session goal with Agentvolve",
                "workflow_from_session",
                "status",
                "needs-task-clarification",
            ),
        ):
            send(
                process.stdin,
                {"id": request_id, "type": "prompt", "message": request_text},
            )
            assert response(process.stdout, request_id)["success"] is True
            completed = emitted_event(process.stdout, "agent_end", process.stdin)
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
            if action in {"workflow_start", "workflow_from_session"}:
                assert "What independently checkable behavior" in latest_result["content"][0]["text"]
                assert not (tasks / "workspaces").exists()

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


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
def test_history_pages_runs_and_traces_and_dashboard_renders(tmp_path: Path):
    from test_agentvolve_goal import RPC
    from test_agentvolve_operator import write_projection_ledger

    from apps.coding_agent.operator_view import progress_view, trace_view

    runs = tmp_path / "runs"
    runs.mkdir()
    for index in range(55):
        (runs / f"solution-pi-20260906T1900{index:02}000Z").mkdir()
    selected = runs / "solution-pi-20260906T190004000Z"
    write_projection_ledger(selected, 45)
    fixture = tmp_path / "view.json"
    fixture.write_text(json.dumps({"progress": progress_view(runs, selected.name, include_diff=False),
        "pages": [trace_view(runs, selected.name, offset) for offset in (0, 20, 40)]}))
    inspector = tmp_path / "dashboard-inspector.ts"
    dashboard = ROOT / "connectors/fixed/pi/agentvolve_dashboard.ts"
    inspector.write_text(f'''import {{ readFileSync }} from "node:fs";
import {{ visibleWidth }} from "@earendil-works/pi-tui";
import {{ showAgentvolveDashboard }} from {json.dumps(str(dashboard))};
export default function(pi: any) {{
  pi.registerCommand("inspect-dashboard", {{ description:"Test dashboard rendering", handler: async (_args: string, ctx: any) => {{
    const fixture = JSON.parse(readFileSync({json.dumps(str(fixture))}, "utf8"));
    const rendered: string[] = [];
    const offsets: number[] = [];
    await showAgentvolveDashboard({{...ctx, mode:"tui", ui:{{...ctx.ui, custom:async (factory: any) => {{
      const view = factory({{requestRender() {{}}, terminal:{{rows:40}}}}, ctx.ui.theme, {{}}, () => {{}});
      try {{
        for (const width of [20, 80, 160]) {{
          for (let page = 0; page < 15; page++) {{
            const lines = view.render(width);
            if (lines.some((line: string) => visibleWidth(line) > width)) throw new Error("dashboard overflow");
            rendered.push(...lines);
            view.handleInput("\\x1b[6~");
          }}
        }}
        view.handleInput("]");
        await new Promise(resolve => setTimeout(resolve, 25));
        rendered.push(...view.render(160));
      }} finally {{ view.dispose(); }}
    }}}}}}, "fixture operator", fixture.progress, async () => fixture.progress, fixture.pages[0],
      async (offset: number) => {{offsets.push(offset); return fixture.pages[offset / 20];}});
    pi.appendEntry("dashboard-render-test", {{rendered, offsets}});
  }}}});
}}
''')
    process = subprocess.Popen(["pi", "--mode", "rpc", "--no-session", "--no-extensions",
        "-e", str(EXTENSION), "-e", str(inspector)], cwd=tmp_path,
        env={**os.environ, "METERING_EVOLUTION_RUNS_DIR": str(runs)},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        rpc = RPC(process)
        history_visits = 0

        def choose(event: dict) -> dict:
            nonlocal history_visits
            if event["title"].startswith("Agentvolve history"):
                history_visits += 1
                if history_visits == 1:
                    assert "of 55" in event["title"]
                    return {"value": "Older runs"}
                if history_visits == 2:
                    assert "51–55" in event["title"]
                    return {"value": event["options"][0]}
                return {"cancelled": True}
            assert event["title"] == "Evolution trace"
            return {"value": "Next generations" if "Next generations" in event["options"] else "Return"}

        rpc.prompt("/history", choose)
        entries = rpc.entries()
        pages = [entry["data"] for entry in entries if entry.get("customType") == "agentvolve-trace-view"]
        assert [page["offset"] for page in pages] == [0, 20, 40]
        assert [row["round"] for page in pages for row in page["rounds"]] == list(range(1, 46))
        rpc.prompt("/progress")
        progress = [entry["data"]["progress"] for entry in rpc.entries() if entry.get("customType") == "agentvolve-progress-view"][-1]
        assert progress["workflow_root"].endswith("190054000Z")
        events = rpc.prompt("/inspect-dashboard")
        rendered = [entry["data"] for entry in rpc.entries() if entry.get("customType") == "dashboard-render-test"]
        assert rendered, events
        assert rendered[-1]["offsets"] == [20]
        assert "parent-20" in "\n".join(rendered[-1]["rendered"])
    finally:
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr is not None
        assert process.stderr.read() == b""
