#!/usr/bin/env python3
"""Independent addition evaluator for the reference harness assays."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json, decode_json_object  # noqa: E402


class EvaluatorError(RuntimeError):
    pass


def evaluate(request: dict[str, object]) -> dict[str, object]:
    if set(request) != {"case", "evaluation", "protocol_version", "submissions"}:
        raise EvaluatorError("evaluator request has the wrong keys")
    if request["protocol_version"] != 1:
        raise EvaluatorError("evaluator protocol_version must be 1")
    case = request["case"]
    if type(case) is not dict or type(case.get("input")) is not dict:
        raise EvaluatorError("evaluator case is malformed")
    task_input = case["input"]
    assert type(task_input) is dict
    prompt = task_input.get("prompt")
    if type(prompt) is not str:
        raise EvaluatorError("evaluator prompt is malformed")
    left = re.search(r"left=(-?\d+)", prompt)
    right = re.search(r"right=(-?\d+)", prompt)
    if left is None or right is None:
        raise EvaluatorError("evaluator prompt omitted operands")
    expected = int(left.group(1)) + int(right.group(1))
    submissions = request["submissions"]
    if type(submissions) is not list or not submissions:
        raise EvaluatorError("evaluator submissions must be non-empty")
    results: list[dict[str, object]] = []
    for item in submissions:
        if type(item) is not dict or set(item) != {"candidate_id", "submission"}:
            raise EvaluatorError("evaluator submission item is malformed")
        submission = item["submission"]
        if type(submission) is not dict:
            raise EvaluatorError("candidate submission must be a JSON object")
        answer = submission.get("answer")
        passed = type(answer) is int and answer == expected
        results.append(
            {
                "candidate_id": item["candidate_id"],
                "evidence": {"answer": answer, "expected": expected},
                "outcome": "pass" if passed else "fail",
                "passed": passed,
                "safety_passed": True,
            }
        )
    return {"results": results}


def main() -> int:
    try:
        request = decode_json_object(sys.stdin.read(), EvaluatorError)
        response = evaluate(request)
    except (EvaluatorError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
