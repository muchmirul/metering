from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "fixture_evolution" / "main.py"


def run(active):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--active", active],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_fixture_example_promotes_a_better_challenger():
    result = run("v3")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["selected_id"] == report["challenger"]["id"]
    assert report["next_parent"] == report["challenger"]
    assert report["evidence"]["mean_improvement_bits"] == pytest.approx(
        0.3219280948873625
    )
    assert [case["result_entropy_bits"] for case in report["evidence"]["cases"]] == [
        1.0,
        1.0,
    ]


def test_fixture_example_retains_parent_when_the_same_mutation_regresses():
    result = run("v4")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["selected_id"] == report["parent"]["id"]
    assert report["next_parent"] == report["parent"]
    assert report["evidence"]["mean_improvement_bits"] < 0
