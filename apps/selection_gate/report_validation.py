"""Numeric and envelope validation shared by Selection Gate schemas."""

from __future__ import annotations

import math
from decimal import Decimal

REPORT_TOLERANCE = 1e-12


class RequestError(ValueError):
    """Raised when a selection request or report violates the contract."""


def require_exact_keys(
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


def require_nonempty_string(value: object, location: str) -> str:
    if type(value) is not str or not value:
        raise RequestError(f"{location} must be a non-empty string")
    return value


def require_bool(value: object, location: str) -> bool:
    if type(value) is not bool:
        raise RequestError(f"{location} must be a boolean")
    return value


def number_as_float(value: object, location: str) -> tuple[Decimal, float]:
    if type(value) is bool or not isinstance(value, (int, Decimal)):
        raise RequestError(f"{location} must be a finite JSON number")
    exact = Decimal(value) if type(value) is int else value
    try:
        converted = float(exact)
    except (OverflowError, ValueError) as exc:
        raise RequestError(f"{location} is outside the finite double range") from exc
    if not math.isfinite(converted):
        raise RequestError(f"{location} is outside the finite double range")
    return exact, converted


def probability(value: object, location: str) -> float:
    exact, converted = number_as_float(value, location)
    if exact < 0 or exact > 1:
        raise RequestError(f"{location} must be between 0 and 1")
    if (converted == 0.0 and exact != 0) or (converted == 1.0 and exact != 1):
        raise RequestError(
            f"{location} would change whether its value is zero or one "
            "in double precision"
        )
    return 0.0 if converted == 0.0 else converted


def nonnegative_number(value: object, location: str) -> float:
    exact, converted = number_as_float(value, location)
    if exact < 0:
        raise RequestError(f"{location} must be greater than or equal to 0")
    if converted == 0.0 and exact != 0:
        raise RequestError(f"{location} is positive but rounds to 0")
    return 0.0 if converted == 0.0 else converted


def same_number(left: float, right: float) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=REPORT_TOLERANCE,
        abs_tol=REPORT_TOLERANCE,
    )
