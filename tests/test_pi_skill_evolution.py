from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "pi_skill_evolution"
SCRIPT = EXAMPLE / "main.py"
ADAPTER = EXAMPLE / "demo_adapter.py"
SKILL = EXAMPLE / "SKILL.md"


def test_pi_skill_example_uses_the_same_evolution_step():
    adapter_command = f"{shlex.quote(sys.executable)} {shlex.quote(str(ADAPTER))}"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--skill",
            str(SKILL),
            "--adapter",
            adapter_command,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["selected_id"] == report["challenger"]["id"]
    assert report["next_parent"] == report["challenger"]
    assert "Run relevant tests" in report["next_parent"]["text"]
    assert report["evidence"] == {
        "checks": [
            {
                "name": "requires-test-verification",
                "parent_passed": False,
                "challenger_passed": True,
            }
        ]
    }
