"""Deterministic stand-in for an external model-training artifact worker."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from demo_validate import read_answer


def canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def main() -> int:
    request = json.load(sys.stdin)
    if request.get("protocol_version") != 1:
        raise SystemExit("unsupported build protocol")
    answer = read_answer()
    content = f"demo-trained-model:{answer}\n".encode()
    digest = hashlib.sha256(content).hexdigest()
    store_value = os.environ.get("METERING_DEMO_ARTIFACT_STORE")
    if not store_value:
        raise SystemExit("METERING_DEMO_ARTIFACT_STORE is required")
    store = Path(store_value)
    store.mkdir(parents=True, exist_ok=True)
    checkpoint = store / f"{digest}.bin"
    checkpoint.write_bytes(content)
    response = {
        "outputs": [
            {
                "kind": "model_checkpoint",
                "name": "demo-trained-model",
                "sha256": digest,
                "uri": checkpoint.resolve().as_uri(),
            }
        ]
    }
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
