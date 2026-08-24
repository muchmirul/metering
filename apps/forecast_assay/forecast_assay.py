"""Measure agent-supplied candidates through one-shot or JSONL transport."""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from metering import ProbabilityError, self_information


SCHEMA_VERSION = 1


class RequestError(ValueError):
    """Raised when the agent request does not match the application contract."""


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RequestError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_non_finite(token: str) -> object:
    raise RequestError(f"non-finite number is not valid JSON: {token}")


def _parse_json_number(token: str) -> float:
    try:
        exact_value = Decimal(token)
        value = float(token)
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise RequestError("JSON number exceeds supported numeric limits") from exc
    if not math.isfinite(value):
        raise RequestError(
            "JSON number is outside the finite double-precision range"
        )
    if (value == 0.0 and exact_value != 0) or (
        value == 1.0 and exact_value != 1
    ):
        raise RequestError(
            "JSON number would change whether its value is zero or one "
            "in double precision"
        )
    return value


def _parse_json_integer(token: str) -> int:
    try:
        exact_value = int(token)
        value = float(exact_value)
    except (OverflowError, ValueError) as exc:
        raise RequestError("JSON number exceeds supported numeric limits") from exc
    if not math.isfinite(value):
        raise RequestError(
            "JSON number is outside the finite double-precision range"
        )
    return exact_value


def _require_exact_keys(
    value: dict[str, object], expected: set[str], location: str
) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing keys: {', '.join(missing)}")
    if extra:
        details.append(f"extra keys: {', '.join(extra)}")
    if details:
        raise RequestError(f"{location}: {'; '.join(details)}")


def _require_nonempty_string(value: object, location: str) -> str:
    if type(value) is not str or not value:
        raise RequestError(f"{location} must be a non-empty string")
    return value


def decode_request(source: str) -> tuple[str, str, list[dict[str, object]]]:
    """Decode one strict candidate-measurement request."""

    if not source.strip():
        raise RequestError("stdin must contain one JSON object")
    try:
        request = json.loads(
            source,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite,
            parse_float=_parse_json_number,
            parse_int=_parse_json_integer,
        )
    except RequestError:
        raise
    except json.JSONDecodeError as exc:
        raise RequestError(f"invalid JSON: {exc.msg}") from exc
    except (RecursionError, ValueError) as exc:
        raise RequestError(f"invalid JSON: {exc}") from exc

    if type(request) is not dict:
        raise RequestError("request must be one JSON object")
    _require_exact_keys(
        request,
        {"schema_version", "candidate", "evaluation", "observations"},
        "request",
    )
    if (
        type(request["schema_version"]) is not int
        or request["schema_version"] != SCHEMA_VERSION
    ):
        raise RequestError(f"schema_version must be {SCHEMA_VERSION}")

    candidate = _require_nonempty_string(request["candidate"], "candidate")
    evaluation = _require_nonempty_string(request["evaluation"], "evaluation")
    observations = request["observations"]
    if type(observations) is not list or not observations:
        raise RequestError("observations must be a non-empty JSON array")

    decoded_observations: list[dict[str, object]] = []
    seen_observations: set[str] = set()
    expected_observation_keys = {
        "observation",
        "target",
        "target_probability",
    }
    for index, observation in enumerate(observations):
        location = f"observations[{index}]"
        if type(observation) is not dict:
            raise RequestError(f"{location} must be a JSON object")
        _require_exact_keys(observation, expected_observation_keys, location)
        observation_id = _require_nonempty_string(
            observation["observation"], f"{location}.observation"
        )
        target = _require_nonempty_string(
            observation["target"], f"{location}.target"
        )
        if observation_id in seen_observations:
            raise RequestError(
                f"duplicate observation identifier: {observation_id}"
            )
        seen_observations.add(observation_id)
        decoded_observations.append(
            {
                "observation": observation_id,
                "target": target,
                "target_probability": observation["target_probability"],
            }
        )
    return candidate, evaluation, decoded_observations


def measure_candidate(
    candidate: str,
    evaluation: str,
    observations: Sequence[dict[str, object]],
) -> dict[str, object]:
    """Return named measurements without selecting or changing the candidate."""

    outcomes: list[dict[str, object]] = []
    finite_values: list[float] = []
    infinite = False
    for index, observation in enumerate(observations):
        probability = observation["target_probability"]
        try:
            value = self_information(probability, base=2)
        except ProbabilityError as exc:
            raise ProbabilityError(
                f"observations[{index}].target_probability: {exc}"
            ) from exc
        outcome_is_infinite = math.isinf(value)
        infinite = infinite or outcome_is_infinite
        if not outcome_is_infinite:
            finite_values.append(value)
        probability_value = float(probability)
        outcomes.append(
            {
                "infinite": outcome_is_infinite,
                "observation": observation["observation"],
                "target": observation["target"],
                "target_probability": (
                    0.0 if probability_value == 0.0 else probability_value
                ),
                "value_bits": None if outcome_is_infinite else value,
            }
        )

    mean = None if infinite else math.fsum(finite_values) / len(outcomes)
    return {
        "candidate": candidate,
        "evaluation": evaluation,
        "schema_version": SCHEMA_VERSION,
        "measurement": {
            "aggregate": {
                "infinite": infinite,
                "mean_target_surprisal_bits": mean,
                "sample_count": len(outcomes),
            },
            "base": 2.0,
            "metering_measure": "self_information",
            "outcomes": outcomes,
        },
    }


def _error_document(code: str, message: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message}}


def _write_document(stream: object, document: dict[str, object]) -> None:
    stream.write(canonical_json(document) + "\n")
    stream.flush()


def _write_error(code: str, message: str) -> None:
    _write_document(sys.stderr, _error_document(code, message))


def _read_stdin() -> str:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return sys.stdin.read()
    try:
        return stream.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RequestError("standard input must be valid UTF-8 JSON") from exc


def _measure_source(source: str) -> dict[str, object]:
    candidate, evaluation, observations = decode_request(source)
    return measure_candidate(candidate, evaluation, observations)


def _run_jsonl() -> int:
    """Process independent candidate requests until standard-input EOF."""

    binary_input = getattr(sys.stdin, "buffer", None)
    while True:
        invalid_utf8 = False
        try:
            if binary_input is None:
                source = sys.stdin.readline()
                if source == "":
                    break
            else:
                raw = binary_input.readline()
                if raw == b"":
                    break
                try:
                    source = raw.decode("utf-8")
                except UnicodeDecodeError:
                    source = ""
                    invalid_utf8 = True
        except OSError as exc:
            _write_error("invalid_request", f"cannot read standard input: {exc}")
            return 2

        try:
            if invalid_utf8:
                raise RequestError("request line must be valid UTF-8 JSON")
            response = _measure_source(source)
        except RequestError as exc:
            response = _error_document("invalid_request", str(exc))
        except ProbabilityError as exc:
            response = _error_document("invalid_probability", str(exc))
        _write_document(sys.stdout, response)
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["--jsonl"]:
        return _run_jsonl()
    if arguments:
        _write_error("invalid_request", "command-line arguments are not supported")
        return 2
    try:
        response = _measure_source(_read_stdin())
    except RequestError as exc:
        _write_error("invalid_request", str(exc))
        return 2
    except ProbabilityError as exc:
        _write_error("invalid_probability", str(exc))
        return 2
    _write_document(sys.stdout, response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
