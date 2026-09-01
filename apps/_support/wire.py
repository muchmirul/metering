"""Strict canonical-JSON wire primitives for source-only applications."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import TextIO, TypeAlias

JsonDocument: TypeAlias = dict[str, object]
NumberParser: TypeAlias = Callable[[str], object]


def canonical_json(value: object) -> str:
    """Return the applications' canonical ASCII JSON representation."""

    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_digest(value: object) -> str:
    """Return the SHA-256 digest of canonical ASCII JSON."""

    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def strict_json_float(token: str) -> float:
    """Convert one JSON decimal token without changing zero/one membership."""

    try:
        exact = Decimal(token)
        converted = float(token)
    except (InvalidOperation, OverflowError, ValueError) as error:
        raise ValueError("JSON number exceeds supported numeric limits") from error
    if not math.isfinite(converted):
        raise ValueError("JSON number is outside the finite double-precision range")
    if (converted == 0.0 and exact != 0) or (converted == 1.0 and exact != 1):
        raise ValueError(
            "JSON number would change whether its value is zero or one "
            "in double precision"
        )
    return 0.0 if converted == 0.0 else converted


def decode_json_object(
    source: str,
    error_type: type[Exception],
    *,
    parse_float: NumberParser = strict_json_float,
    parse_int: NumberParser = int,
) -> JsonDocument:
    """Decode one strict JSON object using an application's numeric policy."""

    if not source.strip():
        raise error_type("stdin must contain one JSON object")

    def unique_object(pairs: list[tuple[str, object]]) -> JsonDocument:
        result: JsonDocument = {}
        for key, value in pairs:
            if key in result:
                raise error_type(f"duplicate key: {key}")
            result[key] = value
        return result

    def reject_non_finite(token: str) -> object:
        raise error_type(f"non-finite number is not valid JSON: {token}")

    try:
        document = json.loads(
            source,
            object_pairs_hook=unique_object,
            parse_constant=reject_non_finite,
            parse_float=parse_float,
            parse_int=parse_int,
        )
    except error_type:
        raise
    except json.JSONDecodeError as error:
        raise error_type(f"invalid JSON: {error.msg}") from error
    except (ArithmeticError, RecursionError, ValueError) as error:
        raise error_type(f"invalid JSON: {error}") from error
    if type(document) is not dict:
        raise error_type("request must be one JSON object")
    return document


def error_document(code: str, message: str) -> JsonDocument:
    return {"error": {"code": code, "message": message}}


def write_document(stream: TextIO, document: JsonDocument) -> None:
    stream.write(canonical_json(document) + "\n")
    stream.flush()
