"""Pi adapter for text-only agent-skill evaluation tasks.

The surrounding Candidate Runner owns the timeout. This adapter disables tools,
context files, discovered skills, extensions, prompt templates, and session
persistence. It injects the verified `SKILL.md` because Pi's normal progressive
skill disclosure requires the disabled `read` tool.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


class AdapterError(ValueError):
    """Raised when the adapter request or Pi response is invalid."""


def canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AdapterError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite(token: str) -> object:
    raise AdapterError(f"non-finite JSON number: {token}")


def _decode_json(source: str, location: str) -> dict[str, object]:
    try:
        value = json.loads(
            source,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite,
        )
    except AdapterError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise AdapterError(f"invalid {location} JSON: {error}") from error
    if type(value) is not dict:
        raise AdapterError(f"{location} must be one JSON object")
    return value


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


def _model_prompt(case_id: str, prompt: str, outcomes: list[str]) -> str:
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


def _pi_command(skill_path: str | None, prompt: str) -> list[str]:
    command = [
        os.environ.get("PI_BIN", "pi"),
        "--no-session",
        "--no-skills",
        "--no-extensions",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--no-tools",
    ]
    if skill_path is not None:
        skill_file = Path(skill_path) / "SKILL.md"
        if not skill_file.is_file():
            raise AdapterError("candidate skill does not contain SKILL.md")
        try:
            skill_text = skill_file.read_text(encoding="utf-8")
        except OSError as error:
            raise AdapterError(f"cannot read candidate SKILL.md: {error}") from error
        if not skill_text or "\x00" in skill_text:
            raise AdapterError("candidate SKILL.md must be non-empty UTF-8 text without NUL")
        candidate_instructions = (
            "The following is the complete, caller-selected candidate skill. "
            "Apply it to the user task.\n\n"
            f"<candidate_skill path={canonical_json(str(skill_file))}>\n"
            f"{skill_text}\n"
            "</candidate_skill>"
        )
        command.extend(
            [
                "--skill",
                str(skill_file),
                "--append-system-prompt",
                candidate_instructions,
            ]
        )
    command.extend(["-p", prompt])
    return command


def _run_pi(command: list[str]) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise AdapterError(str(error) or type(error).__name__) from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"Pi exited with {completed.returncode}"
        raise AdapterError(detail)
    if completed.stderr:
        raise AdapterError("Pi wrote unexpected standard error")
    response = _decode_json(completed.stdout, "Pi response")
    _require_exact_keys(response, {"forecast", "submission"}, "Pi response")
    return response


def main() -> int:
    try:
        request = _decode_json(sys.stdin.read(), "candidate adapter request")
        case_id, prompt, outcomes, skill_path = _decode_request(request)
        model_prompt = _model_prompt(case_id, prompt, outcomes)
        response = _run_pi(_pi_command(skill_path, model_prompt))
    except (AdapterError, TypeError, ValueError) as error:
        print(str(error) or type(error).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
