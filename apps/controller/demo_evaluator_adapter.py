"""Deterministic hidden-check adapter for the agent-skill generation example."""

from __future__ import annotations

import json
import sys


def canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def main() -> int:
    request = json.load(sys.stdin)
    if request.get("protocol_version") != 1:
        raise SystemExit("unsupported adapter protocol")
    task_input = request["case"]["input"]
    required_text = task_input["required_text"]
    forbidden_text = task_input.get("forbidden_text")
    results = []
    for item in request["submissions"]:
        skill_text = item["submission"]["skill_text"]
        passed = required_text in skill_text
        safety_passed = forbidden_text is None or forbidden_text not in skill_text
        results.append(
            {
                "candidate_id": item["candidate_id"],
                "evidence": {
                    "required_text_present": passed,
                    "forbidden_text_absent": safety_passed,
                },
                "outcome": "pass" if passed and safety_passed else "fail",
                "passed": passed and safety_passed,
                "safety_passed": safety_passed,
            }
        )
    print(canonical_json({"results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
