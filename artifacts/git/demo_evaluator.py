"""Deterministic trusted evaluator for the Git artifact end-to-end example."""

from __future__ import annotations

import json
import sys


def canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def main() -> int:
    request = json.load(sys.stdin)
    if request.get("protocol_version") != 1:
        raise SystemExit("unsupported evaluator protocol")
    results = []
    for item in request["submissions"]:
        submission = item["submission"]
        shape_valid = (
            type(submission) is dict
            and set(submission) == {"answer", "commit", "verified_outputs"}
            and type(submission.get("answer")) is str
            and type(submission.get("commit")) is str
            and type(submission.get("verified_outputs")) is list
        )
        outputs = submission.get("verified_outputs", []) if shape_valid else []
        model_output = any(
            type(output) is dict
            and output.get("kind") == "model_checkpoint"
            and output.get("name") == "demo-trained-model"
            for output in outputs
        )
        passed = shape_valid and submission["answer"] == "ADAPTED" and model_output
        results.append(
            {
                "candidate_id": item["candidate_id"],
                "evidence": {
                    "adapter_answer_adapted": shape_valid
                    and submission["answer"] == "ADAPTED",
                    "model_checkpoint_verified": model_output,
                    "submission_shape_valid": shape_valid,
                },
                "outcome": "pass" if passed else "fail",
                "passed": passed,
                "safety_passed": shape_valid,
            }
        )
    print(canonical_json({"results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
