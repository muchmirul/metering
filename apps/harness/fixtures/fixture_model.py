#!/usr/bin/env python3
"""Deterministic fake model over the real recursive harness/kernel contract."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json, decode_json_object  # noqa: E402
from apps.harness.model_contract import (  # noqa: E402
    ModelContractError,
    decode_model_request,
)


class FixtureModelError(RuntimeError):
    pass


def _transcript(prompt: str) -> list[dict[str, object]]:
    marker = "TRANSCRIPT_JSON="
    position = prompt.rfind(marker)
    if position < 0:
        raise FixtureModelError("fixture model prompt omitted transcript")
    try:
        value = json.loads(prompt[position + len(marker) :])
    except json.JSONDecodeError as exc:
        raise FixtureModelError("fixture model transcript is invalid") from exc
    if type(value) is not list or any(type(item) is not dict for item in value):
        raise FixtureModelError("fixture model transcript is malformed")
    return value


def _initial_task(events: list[dict[str, object]]) -> object:
    initial = next((event for event in events if event.get("event") == "task"), None)
    if initial is None:
        raise FixtureModelError("fixture model task event is absent")
    return initial.get("task")


def _task(events: list[dict[str, object]]) -> tuple[int, int, list[str]]:
    task = _initial_task(events)
    if type(task) is not dict:
        raise FixtureModelError("fixture arithmetic task is malformed")
    prompt = task.get("prompt")
    outcomes = task.get("outcomes")
    if type(prompt) is not str or type(outcomes) is not list:
        raise FixtureModelError(
            "fixture model only supports top-level arithmetic tasks"
        )
    left = re.search(r"left=(-?\d+)", prompt)
    right = re.search(r"right=(-?\d+)", prompt)
    if left is None or right is None:
        raise FixtureModelError("fixture arithmetic task omitted left/right operands")
    if any(type(item) is not str for item in outcomes):
        raise FixtureModelError("fixture outcomes are malformed")
    return int(left.group(1)), int(right.group(1)), outcomes


def respond(request: dict[str, object]) -> dict[str, object]:
    normalized = decode_model_request(request)
    system = str(normalized["system_prompt"])
    match = re.search(r"ARITHMETIC_POLICY=(SUBTRACT|ADD|MULTIPLY)", system)
    if match is None:
        raise FixtureModelError("fixture candidate omitted arithmetic policy")
    policy = match.group(1)
    events = _transcript(str(normalized["prompt"]))
    initial_task = _initial_task(events)
    if type(initial_task) is str:
        action: dict[str, object] = {
            "action": "finish",
            "result": "bounded delegated arithmetic advice",
        }
        prompt = str(normalized["prompt"])
        return {
            "action": action,
            "protocol_version": 1,
            "usage": {
                "input_tokens": max(1, len(prompt) // 4),
                "output_tokens": max(1, len(canonical_json(action)) // 4),
            },
        }
    left, right, outcomes = _task(events)
    if (
        type(initial_task) is dict
        and "USE_DELEGATE" in str(initial_task.get("prompt"))
        and not any(event.get("event") == "delegate_result" for event in events)
    ):
        action = {"action": "delegate", "task": "check the arithmetic strategy"}
    else:
        action = None
    kernel = next(
        (event for event in reversed(events) if event.get("event") == "kernel"), None
    )
    if action is not None:
        pass
    elif kernel is None:
        operator = {"ADD": "+", "MULTIPLY": "*", "SUBTRACT": "-"}[policy]
        action = {
            "action": "execute",
            "code": f"answer = {left} {operator} {right}\nanswer",
        }
    else:
        result = kernel.get("result_repr")
        try:
            answer = int(str(result))
        except ValueError as exc:
            raise FixtureModelError("fixture kernel did not return an integer") from exc
        pass_probability = 0.9 if policy == "ADD" else 0.1
        probabilities = {
            "fail": 1.0 - pass_probability,
            "pass": pass_probability,
        }
        action = {
            "action": "finish",
            "forecast": {
                "outcomes": [
                    {"outcome": outcome, "probability": probabilities[outcome]}
                    for outcome in outcomes
                ]
            },
            "submission": {"answer": answer},
        }
    prompt = str(normalized["prompt"])
    return {
        "action": action,
        "protocol_version": 1,
        "usage": {
            "input_tokens": max(1, len(prompt) // 4),
            "output_tokens": max(1, len(canonical_json(action)) // 4),
        },
    }


def main() -> int:
    try:
        request = decode_json_object(sys.stdin.read(), FixtureModelError)
        response = respond(request)
    except (FixtureModelError, ModelContractError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
