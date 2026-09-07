"""Deployed Pi candidate browsing and report rendering, without model calls."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_agentvolve_candidate_view import fixture_run
from test_agentvolve_goal import RPC

from apps.coding_agent.candidate_view import report_view

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / ".pi/extensions/population-evolution.ts"


@pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")
def test_deployed_history_opens_every_child_and_loop_report(tmp_path: Path):
    runs = tmp_path / "runs"
    root, _ids = fixture_run(runs)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report_view(runs, root.name, "H1")))
    inspector = tmp_path / "report-inspector.ts"
    browser = ROOT / "connectors/fixed/pi/agentvolve_candidate_browser.ts"
    support = ROOT / "connectors/fixed/pi/population_evolution_support.ts"
    inspector.write_text(f'''import {{readFileSync}} from "node:fs";
import {{visibleWidth}} from "@earendil-works/pi-tui";
import {{candidateLabel, showCandidateReport}} from {json.dumps(str(browser))};
import {{decodeCandidateReport}} from {json.dumps(str(support))};
export default function(pi: any) {{
 pi.registerCommand("inspect-candidate-report", {{description:"Render a historical child report", handler:async (_args: string, ctx: any) => {{
  const report = decodeCandidateReport(JSON.parse(readFileSync({json.dumps(str(report_path))}, "utf8")));
  const deepLabel = candidateLabel({{...report.node, label:"H256", tree_prefix:"│  ".repeat(255)+"└─ "}});
  if(deepLabel.indexOf("H256")>9) throw new Error("deep tree hid the node ID");
  const lines: string[] = [];
  let action;
  await showCandidateReport({{...ctx, mode:"tui", ui:{{...ctx.ui, custom:async (factory: any) => {{
   const view = factory({{requestRender() {{}}, terminal:{{rows:40}}}}, ctx.ui.theme, {{}}, (value: any) => {{action=value;}});
   for (const width of [1, 20, 80, 160]) {{
    view.handleInput("\\x1b[H");
    for (let page=0; page<120; page++) {{
     const rendered=view.render(width);
     if(rendered.some((line: string) => visibleWidth(line)>width)) throw new Error("report overflow");
     lines.push(...rendered); view.handleInput("\\x1b[6~");
    }}
   }}
   view.handleInput("]");
  }}}}}}, report);
  pi.appendEntry("candidate-render-test", {{lines, action}});
 }}}});
}}
''')
    process = subprocess.Popen(["pi", "--mode", "rpc", "--no-session", "--no-extensions",
        "-e", str(EXTENSION), "-e", str(inspector)], cwd=tmp_path,
        env={**os.environ, "METERING_EVOLUTION_RUNS_DIR": str(runs)},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        rpc = RPC(process)
        stage = 0

        def choose(event: dict) -> dict:
            nonlocal stage
            title, options = event["title"], event["options"]
            if title == "Evolution trace":
                if stage == 0:
                    stage = 1
                    return {"value": "Candidate trees / child reports"}
                return {"value": "Return"}
            if title.startswith("Agentvolve candidate trees"):
                if stage == 1:
                    assert "├─ H1 [eliminated]" in "\n".join(options)
                    stage = 2
                    return {"value": next(option for option in options if "H1 [" in option)}
                stage = 3
                return {"value": "Show loops / attempts"}
            if title == "H1 report":
                if "Next loop steps" in options:
                    return {"value": "Next loop steps"}
                if "Next diff page" in options:
                    return {"value": "Next diff page"}
                return {"value": "Back to tree / loops"}
            if title.startswith("Agentvolve loops / attempts"):
                if stage == 3:
                    stage = 4
                    return {"value": next(option for option in options if "HR2 [" in option)}
                return {"value": "Back to progress"}
            assert title == "HR2 report", event
            return {"value": "Next loop steps" if "Next loop steps" in options else "Back to tree / loops"}

        events = rpc.prompt(f"/history {root.name}", choose)
        assert not any(event.get("notifyType") == "error" for event in events), events
        inspections = [entry["data"] for entry in rpc.entries() if entry.get("customType") == "agentvolve-candidate-inspection"]
        reports = [view for view in inspections if view["view_schema"] == "agentvolve-candidate-report-v1"]
        child = [report for report in reports if report["node"]["label"] == "H1"]
        assert child and all(report["evidence"]["final"] is None for report in child)
        assert max(report["offset"] for report in child) >= 10
        assert max(report["diff"]["offset"] for report in child) > 40
        assert any(report["mode"] == "loop" and report["node"]["label"] == "HR2" for report in reports)
        events = rpc.prompt("/inspect-candidate-report")
        rendered = [entry["data"] for entry in rpc.entries() if entry.get("customType") == "candidate-render-test"]
        assert rendered, events
        assert rendered[-1]["action"] == "diff-next"
        assert "EVALUATION SUMMARY" in "\n".join(rendered[-1]["lines"])
    finally:
        process.terminate()
        process.wait(timeout=10)
        assert process.stderr is not None
        assert process.stderr.read() == b""
