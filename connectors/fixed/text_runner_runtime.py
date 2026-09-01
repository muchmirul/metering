"""Shared strict protocol mechanics for concrete fixed text runners."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from apps.stdio_connector import canonical_json, decode_json_object

ROOT = Path(__file__).resolve().parents[2]

CommandBuilder = Callable[[str | None, str], list[str]]


class AdapterError(ValueError):
    """Raised when a runner request or agent response is invalid."""


def _require_exact_keys(
    value: dict[str, object], expected: set[str], location: str
) -> None:
    if set(value) != expected:
        raise AdapterError(f"{location} has the wrong keys")


def _decode_request(
    request: dict[str, object],
) -> tuple[str, str, list[str], str | None]:
    _require_exact_keys(request, {"candidate", "protocol_version", "task"}, "request")
    if type(request["protocol_version"]) is not int or request["protocol_version"] != 1:
        raise AdapterError("unsupported candidate adapter request")

    candidate = request["candidate"]
    if type(candidate) is not dict:
        raise AdapterError("candidate must be a JSON object")
    _require_exact_keys(candidate, {"candidate_id", "skill_path"}, "candidate")
    candidate_id = candidate["candidate_id"]
    if (
        type(candidate_id) is not str
        or len(candidate_id) != 64
        or any(character not in "0123456789abcdef" for character in candidate_id)
    ):
        raise AdapterError(
            "candidate.candidate_id must be a lowercase SHA-256 identifier"
        )
    skill_path = candidate["skill_path"]
    if skill_path is not None and type(skill_path) is not str:
        raise AdapterError("candidate.skill_path must be a string or null")

    task = request["task"]
    if type(task) is not dict:
        raise AdapterError("task must be a JSON object")
    _require_exact_keys(task, {"case_id", "input"}, "task")
    case_id = task["case_id"]
    if type(case_id) is not str or not case_id:
        raise AdapterError("task.case_id must be a non-empty string")
    task_input = task["input"]
    if type(task_input) is not dict:
        raise AdapterError("task.input must be a JSON object")
    _require_exact_keys(task_input, {"outcomes", "prompt"}, "task.input")
    prompt = task_input["prompt"]
    outcomes = task_input["outcomes"]
    if type(prompt) is not str or not prompt:
        raise AdapterError("task.input.prompt must be a non-empty string")
    if (
        type(outcomes) is not list
        or len(outcomes) < 2
        or any(type(item) is not str or not item for item in outcomes)
        or len(set(outcomes)) != len(outcomes)
    ):
        raise AdapterError("task.input.outcomes must contain unique non-empty strings")
    return case_id, prompt, outcomes, skill_path


def model_prompt(case_id: str, prompt: str, outcomes: list[str]) -> str:
    """Build the exact agent-neutral task and forecast instruction."""

    uniform_probability = 1.0 / len(outcomes)
    response_contract = {
        "forecast": {
            "outcomes": [
                {"outcome": outcome, "probability": uniform_probability}
                for outcome in outcomes
            ]
        },
        "submission": {},
    }
    return (
        "Complete the task using the loaded candidate skill. Return exactly one "
        "JSON object and no Markdown. The displayed probabilities are numeric "
        "examples: replace them with your numeric forecast, never strings. The "
        "probabilities must be finite, non-negative, include every listed "
        "evaluator outcome exactly once, and sum to 1. Replace the displayed "
        "empty submission object with your actual JSON submission. Commit the "
        "forecast before any hidden evaluator is run.\n\n"
        f"Task case: {case_id}\n"
        f"Allowed evaluator outcomes: {canonical_json(outcomes)}\n"
        f"Required response shape: {canonical_json(response_contract)}\n\n"
        f"Task:\n{prompt}"
    )


def _run_agent(command: list[str], agent_name: str) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AdapterError(str(exc) or type(exc).__name__) from exc
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or f"{agent_name} exited with {completed.returncode}"
        )
        raise AdapterError(detail)
    if completed.stderr:
        raise AdapterError(f"{agent_name} wrote unexpected standard error")
    response = decode_json_object(completed.stdout, AdapterError)
    _require_exact_keys(
        response,
        {"forecast", "submission"},
        f"{agent_name} response",
    )
    return response


def run_main(*, agent_name: str, command_builder: CommandBuilder) -> int:
    try:
        request = decode_json_object(sys.stdin.read(), AdapterError)
        case_id, prompt, outcomes, skill_path = _decode_request(request)
        response = _run_agent(
            command_builder(skill_path, model_prompt(case_id, prompt, outcomes)),
            agent_name,
        )
    except (AdapterError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0
