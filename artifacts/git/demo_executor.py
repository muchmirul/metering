"""Non-executing environment harness for the Git artifact integration test."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from demo_validate import read_answer


def canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def main() -> int:
    request = json.load(sys.stdin)
    if set(request) != {"candidate", "protocol_version", "task"}:
        raise SystemExit("executor request has the wrong keys")
    if request["protocol_version"] != 1:
        raise SystemExit("unsupported executor protocol")
    candidate = request["candidate"]
    artifact = candidate["artifact"]
    checkout = Path(candidate["checkout_path"])
    entrypoint = checkout / artifact["entrypoint"]
    answer = read_answer(entrypoint)

    verified_outputs = []
    for output in artifact["outputs"]:
        uri = output["uri"]
        if not uri.startswith("file://"):
            raise SystemExit("demo executor accepts only file output URIs")
        path = Path(uri.removeprefix("file://"))
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != output["sha256"]:
            raise SystemExit("external output digest does not match")
        verified_outputs.append(output)

    pass_probability = 0.9 if answer == "ADAPTED" else 0.1
    response = {
        "forecast": {
            "outcomes": [
                {"outcome": "fail", "probability": 1.0 - pass_probability},
                {"outcome": "pass", "probability": pass_probability},
            ]
        },
        "submission": {
            "answer": answer,
            "commit": artifact["commit"],
            "verified_outputs": verified_outputs,
        },
    }
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
