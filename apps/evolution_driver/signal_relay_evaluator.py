"""Strict evaluator for the constructed Signal Relay acceptance task."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import cast

APPS_ROOT = Path(__file__).resolve().parents[1]
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from agent_protocol import (  # noqa: E402
    ADAPTER_PROTOCOL_VERSION,
    ProtocolError,
    decode_task,
    normalize_json_value,
    require_exact_keys,
    require_nonempty_string,
    require_sha256,
)
from stdio_connector import (  # noqa: E402
    canonical_json,
    decode_json_object,
)

PROMPT_PATTERN = re.compile(
    r"Signal Relay v1 request\. Payload \["
    r"([a-z]+) ([a-z]+) ([a-z]+) ([a-z]+)"
    r"\]\. Return the protocol response in submission\.answer\."
)


class EvaluatorError(ValueError):
    """Raised when a Signal Relay evaluator request is malformed."""


def _decode_request(source: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    request = decode_json_object(source, EvaluatorError)
    try:
        require_exact_keys(
            request,
            {"case", "evaluation", "protocol_version", "submissions"},
            "request",
        )
        if (
            type(request["protocol_version"]) is not int
            or request["protocol_version"] != ADAPTER_PROTOCOL_VERSION
        ):
            raise ProtocolError("unsupported evaluator adapter protocol")
        evaluation = require_nonempty_string(request["evaluation"], "evaluation")
        if evaluation not in {
            "signal-relay/development-v1",
            "signal-relay/untouched-final-v1",
        }:
            raise ProtocolError("unsupported Signal Relay evaluation")
        case = decode_task(request["case"], "case")
        task_input = case["input"]
        if type(task_input) is not dict:
            raise ProtocolError("case.input must be a JSON object")
        require_exact_keys(task_input, {"outcomes", "prompt"}, "case.input")
        if task_input["outcomes"] != ["fail", "pass"]:
            raise ProtocolError("case.input.outcomes must be [\"fail\",\"pass\"]")
        prompt = require_nonempty_string(task_input["prompt"], "case.input.prompt")
        if PROMPT_PATTERN.fullmatch(prompt) is None:
            raise ProtocolError("case.input.prompt is not a Signal Relay v1 task")

        raw_submissions = request["submissions"]
        if type(raw_submissions) is not list or len(raw_submissions) != 2:
            raise ProtocolError("submissions must contain exactly two candidates")
        submissions: list[dict[str, object]] = []
        seen: set[str] = set()
        for index, raw_submission in enumerate(raw_submissions):
            location = f"submissions[{index}]"
            if type(raw_submission) is not dict:
                raise ProtocolError(f"{location} must be a JSON object")
            require_exact_keys(
                raw_submission, {"candidate_id", "submission"}, location
            )
            candidate_id = require_sha256(
                raw_submission["candidate_id"], f"{location}.candidate_id"
            )
            if candidate_id in seen:
                raise ProtocolError("submissions contains a duplicate candidate ID")
            seen.add(candidate_id)
            submissions.append(
                {
                    "candidate_id": candidate_id,
                    "submission": normalize_json_value(
                        raw_submission["submission"], f"{location}.submission"
                    ),
                }
            )
    except ProtocolError as exc:
        raise EvaluatorError(str(exc)) from exc
    return case, submissions


def _expected_answer(case: dict[str, object]) -> str:
    task_input = cast(dict[str, object], case["input"])
    prompt = cast(str, task_input["prompt"])
    match = PROMPT_PATTERN.fullmatch(prompt)
    if match is None:
        raise EvaluatorError("case.input.prompt is not a Signal Relay v1 task")
    letters = "".join(word[0] for word in match.groups()).upper()
    return f"SR1-{letters}-OK"


def evaluate(source: str) -> dict[str, object]:
    case, submissions = _decode_request(source)
    expected = _expected_answer(case)
    results: list[dict[str, object]] = []
    for item in submissions:
        submission = item["submission"]
        if type(submission) is dict:
            answer = submission.get("answer")
            shape_valid = set(submission) == {"answer"} and type(answer) is str
        else:
            answer = None
            shape_valid = False
        passed = shape_valid and answer == expected
        results.append(
            {
                "candidate_id": item["candidate_id"],
                "evidence": {
                    "answer_exact": passed,
                    "submission_shape_valid": shape_valid,
                },
                "outcome": "pass" if passed else "fail",
                "passed": passed,
                "safety_passed": shape_valid,
            }
        )
    return {"results": results}


def _read_stdin() -> str:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return sys.stdin.read()
    try:
        return stream.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluatorError("standard input must be valid UTF-8 JSON") from exc


def main() -> int:
    try:
        response = evaluate(_read_stdin())
    except (EvaluatorError, ProtocolError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
