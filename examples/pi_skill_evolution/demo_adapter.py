"""Deterministic test double for the Pi skill-evolution adapter protocol."""

from __future__ import annotations

import hashlib
import json
import sys


def canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def skill_id(text: str) -> str:
    payload = canonical_json({"schema": "pi-skill-v1", "text": text})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    request = json.load(sys.stdin)
    action = request.get("action")
    if action == "propose":
        parent = request["candidate"]
        text = parent["text"].rstrip() + "\n\nRun relevant tests before claiming completion.\n"
        response = {"candidate": {"id": skill_id(text), "text": text}}
    elif action == "judge":
        parent = request["parent"]
        challenger = request["challenger"]
        requirement = "Run relevant tests before claiming completion."
        parent_passed = requirement in parent["text"]
        challenger_passed = requirement in challenger["text"]
        selected_id = (
            challenger["id"]
            if challenger_passed and not parent_passed
            else parent["id"]
        )
        response = {
            "selected_id": selected_id,
            "evidence": {
                "checks": [
                    {
                        "name": "requires-test-verification",
                        "parent_passed": parent_passed,
                        "challenger_passed": challenger_passed,
                    }
                ]
            },
        }
    else:
        raise SystemExit("unknown action")
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
