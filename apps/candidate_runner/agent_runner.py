"""Schema-v2 external agent candidate instruction."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import cast

from metering import ProbabilityError, entropy

from apps.agent_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    AGENT_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_SCHEMA,
    GIT_ADAPTER_PROTOCOL_VERSION,
    GIT_ARTIFACT_SCHEMA,
    ProtocolError,
    decode_candidate,
    decode_command,
    decode_forecast_outcomes,
    decode_task,
    materialize_skill,
    normalize_json_value,
    require_exact_keys,
    require_schema_version,
    require_timeout,
    run_adapter,
)
from apps._support.wire import (
    canonical_digest,
    canonical_json,
)

ROOT = Path(__file__).resolve().parents[2]


class RequestError(ValueError):
    """Raised when an agent runner request violates its contract."""


def _measurement(value: float) -> dict[str, object]:
    return {
        "base": 2.0,
        "infinite": False,
        "measure": "entropy",
        "value": value,
    }


def run_agent_candidate(request: dict[str, object]) -> dict[str, object]:
    try:
        require_exact_keys(
            request,
            {
                "schema_version",
                "candidate",
                "task",
                "adapter_command",
                "timeout_seconds",
            },
            "schema_version 2 request",
        )
        require_schema_version(request["schema_version"])
        candidate = decode_candidate(request["candidate"])
        command = decode_command(request["adapter_command"], "adapter_command")
        timeout = require_timeout(request["timeout_seconds"], "timeout_seconds")
        task = decode_task(request["task"])
        canonical_json(task)
    except (ProtocolError, TypeError, ValueError) as exc:
        raise RequestError(str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="metering-agent-skill-") as temp:
        artifact = cast(dict[str, object], candidate["artifact"])
        if artifact["artifact_schema"] == GIT_ARTIFACT_SCHEMA:
            adapter_request = {
                "candidate": {
                    "artifact": artifact,
                    "candidate_id": candidate["candidate_id"],
                },
                "protocol_version": GIT_ADAPTER_PROTOCOL_VERSION,
                "task": task,
            }
        else:
            if artifact["artifact_schema"] == DEFAULT_ARTIFACT_SCHEMA:
                skill_path: str | None = None
            else:
                skill_root = Path(temp) / "skill"
                materialize_skill(artifact, skill_root)
                skill_path = str(skill_root)
            adapter_request = {
                "candidate": {
                    "candidate_id": candidate["candidate_id"],
                    "skill_path": skill_path,
                },
                "protocol_version": ADAPTER_PROTOCOL_VERSION,
                "task": task,
            }
        try:
            adapter_response = run_adapter(
                "candidate adapter",
                command,
                adapter_request,
                timeout_seconds=timeout,
                cwd=ROOT,
            )
        except ProtocolError as exc:
            raise RequestError(str(exc)) from exc

    try:
        require_exact_keys(
            adapter_response, {"forecast", "submission"}, "adapter response"
        )
        forecast = adapter_response["forecast"]
        if type(forecast) is not dict:
            raise ProtocolError("adapter response.forecast must be a JSON object")
        require_exact_keys(forecast, {"outcomes"}, "adapter response.forecast")
        outcomes = decode_forecast_outcomes(
            forecast["outcomes"], "adapter response.forecast.outcomes"
        )
        probabilities = [float(item["probability"]) for item in outcomes]
        forecast_entropy = entropy(probabilities, base=2)
        submission = normalize_json_value(
            adapter_response["submission"], "adapter response.submission"
        )
        canonical_json(submission)
    except (ProtocolError, ProbabilityError, TypeError, ValueError) as exc:
        if isinstance(exc, ProbabilityError):
            raise
        raise RequestError(str(exc)) from exc

    return {
        "candidate_id": candidate["candidate_id"],
        "forecast": {
            "entropy": _measurement(forecast_entropy),
            "outcomes": outcomes,
        },
        "runner": {
            "adapter_id": canonical_digest({"command": command}),
            "submission": submission,
        },
        "schema_version": AGENT_SCHEMA_VERSION,
        "task": task,
    }
