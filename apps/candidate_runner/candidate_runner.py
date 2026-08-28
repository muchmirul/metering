"""Run one fixed candidate model against an Observer probe."""

from __future__ import annotations

import math
import re
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import cast

from metering import ProbabilityError, entropy

ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = Path(__file__).resolve().parents[1]
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from agent_protocol import (  # noqa: E402
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
from stdio_connector import (  # noqa: E402
    canonical_digest,
    canonical_json,
    decode_json_object,
    run_stdio_application,
)

SCHEMA_VERSION = 1
RUNNER_MODEL = "observer-fixture-hypothesis-v1"
MIN_CONFIDENCE_BPS = 2500
MAX_CONFIDENCE_BPS = 10000
VERSIONS = ("v1", "v2", "v3", "v4")
PATHS = ("config/mode.txt", "service/port.txt")
CONTENTS = {
    "v1": {"config/mode.txt": "safe\n", "service/port.txt": "8000\n"},
    "v2": {"config/mode.txt": "safe\n", "service/port.txt": "9000\n"},
    "v3": {"config/mode.txt": "fast\n", "service/port.txt": "8000\n"},
    "v4": {"config/mode.txt": "fast\n", "service/port.txt": "9000\n"},
}
CANDIDATE_ID_PATTERN = re.compile(r"[0-9a-f]{64}")


class RequestError(ValueError):
    """Raised when a runner request violates the application contract."""


def _decode_json(source: str) -> dict[str, object]:
    return decode_json_object(source, RequestError, parse_float=Decimal)


def _require_exact_keys(
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


def _require_nonempty_string(value: object, location: str) -> str:
    if type(value) is not str or not value:
        raise RequestError(f"{location} must be a non-empty string")
    return value


def _decode_genome(raw_genome: object) -> dict[str, object]:
    if type(raw_genome) is not dict:
        raise RequestError("genome must be a JSON object")
    _require_exact_keys(
        raw_genome,
        {"hypothesis", "hypothesis_probability_bps"},
        "genome",
    )
    hypothesis = _require_nonempty_string(
        raw_genome["hypothesis"], "genome.hypothesis"
    )
    if hypothesis not in VERSIONS:
        raise RequestError("genome.hypothesis must be one of: v1, v2, v3, v4")
    confidence = raw_genome["hypothesis_probability_bps"]
    if type(confidence) is not int:
        raise RequestError("genome.hypothesis_probability_bps must be an integer")
    if not MIN_CONFIDENCE_BPS <= confidence <= MAX_CONFIDENCE_BPS:
        raise RequestError(
            "genome.hypothesis_probability_bps must be between "
            f"{MIN_CONFIDENCE_BPS} and {MAX_CONFIDENCE_BPS}"
        )
    return {
        "hypothesis": hypothesis,
        "hypothesis_probability_bps": confidence,
    }


def _decode_probe(raw_probe: object) -> dict[str, str]:
    if type(raw_probe) is not dict:
        raise RequestError("probe must be a JSON object")
    operation = _require_nonempty_string(raw_probe.get("operation"), "probe.operation")
    if operation == "list":
        _require_exact_keys(raw_probe, {"operation"}, "probe")
        return {"operation": "list"}
    if operation == "read":
        _require_exact_keys(raw_probe, {"operation", "path"}, "probe")
        path = _require_nonempty_string(raw_probe["path"], "probe.path")
        if path not in PATHS:
            raise RequestError(
                "probe.path must be one of: config/mode.txt, service/port.txt"
            )
        return {"operation": "read", "path": path}
    raise RequestError("probe.operation must be one of: list, read")


def decode_request(
    source: str,
) -> tuple[str, dict[str, object], dict[str, str]]:
    request = _decode_json(source)
    _require_exact_keys(
        request,
        {"schema_version", "candidate_id", "genome", "probe"},
        "request",
    )
    if (
        type(request["schema_version"]) is not int
        or request["schema_version"] != SCHEMA_VERSION
    ):
        raise RequestError(f"schema_version must be {SCHEMA_VERSION}")
    candidate_id = _require_nonempty_string(
        request["candidate_id"], "candidate_id"
    )
    if CANDIDATE_ID_PATTERN.fullmatch(candidate_id) is None:
        raise RequestError("candidate_id must be a lowercase SHA-256 identifier")
    genome = _decode_genome(request["genome"])
    expected_id = canonical_digest(
        {
            "genome": genome,
            "genome_schema": "flat-json-atoms-v1",
            "schema_version": SCHEMA_VERSION,
        }
    )
    if candidate_id != expected_id:
        raise RequestError("candidate_id does not match the supplied genome")
    probe = _decode_probe(request["probe"])
    return candidate_id, genome, probe


def _result_for(version: str, probe: dict[str, str]) -> dict[str, object]:
    if probe["operation"] == "list":
        return {"kind": "listing", "paths": list(PATHS)}
    return {"kind": "text", "text": CONTENTS[version][probe["path"]]}


def _measurement(value: float) -> dict[str, object]:
    return {
        "base": 2.0,
        "infinite": False,
        "measure": "entropy",
        "value": value,
    }


def run_candidate(
    candidate_id: str,
    genome: dict[str, object],
    probe: dict[str, str],
) -> dict[str, object]:
    hypothesis = str(genome["hypothesis"])
    confidence = int(genome["hypothesis_probability_bps"]) / 10000.0
    other_probability = (1.0 - confidence) / (len(VERSIONS) - 1)
    version_probabilities = {
        version: confidence if version == hypothesis else other_probability
        for version in VERSIONS
    }

    grouped: dict[str, list[float]] = {}
    for version in VERSIONS:
        target = canonical_json(_result_for(version, probe))
        grouped.setdefault(target, []).append(version_probabilities[version])
    outcomes: list[dict[str, object]] = []
    for target in sorted(grouped):
        probability = math.fsum(grouped[target])
        outcomes.append(
            {
                "probability": 0.0 if probability == 0.0 else probability,
                "target": target,
            }
        )
    forecast_entropy = entropy(
        [float(outcome["probability"]) for outcome in outcomes],
        base=2,
    )
    return {
        "candidate_id": candidate_id,
        "forecast": {
            "entropy": _measurement(forecast_entropy),
            "outcomes": outcomes,
        },
        "genome": genome,
        "probe": probe,
        "runner_model": RUNNER_MODEL,
        "schema_version": SCHEMA_VERSION,
    }


def _run_agent_skill(request: dict[str, object]) -> dict[str, object]:
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


def _process(source: str) -> dict[str, object]:
    request = _decode_json(source)
    if request.get("schema_version") == AGENT_SCHEMA_VERSION:
        return _run_agent_skill(request)
    candidate_id, genome, probe = decode_request(source)
    return run_candidate(candidate_id, genome, probe)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        _process,
        arguments,
        error_rules=(
            (RequestError, "invalid_request"),
            (ProbabilityError, "invalid_probability"),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
