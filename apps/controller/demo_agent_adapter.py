"""Deterministic candidate adapter for the agent-skill generation example."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def main() -> int:
    request = json.load(sys.stdin)
    if request.get("protocol_version") != 1:
        raise SystemExit("unsupported adapter protocol")
    candidate = request["candidate"]
    task = request["task"]
    skill_path = candidate["skill_path"]
    skill_text = (
        ""
        if skill_path is None
        else (Path(skill_path) / "SKILL.md").read_text(encoding="utf-8")
    )
    required_text = task["input"]["required_text"]
    predicted_pass = required_text in skill_text
    pass_probability = 0.8 if predicted_pass else 0.4
    response = {
        "forecast": {
            "outcomes": [
                {"outcome": "fail", "probability": 1.0 - pass_probability},
                {"outcome": "pass", "probability": pass_probability},
            ]
        },
        "submission": {"skill_text": skill_text},
    }
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
