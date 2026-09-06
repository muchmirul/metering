"""Bounded operator diagnostics, never optimizer feedback or execution authority."""

from __future__ import annotations

import hashlib
import os
import re

from apps._support.process import JsonProcessError

MAX_EXCERPT = 4096
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)((?:api[_-]?key|(?:access[_-]?)?token|password|secret)\s*[=:]\s*[\"']?)[^\s,;\"']+"
)
_BEARER = re.compile(r"(?i)\b(Bearer|Basic)\s+[^\s,;\"']+")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def operator_excerpt(text: str) -> str:
    # Bound first: diagnostic handling must not create unbounded derivative data.
    # Strip terminal escapes before matching: an ANSI prefix can otherwise hide
    # the word boundary before "Bearer", leaving its credential unredacted.
    text = _CONTROL.sub("", _ANSI.sub("", text[: MAX_EXCERPT * 2]))
    for name, value in os.environ.items():
        if len(value) >= 4 and any(
            word in name.upper() for word in ("SECRET", "TOKEN", "PASSWORD", "API_KEY")
        ):
            text = text.replace(value, "[REDACTED]")
    text = _BEARER.sub(lambda match: match[1] + " [REDACTED]", text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: match[1] + "[REDACTED]", text)
    return text[:MAX_EXCERPT]


def exception_summary(error: BaseException) -> str:
    if isinstance(error, JsonProcessError):
        suffix = (
            f" (returncode={error.returncode})" if error.returncode is not None else ""
        )
        return error.kind + suffix
    return operator_excerpt(str(error).strip()) or type(error).__name__


def exception_document(error: BaseException) -> dict[str, object]:
    stderr = error.stderr if isinstance(error, JsonProcessError) else ""
    detail = error.detail if isinstance(error, JsonProcessError) else str(error)
    return {
        "exception_type": type(error).__name__,
        "kind": error.kind if isinstance(error, JsonProcessError) else "exception",
        "returncode": error.returncode if isinstance(error, JsonProcessError) else None,
        "summary": exception_summary(error),
        "detail_excerpt": operator_excerpt(detail),
        "stderr_excerpt": operator_excerpt(stderr),
        "stderr_sha256": hashlib.sha256(stderr.encode("utf-8", "replace")).hexdigest(),
        "stderr_truncated": len(stderr) > MAX_EXCERPT,
    }
