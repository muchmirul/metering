"""Small command helpers shared by reviewed fixed CLI connectors."""

from __future__ import annotations

import json
import os
from pathlib import Path


def command_prefix(
    command_environment: str,
    binary_environment: str,
    default_binary: str,
) -> list[str]:
    """Return one caller-pinned command prefix without invoking a shell."""

    source = os.environ.get(command_environment)
    if source is not None:
        if not source.strip():
            raise ValueError(
                f"{command_environment} must contain a non-empty JSON string array"
            )
        try:
            value = json.loads(source)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{command_environment} is invalid JSON: {exc}") from exc
        if type(value) is not list or not value or any(
            type(item) is not str or not item or "\x00" in item for item in value
        ):
            raise ValueError(
                f"{command_environment} must contain a non-empty JSON string array"
            )
        return value

    binary = os.environ.get(binary_environment, default_binary)
    if not binary or "\x00" in binary:
        raise ValueError(f"{binary_environment} must name one executable")
    return [binary]


def read_skill_text(skill_file: Path, location: str) -> str:
    """Read one materialized candidate skill for explicit prompt injection."""

    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read {location}: {exc}") from exc
    if not text or "\x00" in text:
        raise ValueError(f"{location} must be non-empty UTF-8 text without NUL")
    return text
