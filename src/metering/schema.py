"""Shared artifact vocabulary and strict field decoding for Metering.

Every Metering artifact is strict JSON.  Each object has an exact key set, each
scalar has an exact type, and every number is finite.  Those rules are defined
once here so that the controller that writes an artifact, the reader that loads
it, and the offline meters that interpret it cannot drift apart.

Each module binds :class:`StrictFields` to its own error class, so a caller
still catches the error type that belongs to the boundary it called.  For
example, ``metering.events`` raises ``EventError`` and ``metering.report``
raises ``ReportError``, and both reuse the same checks.
"""

from __future__ import annotations

import math
import re
import uuid
from typing import Any, Final, Iterable

# Schema versions.  Each one gates a strict decoder, so changing a value here is
# a compatibility decision rather than a cosmetic edit.
EVENT_SCHEMA_VERSION: Final = 1
PUBLIC_INSTANCE_SCHEMA_VERSION: Final = 1
REFERENCE_SCHEMA_VERSION: Final = 1
MANIFEST_SCHEMA_VERSION: Final = 1
REPORT_SCHEMA_VERSION: Final = 1
CALIBRATION_SCHEMA_VERSION: Final = 1

# The four canonical event types.  A trace begins with one run_started event,
# continues with interaction or protocol_error events, and ends with exactly one
# termination event.
EVENT_RUN_STARTED: Final = "run_started"
EVENT_INTERACTION: Final = "interaction"
EVENT_PROTOCOL_ERROR: Final = "protocol_error"
EVENT_TERMINATION: Final = "termination"

# The four ways a run can end.  Only the first one counts as normal completion.
TERMINATION_NORMAL: Final = "normal_finish"
TERMINATION_INVALID_ACTION: Final = "invalid_action"
TERMINATION_HARNESS_CRASH: Final = "harness_crash"
TERMINATION_BUDGET_EXHAUSTED: Final = "budget_exhausted"
TERMINATION_REASONS: Final = frozenset(
    {
        TERMINATION_NORMAL,
        TERMINATION_INVALID_ACTION,
        TERMINATION_HARNESS_CRASH,
        TERMINATION_BUDGET_EXHAUSTED,
    }
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class SchemaError(ValueError):
    """Raised when a value does not match its declared Metering schema."""


class ReportError(SchemaError):
    """Raised when raw artifacts are inconsistent or a trace is corrupt.

    This error belongs to the artifact contract rather than to one module, so
    both strict replay and report building raise it.
    """


def is_canonical_uuid4(value: object) -> bool:
    """Return whether ``value`` is the canonical text form of a UUID4."""

    if type(value) is not str:
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value


class StrictFields:
    """Strict JSON field checks that raise one caller-chosen error type.

    Metering never repairs malformed input.  A check either returns the value
    with its exact type confirmed or raises, and the message always names the
    field so a failure points at one place in one artifact.

    The error type is supplied by the caller because the same rule is enforced
    at several boundaries.  A malformed action is an ``EventError`` and a
    malformed manifest is a ``ReportError``, and both are checked here.
    """

    __slots__ = ("error",)

    def __init__(self, error: type[Exception] = SchemaError) -> None:
        self.error = error

    def mapping(self, value: object, name: str) -> dict[str, Any]:
        """Require an exact ``dict``, because JSON objects decode to one."""

        if type(value) is not dict:
            raise self.error(f"{name} must be an object")
        return value

    def exact_keys(
        self, value: object, expected: Iterable[str], name: str
    ) -> dict[str, Any]:
        """Require an object whose key set is exactly ``expected``.

        Missing and unexpected keys are reported together so that a schema
        mismatch can be read in one pass.
        """

        data = self.mapping(value, name)
        wanted = set(expected)
        keys = set(data)
        if keys != wanted:
            missing = sorted(wanted - keys)
            extra = sorted(keys - wanted)
            raise self.error(
                f"{name} has invalid schema; missing keys: {missing!r}; "
                f"unexpected keys: {extra!r}"
            )
        return data

    def text(self, value: object, name: str) -> str:
        if type(value) is not str or not value:
            raise self.error(f"{name} must be a non-empty string")
        return value

    def integer(self, value: object, name: str, *, minimum: int | None = 0) -> int:
        """Require an exact ``int``.

        ``True`` is an instance of ``int`` in Python, so an identity check on
        the type is what keeps a Boolean out of a count field.
        """

        if type(value) is not int:
            raise self.error(f"{name} must be an exact integer")
        if minimum is not None and value < minimum:
            raise self.error(f"{name} must be an exact integer >= {minimum}")
        return value

    def boolean(self, value: object, name: str) -> bool:
        if type(value) is not bool:
            raise self.error(f"{name} must be an exact bool")
        return value

    def sha256_digest(self, value: object, name: str) -> str:
        digest = self.text(value, name)
        if _SHA256_PATTERN.fullmatch(digest) is None:
            raise self.error(f"{name} must be a lowercase SHA-256 hex digest")
        return digest

    def uuid4(self, value: object, name: str) -> str:
        text = self.text(value, name)
        if not is_canonical_uuid4(text):
            raise self.error(f"{name} must be a canonical UUID4 string")
        return text

    def finite_json(self, value: object, name: str) -> None:
        """Walk a decoded value and reject anything JSON cannot carry exactly.

        Non-finite floats are rejected because they have no JSON spelling, and
        non-string object keys are rejected because they would change meaning
        when encoded.
        """

        if value is None or type(value) in {str, bool, int}:
            return
        if type(value) is float:
            if not math.isfinite(value):
                raise self.error(f"{name} contains a non-finite number")
            return
        if type(value) is list:
            for index, item in enumerate(value):
                self.finite_json(item, f"{name}[{index}]")
            return
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise self.error(f"{name} contains a non-string object key")
                self.finite_json(item, f"{name}.{key}")
            return
        raise self.error(
            f"{name} contains a non-JSON value of type {type(value).__name__}"
        )
