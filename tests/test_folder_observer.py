from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OBSERVER = ROOT / "apps" / "folder_observer" / "observer.py"


def run_observer(active: str, history: Path | None = None):
    arguments = [sys.executable, str(OBSERVER), "--active", active]
    if history is not None:
        arguments.extend(["--history", str(history)])
    return subprocess.run(
        arguments,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_events(output: str) -> list[dict[str, object]]:
    lines = output.splitlines()
    events = [json.loads(line) for line in lines]
    assert lines == [
        json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        for event in events
    ]
    return events


@pytest.mark.parametrize("active", ["v1", "v2", "v3", "v4"])
def test_observer_identifies_every_fixture_version(active):
    result = run_observer(active)

    assert result.returncode == 0
    assert result.stderr == ""
    events = parse_events(result.stdout)
    assert [event["event"] for event in events] == [
        "start",
        "observation",
        "observation",
        "identified",
    ]
    assert events[-1]["snapshot"]["name"] == active
    assert events[-1]["steps"] == 2


def test_observer_exposes_version_lineage_and_exact_probability_models():
    result = run_observer("v3")

    assert result.returncode == 0
    events = parse_events(result.stdout)
    start, first, second, identified = events

    assert start["model"] == {
        "candidate_prior": "uniform",
        "probability_rule": "matching_versions / remaining_versions",
    }
    assert start["versions"] == [
        {
            "name": "v1",
            "parent": None,
            "parent_snapshot_id": None,
            "snapshot_id": (
                "6298657f9ed2c242c2aa39a38b098637"
                "1a23b7b5f1bd2f8140a704c21a3b725e"
            ),
            "tree_id": (
                "684c0aefd41e7f63afa3bceff628715f"
                "cf0988c84fdcca07f8616996c3d6ca02"
            ),
        },
        {
            "name": "v2",
            "parent": "v1",
            "parent_snapshot_id": (
                "6298657f9ed2c242c2aa39a38b098637"
                "1a23b7b5f1bd2f8140a704c21a3b725e"
            ),
            "snapshot_id": (
                "7c2f20edfd1fdcecd636df32a5ccc3ea"
                "d815407853505e528f7c2b146805668c"
            ),
            "tree_id": (
                "9d49cb4ff3f320821f983c05643e5ce7"
                "0046e0e0ce9c7fbe4c86cb2509d90e94"
            ),
        },
        {
            "name": "v3",
            "parent": "v2",
            "parent_snapshot_id": (
                "7c2f20edfd1fdcecd636df32a5ccc3ea"
                "d815407853505e528f7c2b146805668c"
            ),
            "snapshot_id": (
                "244c1de679962b61c1e69e03bc1c9b32"
                "84b088b2883a50f9f88a70eb6ae15fcc"
            ),
            "tree_id": (
                "26f0299f8954c040c179bf9f70a63e0"
                "1c30a98a71c49f7f3851300e248ee8604"
            ),
        },
        {
            "name": "v4",
            "parent": "v3",
            "parent_snapshot_id": (
                "244c1de679962b61c1e69e03bc1c9b32"
                "84b088b2883a50f9f88a70eb6ae15fcc"
            ),
            "snapshot_id": (
                "c7f6da72aa99e45f3f6ba3a48af86e"
                "3d4a970ef61c76d590e01af65cf10aa8b7"
            ),
            "tree_id": (
                "37e494ec9dc3bc9e1ca0f5b76f720a0f"
                "eb8db092109ee414c909f4f2a85e8ef6"
            ),
        },
    ]

    assert first["candidates_before"] == ["v1", "v2", "v3", "v4"]
    assert first["selected_probe"] == {
        "operation": "read",
        "path": "config/mode.txt",
    }
    assert first["observed_result"] == {"kind": "text", "text": "fast\n"}
    assert first["observed_probability"] == 0.5
    assert first["candidates_after"] == ["v3", "v4"]
    assert first["candidate_entropy_before"] == {
        "request": {
            "measure": "entropy",
            "probabilities": [0.25, 0.25, 0.25, 0.25],
        },
        "response": {
            "base": 2.0,
            "infinite": False,
            "measure": "entropy",
            "value": 2.0,
        },
    }
    assert first["observed_surprisal"] == {
        "request": {"measure": "self_information", "probability": 0.5},
        "response": {
            "base": 2.0,
            "infinite": False,
            "measure": "self_information",
            "value": 1.0,
        },
    }

    assert second["candidates_before"] == ["v3", "v4"]
    assert second["selected_probe"] == {
        "operation": "read",
        "path": "service/port.txt",
    }
    assert second["observed_result"] == {"kind": "text", "text": "8000\n"}
    assert second["candidates_after"] == ["v3"]
    assert second["candidate_entropy_after"]["response"]["value"] == 0.0
    assert identified["snapshot"] == start["versions"][2]


def test_observer_rejects_an_unknown_fixture_version():
    result = run_observer("unknown")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid choice" in result.stderr


def test_observer_can_append_every_measurement_to_history(tmp_path):
    history = tmp_path / "history"

    result = run_observer("v3", history)

    assert result.returncode == 0
    events = parse_events(result.stdout)
    first_measurement = events[1]["candidate_entropy_before"]
    assert set(first_measurement["history"]) == {
        "pair_id",
        "parent_record_id",
        "record_id",
    }

    log_result = subprocess.run(
        [sys.executable, "-m", "metering.history", "log", str(history)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert log_result.returncode == 0
    assert log_result.stderr == ""
    log = json.loads(log_result.stdout)
    assert len(log["records"]) == 12
    assert log["records"][0]["record_id"] == log["head"]
