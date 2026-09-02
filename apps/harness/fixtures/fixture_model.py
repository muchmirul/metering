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


CODING_FIXTURES = {
    "chunks": (
        "sequence.py",
        "def chunks(values, size):\n"
        "    if size <= 0:\n"
        "        raise ValueError('size must be positive')\n"
        "    return [values[index:index + size] for index in range(0, len(values), size)]\n",
    ),
    "merge-mappings": (
        "mapping.py",
        "def merged(defaults, overrides):\n"
        "    result = dict(defaults)\n"
        "    result.update(overrides)\n"
        "    return result\n",
    ),
    "parse-bool": (
        "config.py",
        "def parse_bool(value):\n"
        "    normalized = value.strip().casefold()\n"
        "    if normalized in {'1', 'true', 'yes', 'on'}:\n"
        "        return True\n"
        "    if normalized in {'0', 'false', 'no', 'off'}:\n"
        "        return False\n"
        "    raise ValueError('invalid boolean')\n",
    ),
    "username": (
        "textutil.py",
        "def normalize_username(value):\n"
        "    words = value.split()\n"
        "    if not words:\n"
        "        raise ValueError('username is empty')\n"
        "    return '-'.join(word.casefold() for word in words)\n",
    ),
    "dedupe": (
        "dedupe.py",
        "def dedupe(values):\n"
        "    result = []\n"
        "    for value in values:\n"
        "        if value not in result:\n"
        "            result.append(value)\n"
        "    return result\n",
    ),
    "parse-fields": (
        "fields.py",
        "def parse_fields(text):\n"
        "    result = {}\n"
        "    for field in text.split(','):\n"
        "        if '=' not in field:\n"
        "            raise ValueError('missing equals')\n"
        "        key, value = field.split('=', 1)\n"
        "        key = key.strip()\n"
        "        if not key:\n"
        "            raise ValueError('empty key')\n"
        "        result[key] = value.strip()\n"
        "    return result\n",
    ),
    "slug": (
        "slug.py",
        "def slugify(value):\n"
        "    words = value.split()\n"
        "    if not words:\n"
        "        raise ValueError('slug is empty')\n"
        "    return '-'.join(word.casefold() for word in words)\n",
    ),
}


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


def _coding_action(
    events: list[dict[str, object]], policy: str
) -> dict[str, object] | None:
    task = _initial_task(events)
    if type(task) is not dict or type(task.get("workspace")) is not dict:
        return None
    outcomes = task.get("outcomes")
    if type(outcomes) is not list or any(type(item) is not str for item in outcomes):
        raise FixtureModelError("fixture coding outcomes are malformed")
    kernel = next(
        (event for event in reversed(events) if event.get("event") == "kernel"), None
    )
    if kernel is None:
        operator = {"ADD": "+", "MULTIPLY": "*", "SUBTRACT": "-"}[policy]
        task_prompt = str(task.get("prompt", ""))
        fixture = re.search(r"CODING_FIXTURE=([a-z-]+)", task_prompt)
        if fixture is not None:
            name = fixture.group(1)
            try:
                path, correct = CODING_FIXTURES[name]
            except KeyError as exc:
                raise FixtureModelError("unknown coding fixture") from exc
            existing = (
                f"# deterministic rejected mutation\nFIXTURE_POLICY = {policy!r}\n"
                if policy != "ADD"
                else correct
            )
            return {
                "action": "execute",
                "code": f"write_file({path!r}, {existing!r})",
            }
        generation = re.search(r'"generation":(\d+)', task_prompt)
        prefix = (
            f"# evolved generation {generation.group(1)}\n"
            if generation is not None
            else ""
        )
        content = (
            prefix
            + "def solve(left: int, right: int) -> int:\n"
            + f"    return left {operator} right\n"
        )
        return {
            "action": "execute",
            "code": f"write_file('solver.py', {content!r})",
        }
    pass_probability = 0.9 if policy == "ADD" else 0.1
    probabilities = {"fail": 1.0 - pass_probability, "pass": pass_probability}
    return {
        "action": "finish",
        "forecast": {
            "outcomes": [
                {"outcome": outcome, "probability": probabilities[str(outcome)]}
                for outcome in outcomes
            ]
        },
        "submission": {"summary": f"fixture {policy.lower()} coding attempt"},
    }


def respond(request: dict[str, object]) -> dict[str, object]:
    normalized = decode_model_request(request)
    system = str(normalized["system_prompt"])
    match = re.search(r"ARITHMETIC_POLICY=(SUBTRACT|ADD|MULTIPLY)", system)
    if match is None:
        raise FixtureModelError("fixture candidate omitted arithmetic policy")
    policy = match.group(1)
    events = _transcript(str(normalized["prompt"]))
    coding_action = _coding_action(events, policy)
    if coding_action is not None:
        prompt = str(normalized["prompt"])
        return {
            "action": coding_action,
            "protocol_version": 1,
            "usage": {
                "input_tokens": max(1, len(prompt) // 4),
                "output_tokens": max(1, len(canonical_json(coding_action)) // 4),
            },
        }
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
