"""Temporary, synthetic evidence with real Git files for browser acceptance only."""

from __future__ import annotations

import hashlib
import signal
import tempfile
from pathlib import Path

from test_agentvolve_trace_view import append_candidate, files_fixture
from test_agentvolve_candidate_view import save
from apps._support.wire import canonical_digest, canonical_json
from apps.coding_agent.trace_server import TraceServer, assets_ready


def main():
    assets_ready()
    with tempfile.TemporaryDirectory(prefix="agentvolve-trace-browser-") as temporary:
        root, ids, a, b = files_fixture(Path(temporary))

        def many_files(repository: Path):
            (repository / "bulk").mkdir()
            for index in range(105):
                (repository / "bulk" / f"{index:03d}.txt").write_text(
                    f"bulk file {index}"
                )

        c = append_candidate(root, b, many_files)
        attempt = "a" * 64
        pending = {
            "round": 4,
            "intent_id": "pending-fixture",
            "stage": "controller_pending",
            "parent_candidate_id": b,
            "attempts": [
                {
                    "attempt_id": attempt,
                    "retry": False,
                    "reason": "initial",
                    "wall_reservation_seconds": 60,
                }
            ],
        }
        save(
            root / "state/pending/round-intent.json",
            {**pending, "pending_id": canonical_digest(pending)},
        )
        diagnostic = {
            "diagnostic_schema": "population-driver-failure-v1",
            "authority": "diagnostic-only",
            "attempt_id": attempt,
            "intent_id": "pending-fixture",
            "error": {"summary": "fixture timeout"},
        }
        digest = hashlib.sha256(
            (canonical_json(diagnostic) + "\n").encode()
        ).hexdigest()
        save(root / f"state/diagnostics/{digest}.json", diagnostic)
        server = TraceServer(root.parent, root.name)
        signal.signal(
            signal.SIGTERM, lambda *_args: setattr(server, "started", float("-inf"))
        )
        print(
            canonical_json(
                {"url": server.url, "ids": {"seed": ids[0], "a": a, "b": b, "c": c}}
            ),
            flush=True,
        )
        server.run_until_idle()


if __name__ == "__main__":
    main()
