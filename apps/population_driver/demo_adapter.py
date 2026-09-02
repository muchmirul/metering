#!/usr/bin/env python3
"""Deterministic non-executing adapters for the Population Driver protocol demo."""

from __future__ import annotations

import json
import sys

RESOURCE_NAMES = (
    "actions",
    "energy_millijoules",
    "gpu_milliseconds",
    "memory_bytes",
    "storage_bytes",
    "tokens",
    "wall_milliseconds",
)


def _write(value: object) -> None:
    print(json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True))


def _proposal(request: dict[str, object]) -> dict[str, object]:
    context = request["context"]
    parent = request["parent"]
    if type(context) is not dict or type(parent) is not dict:
        raise ValueError("proposal request is malformed")
    generation = context["generation"]
    artifact = parent["artifact"]
    if type(generation) is not int or type(artifact) is not dict:
        raise ValueError("proposal context or parent is malformed")
    child = dict(artifact)
    child["commit"] = format(generation, "040x")
    child["content_sha256"] = format(generation + 200, "064x")
    child["git_tree"] = format(generation + 100, "040x")
    return {
        "challenger_artifact": child,
        "reason": f"deterministic protocol-demo mutation {generation}",
    }


def _runner(request: dict[str, object]) -> dict[str, object]:
    candidate = request["candidate"]
    if type(candidate) is not dict or type(candidate.get("artifact")) is not dict:
        raise ValueError("runner candidate is malformed")
    artifact = candidate["artifact"]
    assert type(artifact) is dict
    adapted = int(str(artifact["commit"]), 16) > 0
    pass_probability = 0.9 if adapted else 0.1
    return {
        "forecast": {
            "outcomes": [
                {"outcome": "fail", "probability": 1.0 - pass_probability},
                {"outcome": "pass", "probability": pass_probability},
            ]
        },
        "submission": {"adapted": adapted},
    }


def _evaluator(request: dict[str, object]) -> dict[str, object]:
    submissions = request["submissions"]
    if type(submissions) is not list:
        raise ValueError("evaluator submissions are malformed")
    results = []
    for item in submissions:
        if type(item) is not dict or type(item.get("submission")) is not dict:
            raise ValueError("evaluator submission is malformed")
        submission = item["submission"]
        assert type(submission) is dict
        passed = submission.get("adapted") is True
        results.append(
            {
                "candidate_id": item["candidate_id"],
                "evidence": {"adapted": passed},
                "outcome": "pass" if passed else "fail",
                "passed": passed,
                "safety_passed": True,
            }
        )
    return {"results": results}


def _evidence(request: dict[str, object]) -> dict[str, object]:
    controller_result = request["controller_result"]
    if type(controller_result) is not dict:
        raise ValueError("evidence request is malformed")
    candidates = []
    for report_name in ("incumbent_report", "challenger_report"):
        report = controller_result[report_name]
        if type(report) is not dict or type(report.get("task_summary")) is not dict:
            raise ValueError("Controller report is malformed")
        summary = report["task_summary"]
        assert type(summary) is dict
        passed = int(summary["passed_count"])
        case_count = int(summary["case_count"])
        pass_rate = passed / case_count
        candidates.append(
            {
                "behavior_distribution": [1.0 - pass_rate, pass_rate],
                "candidate_id": report["candidate"],
                "cost": {name: 1 for name in RESOURCE_NAMES},
                "protected_passed": True,
                "seed": {"round": request["round"]},
            }
        )
    return {"candidates": candidates, "protocol_version": 1}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {
        "evaluator",
        "evidence",
        "proposal",
        "runner",
    }:
        print(
            "usage: demo_adapter.py {proposal|runner|evaluator|evidence}",
            file=sys.stderr,
        )
        return 2
    try:
        request = json.load(sys.stdin)
        if type(request) is not dict:
            raise ValueError("request must be a JSON object")
        action = sys.argv[1]
        result = {
            "evaluator": _evaluator,
            "evidence": _evidence,
            "proposal": _proposal,
            "runner": _runner,
        }[action](request)
    except (KeyError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    _write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
