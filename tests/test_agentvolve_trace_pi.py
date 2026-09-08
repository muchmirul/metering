"""Deployed Pi opens the actual trace service, without calling an inference model."""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from test_agentvolve_candidate_view import fixture_run
from test_agentvolve_goal import RPC

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / ".pi/extensions/population-evolution.ts"
ASSETS = ROOT / "apps/coding_agent/trace_ui/dist/app.js"


@pytest.mark.skipif(
    shutil.which("pi") is None or not ASSETS.is_file(),
    reason="Pi and built optional Trace Viewer assets are required",
)
def test_deployed_history_explicitly_launches_trace_viewer(tmp_path: Path):
    runs = tmp_path / "runs"
    root, ids = fixture_run(runs, "solution")
    process = subprocess.Popen(
        [
            "pi",
            "--mode",
            "rpc",
            "--no-session",
            "--no-extensions",
            "-e",
            str(EXTENSION),
        ],
        cwd=tmp_path,
        env={**os.environ, "METERING_EVOLUTION_RUNS_DIR": str(runs)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    viewer_pid = None
    try:
        rpc = RPC(process)
        selected = False

        def choose(event):
            nonlocal selected
            assert event["title"] == "Evolution trace"
            if not selected:
                selected = True
                return {"value": "Open Trace Viewer"}
            return {"value": "Return"}

        events = rpc.prompt(f"/history {root.name}", choose)
        assert not any(event.get("notifyType") == "error" for event in events), events
        message = next(
            event["message"]
            for event in events
            if event.get("message", "").startswith("Trace Viewer ready")
        )
        viewer_pid = int(re.search(r"Viewer PID: (\d+)", message)[1])
        url = re.search(r"http://127\.0\.0\.1:\d+/#token=[A-Za-z0-9_-]+", message)[0]
        parts = urlsplit(url)
        connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
        connection.request(
            "GET",
            "/api/graph",
            headers={"Authorization": "Bearer " + parse_qs(parts.fragment)["token"][0]},
        )
        response = connection.getresponse()
        assert response.status == 200
        graph = json.loads(response.read())
        assert graph["nodes"][1]["display_label"] == "S1a"
        assert graph["nodes"][1]["candidate_id"] == ids[1]
        assert graph["authority"] == "projection-only"
        connection.close()
        assert not any(url in json.dumps(entry) for entry in rpc.entries())
        assert not list(runs.glob("workflow-pi-*"))
    finally:
        if viewer_pid is not None:
            cmdline = Path(f"/proc/{viewer_pid}/cmdline")
            if (
                cmdline.exists()
                and b"apps.coding_agent.trace_server" in cmdline.read_bytes()
                and str(root.name).encode() in cmdline.read_bytes()
            ):
                os.kill(viewer_pid, signal.SIGTERM)
        process.terminate()
        process.wait(timeout=10)
