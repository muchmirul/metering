"""Strict subprocess mechanics shared by the two Controller workflows."""

from __future__ import annotations

import json
import math
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

APPS_ROOT = Path(__file__).resolve().parents[1]
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from stdio_connector import (  # noqa: E402
    JsonProcessError,
    decode_json_object,
    run_json_process,
)

ROOT = Path(__file__).resolve().parents[2]
COMPONENT_TIMEOUT_SECONDS = 10
CANDIDATE_RUNNER = "apps/candidate_runner/candidate_runner.py"
FORECAST_ASSAY = "apps/forecast_assay/forecast_assay.py"
MUTATOR = "apps/mutator/mutator.py"
OBSERVER = "apps/observer/observer.py"
SELECTION_GATE = "apps/selection_gate/selection_gate.py"


class RequestError(ValueError):
    """Raised when a controller request violates its protocol."""


class ControllerError(RuntimeError):
    """Raised when a component or composition invariant fails."""


def _parse_json_number(token: str) -> float:
    try:
        exact = Decimal(token)
        converted = float(exact)
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise RequestError("JSON number exceeds supported numeric limits") from exc
    if not math.isfinite(converted):
        raise RequestError("JSON number is outside the finite double range")
    if (converted == 0.0 and exact != 0) or (
        converted == 1.0 and exact != 1
    ):
        raise RequestError(
            "JSON number would change whether its value is zero or one "
            "in double precision"
        )
    return converted


def _decode_json(source: str) -> dict[str, object]:
    return decode_json_object(
        source,
        RequestError,
        parse_float=_parse_json_number,
    )


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


def _component_error_detail(stderr: str, returncode: int) -> str:
    detail = stderr.strip()
    if detail:
        try:
            document = json.loads(detail)
            error = document.get("error")
            if type(error) is dict and type(error.get("message")) is str:
                return str(error["message"])
        except (AttributeError, json.JSONDecodeError):
            pass
        return detail
    return f"exit status {returncode}"


def _decode_component_output(
    name: str, source: str, *, allow_error: bool = False
) -> dict[str, object]:
    try:
        response = json.loads(
            source,
            object_pairs_hook=lambda pairs: _component_unique_object(name, pairs),
            parse_constant=lambda token: _component_non_finite(name, token),
        )
    except (ControllerError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, ControllerError):
            raise
        raise ControllerError(f"{name} returned invalid JSON: {exc}") from exc
    if type(response) is not dict:
        raise ControllerError(f"{name} response must be one JSON object")
    if "error" in response and not allow_error:
        raise ControllerError(f"{name} returned an error response")
    return response


def _component_unique_object(
    name: str, pairs: list[tuple[str, object]]
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ControllerError(f"{name} returned duplicate key: {key}")
        result[key] = value
    return result


def _component_non_finite(name: str, token: str) -> object:
    raise ControllerError(f"{name} returned a non-finite number: {token}")


def _run_component(
    name: str,
    relative_path: str,
    request: dict[str, object],
    *,
    arguments: tuple[str, ...] = (),
    timeout_seconds: int = COMPONENT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    command = [sys.executable, str(ROOT / relative_path), *arguments]
    try:
        source = run_json_process(
            command,
            request,
            cwd=ROOT,
            timeout_seconds=timeout_seconds,
        )
    except JsonProcessError as error:
        if error.kind == "timeout":
            message = f"{name} exceeded the component timeout"
        elif error.kind == "start":
            message = f"cannot start {name}: {error.detail}"
        elif error.kind == "exit":
            returncode = error.returncode if error.returncode is not None else 1
            detail = _component_error_detail(error.stderr, returncode)
            message = f"{name} failed: {detail}"
        else:
            message = f"{name} wrote unexpected standard error"
        raise ControllerError(message) from error
    return _decode_component_output(name, source)


def _require_component_object(
    value: object, location: str
) -> dict[str, object]:
    if type(value) is not dict:
        raise ControllerError(f"{location} must be a JSON object")
    return value
