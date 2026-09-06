"""Versioned coding checks; output assertions are interpreted outside the sandbox."""

from __future__ import annotations

from apps._support.wire import canonical_json, decode_json_object

OUTPUT_CHECK_SCHEMA = "stdout-json-v1"
LEGACY_ASSAY_KEYS = {"argv", "timeout_ms"}
OUTPUT_ASSAY_KEYS = {*LEGACY_ASSAY_KEYS, "check_schema", "expected_stdout"}
MAX_EXPECTED_CHARACTERS = 65_536


class CheckError(ValueError):
    """Raised when a declared independent output check is malformed."""


def validate_output_contract(assay: dict[str, object]) -> None:
    if set(assay) == LEGACY_ASSAY_KEYS:
        return
    if set(assay) != OUTPUT_ASSAY_KEYS or assay["check_schema"] != OUTPUT_CHECK_SCHEMA:
        raise CheckError("coding output check schema or keys are unsupported")
    expected = assay["expected_stdout"]
    if type(expected) is not dict or not expected:
        raise CheckError("coding expected_stdout must be a non-empty JSON object")
    try:
        source = canonical_json(expected)
        if len(source) > MAX_EXPECTED_CHARACTERS:
            raise CheckError("coding expected_stdout exceeds the output bound")
        decode_json_object(source, CheckError)
    except (ValueError, TypeError, RecursionError) as exc:
        raise CheckError("coding expected_stdout must be bounded strict JSON") from exc


def check_passed(execution: dict[str, object], assay: dict[str, object]) -> bool:
    """Derive an outcome from authenticated raw output, not a candidate pass flag.

    Legacy argv checks keep their original exit-status-only meaning. New output
    checks require one complete strict JSON object with exactly the declared
    structure, values and JSON types. Expected values never enter the sandbox.
    """
    validate_output_contract(assay)
    if (
        type(execution["returncode"]) is not int
        or execution["returncode"] != 0
        or execution["timed_out"] is not False
    ):
        return False
    if set(assay) == LEGACY_ASSAY_KEYS:
        return True
    stdout = execution["stdout"]
    if type(stdout) is not str or len(stdout) > MAX_EXPECTED_CHARACTERS:
        return False
    try:
        actual = decode_json_object(stdout, CheckError)
        return canonical_json(actual) == canonical_json(assay["expected_stdout"])
    except (CheckError, ValueError, TypeError, RecursionError):
        return False
