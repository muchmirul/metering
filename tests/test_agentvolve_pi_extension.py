"""Deployed read-only Pi history and terminal rendering; job lifecycle is tested separately."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_agentvolve_goal import EXTENSION, ROOT, RPC


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
def test_history_pages_runs_and_traces_and_dashboard_renders(tmp_path: Path):
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

        def choose(event):
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
        events = rpc.prompt("/progress")
        assert any("No job is bound" in event.get("message", "") for event in events)
        progress = [entry["data"]["progress"] for entry in rpc.entries() if entry.get("customType") == "agentvolve-progress-view"][-1]
        assert progress["workflow_root"] == str(selected), "History must not silently bind latest progress"
        events = rpc.prompt("/inspect-dashboard")
        rendered = [entry["data"] for entry in rpc.entries() if entry.get("customType") == "dashboard-render-test"]
        assert rendered, events
        assert rendered[-1]["offsets"] == [20]
        assert "parent-20" in "\n".join(rendered[-1]["rendered"])
    finally:
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr.read() == b""
