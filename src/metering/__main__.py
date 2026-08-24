"""Strict JSON command-line boundary for agent and shell use."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from . import (
    ProbabilityError,
    __version__,
    entropy,
    kl_divergence,
    mutual_information,
    self_information,
)


class RequestError(ValueError):
    """Raised when the CLI request envelope is malformed."""


class _StrictArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise RequestError(f"invalid command line: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _StrictArgumentParser(
        prog="metering",
        description="Read one information-measure request as JSON from stdin.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
        epilog="""request examples:
  {"measure":"self_information","probability":0.125}
  {"measure":"entropy","probabilities":[0.5,0.5]}
  {"measure":"kl_divergence","p":[0.5,0.5],"q":[0.75,0.25]}
  {"measure":"mutual_information","joint":[[0.5,0],[0,0.5]]}

Add an optional numeric "base" key to any request. JSON is read from stdin.""",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _parse_arguments(argv: Sequence[str] | None) -> None:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    terminal_arguments = {("-h",), ("--help",), ("--version",)}
    if arguments and arguments not in terminal_arguments:
        raise RequestError(
            f"invalid command line arguments: {' '.join(arguments)}"
        )
    _parser().parse_args(arguments)


_REQUIRED_KEYS = {
    "self_information": frozenset({"measure", "probability"}),
    "entropy": frozenset({"measure", "probabilities"}),
    "kl_divergence": frozenset({"measure", "p", "q"}),
    "mutual_information": frozenset({"measure", "joint"}),
}
_OPTIONAL_KEYS = frozenset({"base"})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RequestError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise RequestError(f"non-finite JSON number {token!r} is not allowed")


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


def _read_request(text: str) -> dict[str, Any]:
    if not text.strip():
        raise RequestError("stdin must contain one JSON object")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
            parse_float=_parse_json_number,
            parse_int=_parse_json_number,
        )
    except RequestError:
        raise
    except json.JSONDecodeError as exc:
        raise RequestError(
            f"invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    except (RecursionError, ValueError) as exc:
        raise RequestError(f"invalid JSON: {exc}") from exc
    if type(value) is not dict:
        raise RequestError("request must be a JSON object")
    return value


def _validate_envelope(request: dict[str, Any]) -> str:
    measure = request.get("measure")
    if type(measure) is not str or measure not in _REQUIRED_KEYS:
        allowed = ", ".join(sorted(_REQUIRED_KEYS))
        raise RequestError(f"measure must be one of: {allowed}")
    required = _REQUIRED_KEYS[measure]
    missing = sorted(required - request.keys())
    extra = sorted(request.keys() - required - _OPTIONAL_KEYS)
    if missing:
        raise RequestError(f"missing request key(s): {', '.join(missing)}")
    if extra:
        raise RequestError(f"unexpected request key(s): {', '.join(extra)}")
    return measure


def _measure(request: dict[str, Any]) -> tuple[str, float, float]:
    measure = _validate_envelope(request)
    base = request.get("base", 2)
    if measure == "self_information":
        value = self_information(request["probability"], base=base)
    elif measure == "entropy":
        value = entropy(request["probabilities"], base=base)
    elif measure == "kl_divergence":
        value = kl_divergence(request["p"], request["q"], base=base)
    else:
        value = mutual_information(request["joint"], base=base)
    return measure, float(base), value


def _write_json(stream: Any, value: dict[str, Any]) -> None:
    stream.write(
        json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _write_error(code: str, message: str) -> None:
    _write_json(sys.stderr, {"error": {"code": code, "message": message}})


def main(argv: Sequence[str] | None = None) -> int:
    try:
        _parse_arguments(argv)
        request = _read_request(sys.stdin.read())
        measure, base, value = _measure(request)
    except RequestError as exc:
        _write_error("invalid_request", str(exc))
        return 2
    except ProbabilityError as exc:
        _write_error("invalid_probability", str(exc))
        return 2

    infinite = math.isinf(value)
    _write_json(
        sys.stdout,
        {
            "base": base,
            "infinite": infinite,
            "measure": measure,
            "value": None if infinite else value,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
