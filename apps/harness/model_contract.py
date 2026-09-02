"""Provider-neutral one-shot model transport for the fixed recursive harness."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from apps._support.process import kill_process_tree
from apps._support.wire import canonical_digest, canonical_json, decode_json_object
from apps.agent_protocol import (
    ProtocolError,
    decode_command,
    normalize_json_value,
    require_exact_keys,
    require_sha256,
)
from apps.harness.resources import ResourceObservation, ResourceObserver

MODEL_PROTOCOL_VERSION = 1


class ModelContractError(RuntimeError):
    """Raised when a model transport fails or returns a malformed action."""


@dataclass(frozen=True)
class ModelReply:
    action: dict[str, object]
    input_tokens: int
    output_tokens: int
    observation: ResourceObservation | None = None


def model_request(system_prompt: str, prompt: str) -> dict[str, object]:
    if not system_prompt or "\x00" in system_prompt:
        raise ModelContractError(
            "model system_prompt must be non-empty text without NUL"
        )
    if not prompt or "\x00" in prompt:
        raise ModelContractError("model prompt must be non-empty text without NUL")
    request_id = canonical_digest(
        {
            "model_protocol_version": MODEL_PROTOCOL_VERSION,
            "prompt": prompt,
            "system_prompt": system_prompt,
        }
    )
    return {
        "prompt": prompt,
        "protocol_version": MODEL_PROTOCOL_VERSION,
        "request_id": request_id,
        "system_prompt": system_prompt,
    }


def decode_model_request(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ModelContractError("model request must be a JSON object")
    try:
        require_exact_keys(
            value,
            {"prompt", "protocol_version", "request_id", "system_prompt"},
            "model request",
        )
        if type(value["protocol_version"]) is not int or value["protocol_version"] != 1:
            raise ProtocolError("model request.protocol_version must be 1")
        request_id = require_sha256(value["request_id"], "model request.request_id")
    except ProtocolError as exc:
        raise ModelContractError(str(exc)) from exc
    prompt = value["prompt"]
    system_prompt = value["system_prompt"]
    if type(prompt) is not str or not prompt or "\x00" in prompt:
        raise ModelContractError(
            "model request.prompt must be non-empty text without NUL"
        )
    if type(system_prompt) is not str or not system_prompt or "\x00" in system_prompt:
        raise ModelContractError(
            "model request.system_prompt must be non-empty text without NUL"
        )
    expected = model_request(system_prompt, prompt)
    if request_id != expected["request_id"]:
        raise ModelContractError("model request.request_id does not match its content")
    return expected


def _tokens(value: object, location: str) -> int:
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ModelContractError(f"{location} must be a non-negative integer")
    return value


def decode_model_response(value: object) -> ModelReply:
    if type(value) is not dict:
        raise ModelContractError("model response must be a JSON object")
    try:
        require_exact_keys(
            value, {"action", "protocol_version", "usage"}, "model response"
        )
    except ProtocolError as exc:
        raise ModelContractError(str(exc)) from exc
    if type(value["protocol_version"]) is not int or value["protocol_version"] != 1:
        raise ModelContractError("model response.protocol_version must be 1")
    action = normalize_json_value(value["action"], "model response.action")
    if type(action) is not dict:
        raise ModelContractError("model response.action must be a JSON object")
    usage = value["usage"]
    if type(usage) is not dict:
        raise ModelContractError("model response.usage must be a JSON object")
    try:
        require_exact_keys(
            usage, {"input_tokens", "output_tokens"}, "model response.usage"
        )
    except ProtocolError as exc:
        raise ModelContractError(str(exc)) from exc
    return ModelReply(
        action=action,
        input_tokens=_tokens(
            usage["input_tokens"], "model response.usage.input_tokens"
        ),
        output_tokens=_tokens(
            usage["output_tokens"], "model response.usage.output_tokens"
        ),
    )


class SubprocessModelTransport:
    """Call one reviewed provider connector for every harness turn."""

    def __init__(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
        max_response_bytes: int,
        environment: dict[str, str] | None = None,
    ) -> None:
        try:
            self.command = decode_command(command, "model command")
        except ProtocolError as exc:
            raise ModelContractError(str(exc)) from exc
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600:
            raise ModelContractError(
                "model timeout must be from 1 through 3600 seconds"
            )
        if (
            type(max_response_bytes) is not int
            or not 1024 <= max_response_bytes <= 16_777_216
        ):
            raise ModelContractError(
                "model response limit must be from 1024 through 16777216 bytes"
            )
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.environment = dict(environment or {})

    def call(self, system_prompt: str, prompt: str) -> ModelReply:
        request = model_request(system_prompt, prompt)
        try:
            process = subprocess.Popen(
                self.command,
                cwd=Path(__file__).resolve().parents[2],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                start_new_session=os.name == "posix",
                env={**os.environ, **self.environment},
            )
        except OSError as exc:
            raise ModelContractError(f"cannot start model transport: {exc}") from exc
        observer = ResourceObserver(
            lambda: (
                None
                if process.poll() is not None
                else ("procfs", Path(str(process.pid)))
            )
        )
        try:
            try:
                stdout, stderr = process.communicate(
                    canonical_json(request) + "\n",
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                kill_process_tree(process)
                raise ModelContractError(
                    "model transport exceeded its timeout"
                ) from exc
            except BaseException:
                kill_process_tree(process)
                raise
        finally:
            observation = observer.stop()
        if (
            len(stdout.encode("utf-8")) > self.max_response_bytes
            or len(stderr.encode("utf-8")) > self.max_response_bytes
        ):
            raise ModelContractError("model transport exceeded its response byte limit")
        if process.returncode != 0:
            detail = (
                stderr.strip() or f"model transport exited with {process.returncode}"
            )
            raise ModelContractError(detail)
        if stderr:
            raise ModelContractError("model transport wrote unexpected standard error")
        response = decode_json_object(stdout, ModelContractError)
        reply = decode_model_response(response)
        return ModelReply(
            action=reply.action,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            observation=observation,
        )
