"""Strict Pi-compatible JSON-event transport for evolutionary harness turns."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable

from apps._support.wire import canonical_json, decode_json_object
from apps.harness.model_contract import ModelContractError, decode_model_request

CommandBuilder = Callable[[dict[str, object]], list[str]]


class HarnessModelAdapterError(RuntimeError):
    """Raised when a fixed agent CLI does not return one model action."""


def pinned_model_arguments() -> tuple[str, str, str]:
    values: list[str] = []
    for name in (
        "METERING_HARNESS_PROVIDER",
        "METERING_HARNESS_MODEL",
        "METERING_HARNESS_REASONING",
    ):
        value = os.environ.get(name)
        if not value or "\x00" in value:
            raise HarnessModelAdapterError(f"{name} must pin the model transport")
        values.append(value)
    return values[0], values[1], values[2]


def verify_implementation(
    command: list[str], expected_version: str, agent_name: str
) -> None:
    """Fail closed when the executable differs from the runtime identity."""

    try:
        completed = subprocess.run(
            [*command, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HarnessModelAdapterError(
            f"cannot verify {agent_name} implementation: {exc}"
        ) from exc
    if completed.returncode != 0 or completed.stderr:
        detail = completed.stderr.strip() or f"{agent_name} --version failed"
        raise HarnessModelAdapterError(detail)
    if completed.stdout.strip() != expected_version:
        raise HarnessModelAdapterError(
            f"{agent_name} version does not match runtime identity"
        )


def agent_arguments(request: dict[str, object]) -> list[str]:
    provider, model, reasoning = pinned_model_arguments()
    return [
        "--provider",
        provider,
        "--model",
        model,
        "--thinking",
        reasoning,
        "--no-session",
        "--no-skills",
        "--no-extensions",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--no-tools",
        "--mode",
        "json",
        "--system-prompt",
        str(request["system_prompt"]),
        "-p",
        str(request["prompt"]),
    ]


def _output_limit() -> int:
    source = os.environ.get("METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES", "262144")
    try:
        value = int(source)
    except ValueError as exc:
        raise HarnessModelAdapterError(
            "METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES must be an integer"
        ) from exc
    if not 1024 <= value <= 16_777_216:
        raise HarnessModelAdapterError(
            "METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES must be from 1024 through 16777216"
        )
    return value


def _timeout() -> int:
    source = os.environ.get("METERING_HARNESS_MODEL_TIMEOUT", "300")
    try:
        value = int(source)
    except ValueError as exc:
        raise HarnessModelAdapterError(
            "METERING_HARNESS_MODEL_TIMEOUT must be an integer"
        ) from exc
    if not 1 <= value <= 3600:
        raise HarnessModelAdapterError(
            "METERING_HARNESS_MODEL_TIMEOUT must be from 1 through 3600"
        )
    return value


def _assistant(events: str, agent_name: str) -> tuple[str, int, int]:
    final: dict[str, object] | None = None
    for number, line in enumerate(events.splitlines(), start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HarnessModelAdapterError(
                f"{agent_name} JSON event {number} is invalid"
            ) from exc
        if type(event) is not dict:
            raise HarnessModelAdapterError(
                f"{agent_name} JSON event {number} must be an object"
            )
        message = event.get("message")
        if event.get("type") == "message_end" and type(message) is dict:
            if message.get("role") == "assistant":
                final = message
    if final is None:
        raise HarnessModelAdapterError(
            f"{agent_name} omitted its final assistant message"
        )
    content = final.get("content")
    if type(content) is not list:
        raise HarnessModelAdapterError(f"{agent_name} assistant content is malformed")
    text_parts: list[str] = []
    for item in content:
        if type(item) is not dict:
            raise HarnessModelAdapterError(
                f"{agent_name} assistant content is malformed"
            )
        kind = item.get("type")
        if kind == "text" and type(item.get("text")) is str:
            text_parts.append(str(item["text"]))
        elif kind == "thinking":
            continue
        else:
            raise HarnessModelAdapterError(
                f"{agent_name} returned non-text content with tools disabled"
            )
    text = "".join(text_parts)
    if not text:
        raise HarnessModelAdapterError(f"{agent_name} returned an empty action")
    usage = final.get("usage")
    if type(usage) is not dict:
        raise HarnessModelAdapterError(f"{agent_name} omitted final token usage")
    input_tokens = usage.get("input")
    output_tokens = usage.get("output")
    if type(input_tokens) is not int or input_tokens < 0:
        raise HarnessModelAdapterError(f"{agent_name} input token usage is malformed")
    if type(output_tokens) is not int or output_tokens < 0:
        raise HarnessModelAdapterError(f"{agent_name} output token usage is malformed")
    return text, input_tokens, output_tokens


def invoke_model(
    source: str,
    *,
    agent_name: str,
    command_builder: CommandBuilder,
) -> dict[str, object]:
    raw_request = decode_json_object(source, HarnessModelAdapterError)
    try:
        request = decode_model_request(raw_request)
    except ModelContractError as exc:
        raise HarnessModelAdapterError(str(exc)) from exc
    command = command_builder(request)
    try:
        with tempfile.TemporaryDirectory(prefix="metering-harness-model-") as temporary:
            completed = subprocess.run(
                command,
                cwd=temporary,
                capture_output=True,
                text=True,
                check=False,
                timeout=_timeout(),
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HarnessModelAdapterError(f"cannot complete {agent_name}: {exc}") from exc
    limit = _output_limit()
    if (
        len(completed.stdout.encode("utf-8")) > limit
        or len(completed.stderr.encode("utf-8")) > limit
    ):
        raise HarnessModelAdapterError(f"{agent_name} exceeded its output byte limit")
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or f"{agent_name} exited with {completed.returncode}"
        )
        raise HarnessModelAdapterError(detail)
    if completed.stderr:
        raise HarnessModelAdapterError(f"{agent_name} wrote unexpected standard error")
    text, input_tokens, output_tokens = _assistant(completed.stdout, agent_name)
    action = decode_json_object(text, HarnessModelAdapterError)
    return {
        "action": action,
        "protocol_version": 1,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def run_main(*, agent_name: str, command_builder: CommandBuilder) -> int:
    try:
        response = invoke_model(
            sys.stdin.read(), agent_name=agent_name, command_builder=command_builder
        )
    except (HarnessModelAdapterError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0
