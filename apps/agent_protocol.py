"""Shared version 2 contracts for agent-artifact application examples.

This module is source-only application support. It is not part of the installed
``metering`` package. The public integration boundary remains canonical JSON
through the application commands under ``apps/``.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import TypedDict, cast

from apps._support.process import (
    JsonProcessError,
    run_json_process,
)
from apps._support.wire import (
    canonical_digest,
    canonical_json,
    strict_json_float,
)

SKILL_ARTIFACT_SCHEMA = "agent-skill-v1"
DEFAULT_ARTIFACT_SCHEMA = "agent-default-v1"
GIT_ARTIFACT_SCHEMA = "git-candidate-v1"
CANDIDATE_SCHEMA = "agent-candidate-v1"
ADAPTER_PROTOCOL_VERSION = 1
GIT_ADAPTER_PROTOCOL_VERSION = 2
AGENT_SCHEMA_VERSION = 2
SHA256_LENGTH = 64

# Public protocol name retained for artifact and command identities.
digest = canonical_digest


class ProtocolError(ValueError):
    """Raised when a version 2 artifact or adapter violates its contract."""


class ArtifactFile(TypedDict):
    content: str
    executable: bool
    path: str


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
        raise ProtocolError(f"{location}: {'; '.join(details)}")


def _require_utf8(value: str, location: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ProtocolError(f"{location} must be valid UTF-8") from error
    return value


def require_nonempty_string(value: object, location: str) -> str:
    if type(value) is not str or not value:
        raise ProtocolError(f"{location} must be a non-empty string")
    _require_utf8(value, location)
    if "\x00" in value:
        raise ProtocolError(f"{location} must not contain NUL")
    return value


def require_sha256(value: object, location: str) -> str:
    identifier = require_nonempty_string(value, location)
    if len(identifier) != SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in identifier
    ):
        raise ProtocolError(f"{location} must be a lowercase SHA-256 identifier")
    return identifier


def require_bool(value: object, location: str) -> bool:
    if type(value) is not bool:
        raise ProtocolError(f"{location} must be a boolean")
    return value


def require_timeout(value: object, location: str) -> int:
    if type(value) is not int or not 1 <= value <= 3600:
        raise ProtocolError(f"{location} must be an integer from 1 through 3600")
    return value


def require_schema_version(value: object, location: str = "schema_version") -> None:
    if type(value) is not int or value != AGENT_SCHEMA_VERSION:
        raise ProtocolError(f"{location} must be {AGENT_SCHEMA_VERSION}")


def decode_command(value: object, location: str) -> list[str]:
    if type(value) is not list or not value:
        raise ProtocolError(f"{location} must be a non-empty JSON string array")
    command: list[str] = []
    for index, item in enumerate(value):
        command.append(require_nonempty_string(item, f"{location}[{index}]"))
    return command


def _normalized_artifact_path(value: object, location: str) -> str:
    path = require_nonempty_string(value, location)
    candidate = PurePosixPath(path)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != path
        or "\\" in path
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ProtocolError(f"{location} must be a normalized relative POSIX path")
    return path


def _git_object_id(value: object, location: str) -> str:
    identifier = require_nonempty_string(value, location)
    if len(identifier) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in identifier
    ):
        raise ProtocolError(f"{location} must be a lowercase Git object ID")
    return identifier


def _decode_git_output(value: object, location: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(value, {"kind", "name", "sha256", "uri"}, location)
    return {
        "kind": require_nonempty_string(value["kind"], f"{location}.kind"),
        "name": require_nonempty_string(value["name"], f"{location}.name"),
        "sha256": require_sha256(value["sha256"], f"{location}.sha256"),
        "uri": require_nonempty_string(value["uri"], f"{location}.uri"),
    }


def _decode_git_artifact(value: dict[str, object], location: str) -> dict[str, object]:
    require_exact_keys(
        value,
        {
            "artifact_schema",
            "commit",
            "content_sha256",
            "entrypoint",
            "git_tree",
            "outputs",
            "repository",
        },
        location,
    )
    raw_outputs = value["outputs"]
    if type(raw_outputs) is not list:
        raise ProtocolError(f"{location}.outputs must be a JSON array")
    outputs: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_output in enumerate(raw_outputs):
        output = _decode_git_output(raw_output, f"{location}.outputs[{index}]")
        identity = (str(output["kind"]), str(output["name"]))
        if identity in seen:
            raise ProtocolError(
                f"{location}.outputs contains duplicate kind and name: "
                f"{identity[0]}/{identity[1]}"
            )
        seen.add(identity)
        outputs.append(output)
    outputs.sort(key=lambda item: (str(item["kind"]), str(item["name"])))
    return {
        "artifact_schema": GIT_ARTIFACT_SCHEMA,
        "commit": _git_object_id(value["commit"], f"{location}.commit"),
        "content_sha256": require_sha256(
            value["content_sha256"], f"{location}.content_sha256"
        ),
        "entrypoint": _normalized_artifact_path(
            value["entrypoint"], f"{location}.entrypoint"
        ),
        "git_tree": _git_object_id(value["git_tree"], f"{location}.git_tree"),
        "outputs": outputs,
        "repository": require_nonempty_string(
            value["repository"], f"{location}.repository"
        ),
    }


def decode_agent_artifact(
    value: object, location: str = "artifact"
) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    schema = value.get("artifact_schema")
    if schema == DEFAULT_ARTIFACT_SCHEMA:
        require_exact_keys(value, {"artifact_schema"}, location)
        return {"artifact_schema": DEFAULT_ARTIFACT_SCHEMA}
    if schema == GIT_ARTIFACT_SCHEMA:
        return _decode_git_artifact(value, location)
    if schema != SKILL_ARTIFACT_SCHEMA:
        raise ProtocolError(
            f"{location}.artifact_schema must be {DEFAULT_ARTIFACT_SCHEMA}, "
            f"{SKILL_ARTIFACT_SCHEMA}, or {GIT_ARTIFACT_SCHEMA}"
        )
    require_exact_keys(value, {"artifact_schema", "files"}, location)
    raw_files = value["files"]
    if type(raw_files) is not list or not raw_files:
        raise ProtocolError(f"{location}.files must be a non-empty JSON array")

    files: list[ArtifactFile] = []
    seen: set[str] = set()
    for index, raw_file in enumerate(raw_files):
        file_location = f"{location}.files[{index}]"
        if type(raw_file) is not dict:
            raise ProtocolError(f"{file_location} must be a JSON object")
        require_exact_keys(raw_file, {"content", "executable", "path"}, file_location)
        path = _normalized_artifact_path(raw_file["path"], f"{file_location}.path")
        if path in seen:
            raise ProtocolError(f"{location}.files contains duplicate path: {path}")
        seen.add(path)
        content = raw_file["content"]
        if type(content) is not str:
            raise ProtocolError(f"{file_location}.content must be a UTF-8 string")
        _require_utf8(content, f"{file_location}.content")
        executable = require_bool(raw_file["executable"], f"{file_location}.executable")
        files.append({"content": content, "executable": executable, "path": path})

    if "SKILL.md" not in seen:
        raise ProtocolError(f"{location}.files must contain SKILL.md")
    skill_text = next(item["content"] for item in files if item["path"] == "SKILL.md")
    if not skill_text:
        raise ProtocolError(f"{location} SKILL.md must not be empty")
    files.sort(key=lambda item: item["path"])
    return {"artifact_schema": SKILL_ARTIFACT_SCHEMA, "files": files}


def candidate_record(artifact: object, location: str = "artifact") -> dict[str, object]:
    normalized = decode_agent_artifact(artifact, location)
    candidate_id = digest(
        {"artifact": normalized, "candidate_schema": CANDIDATE_SCHEMA}
    )
    return {"artifact": normalized, "candidate_id": candidate_id}


def decode_candidate(value: object, location: str = "candidate") -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(value, {"artifact", "candidate_id"}, location)
    supplied_id = require_sha256(value["candidate_id"], f"{location}.candidate_id")
    record = candidate_record(value["artifact"], f"{location}.artifact")
    if supplied_id != record["candidate_id"]:
        raise ProtocolError(
            f"{location}.candidate_id does not match the supplied artifact"
        )
    return record


def _artifact_file_map(
    candidate: dict[str, object],
) -> dict[str, tuple[object, object]]:
    artifact = cast(dict[str, object], candidate["artifact"])
    files = cast(list[ArtifactFile], artifact.get("files", []))
    return {item["path"]: (item["content"], item["executable"]) for item in files}


def changed_artifact_paths(
    parent: dict[str, object], challenger: dict[str, object]
) -> list[str]:
    parent_artifact = cast(dict[str, object], parent["artifact"])
    challenger_artifact = cast(dict[str, object], challenger["artifact"])
    if (
        parent_artifact.get("artifact_schema") == GIT_ARTIFACT_SCHEMA
        or challenger_artifact.get("artifact_schema") == GIT_ARTIFACT_SCHEMA
    ):
        return [] if parent_artifact == challenger_artifact else ["@git-candidate"]
    parent_files = _artifact_file_map(parent)
    challenger_files = _artifact_file_map(challenger)
    return sorted(
        path
        for path in set(parent_files) | set(challenger_files)
        if parent_files.get(path) != challenger_files.get(path)
    )


def materialize_skill(artifact: dict[str, object], root: Path) -> None:
    if artifact.get("artifact_schema") != SKILL_ARTIFACT_SCHEMA:
        raise ProtocolError("only an agent-skill-v1 artifact can be materialized")
    root.mkdir(parents=True, exist_ok=False)
    files = cast(list[ArtifactFile], artifact["files"])
    for item in files:
        path = root / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item["content"], encoding="utf-8", newline="")
        path.chmod(0o755 if item["executable"] else 0o644)


def _unique_adapter_object(
    name: str, pairs: list[tuple[str, object]]
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"{name} returned duplicate key: {key}")
        result[key] = value
    return result


def _reject_adapter_nonfinite(name: str, token: str) -> object:
    raise ProtocolError(f"{name} returned a non-finite number: {token}")


def decode_adapter_output(name: str, source: str) -> dict[str, object]:
    try:
        document = json.loads(
            source,
            object_pairs_hook=lambda pairs: _unique_adapter_object(name, pairs),
            parse_constant=lambda token: _reject_adapter_nonfinite(name, token),
            parse_float=strict_json_float,
        )
    except ProtocolError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProtocolError(f"{name} returned invalid JSON: {exc}") from exc
    if type(document) is not dict:
        raise ProtocolError(f"{name} response must be one JSON object")
    try:
        canonical_json(document)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"{name} returned unsupported JSON values") from exc
    return document


def run_adapter(
    name: str,
    command: list[str],
    request: dict[str, object],
    *,
    timeout_seconds: int,
    cwd: Path,
) -> dict[str, object]:
    try:
        source = run_json_process(
            command,
            request,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )
    except JsonProcessError as error:
        if error.kind == "timeout":
            message = f"{name} exceeded its timeout"
        elif error.kind == "start":
            message = f"cannot start {name}: {error.detail}"
        elif error.kind == "exit":
            detail = error.stderr.strip() or f"exit status {error.returncode}"
            message = f"{name} failed: {detail}"
        else:
            message = f"{name} wrote unexpected standard error"
        raise ProtocolError(message) from error
    return decode_adapter_output(name, source)


def normalize_json_value(value: object, location: str = "value") -> object:
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is str:
        return _require_utf8(value, location)
    if isinstance(value, (float, Decimal)):
        try:
            converted = float(value)
        except (OverflowError, ValueError) as exc:
            raise ProtocolError(
                f"{location} is outside the finite double range"
            ) from exc
        if not math.isfinite(converted):
            raise ProtocolError(f"{location} is outside the finite double range")
        return 0.0 if converted == 0.0 else converted
    if type(value) is list:
        return [
            normalize_json_value(item, f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) is dict:
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ProtocolError(f"{location} contains a non-string object key")
            _require_utf8(key, f"{location} object key")
            normalized[key] = normalize_json_value(item, f"{location}.{key}")
        return normalized
    raise ProtocolError(f"{location} contains an unsupported JSON value")


def finite_number(value: object, location: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float, Decimal)):
        raise ProtocolError(f"{location} must be a finite JSON number")
    try:
        converted = float(value)
    except (OverflowError, ValueError) as exc:
        raise ProtocolError(f"{location} must be a finite JSON number") from exc
    if not math.isfinite(converted):
        raise ProtocolError(f"{location} must be a finite JSON number")
    return 0.0 if converted == 0.0 else converted


def probability(value: object, location: str) -> float:
    converted = finite_number(value, location)
    if not 0.0 <= converted <= 1.0:
        raise ProtocolError(f"{location} must be between 0 and 1")
    return converted


def decode_task(value: object, location: str = "task") -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(value, {"case_id", "input"}, location)
    return {
        "case_id": require_nonempty_string(value["case_id"], f"{location}.case_id"),
        "input": normalize_json_value(value["input"], f"{location}.input"),
    }


def decode_forecast_outcomes(
    value: object, location: str = "forecast.outcomes"
) -> list[dict[str, object]]:
    if type(value) is not list or not value:
        raise ProtocolError(f"{location} must be a non-empty JSON array")

    outcomes: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw_outcome in enumerate(value):
        outcome_location = f"{location}[{index}]"
        if type(raw_outcome) is not dict:
            raise ProtocolError(f"{outcome_location} must be a JSON object")
        require_exact_keys(raw_outcome, {"outcome", "probability"}, outcome_location)
        outcome = require_nonempty_string(
            raw_outcome["outcome"], f"{outcome_location}.outcome"
        )
        if outcome in seen:
            raise ProtocolError(f"duplicate forecast outcome: {outcome}")
        seen.add(outcome)
        outcomes.append(
            {
                "outcome": outcome,
                "probability": probability(
                    raw_outcome["probability"],
                    f"{outcome_location}.probability",
                ),
            }
        )
    outcomes.sort(key=lambda item: str(item["outcome"]))
    return outcomes


def decode_forecast(value: object, location: str = "forecast") -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(value, {"entropy", "outcomes"}, location)

    entropy = value["entropy"]
    entropy_location = f"{location}.entropy"
    if type(entropy) is not dict:
        raise ProtocolError(f"{entropy_location} must be a JSON object")
    require_exact_keys(
        entropy, {"base", "infinite", "measure", "value"}, entropy_location
    )
    base = finite_number(entropy["base"], f"{entropy_location}.base")
    if base != 2.0:
        raise ProtocolError(f"{entropy_location}.base must be 2")
    if entropy["measure"] != "entropy":
        raise ProtocolError(f"{entropy_location}.measure must be entropy")
    if require_bool(entropy["infinite"], f"{entropy_location}.infinite"):
        raise ProtocolError(f"{entropy_location}.infinite must be false")
    entropy_value = finite_number(entropy["value"], f"{entropy_location}.value")
    if entropy_value < 0.0:
        raise ProtocolError(f"{entropy_location}.value must be non-negative")

    return {
        "entropy": {
            "base": base,
            "infinite": False,
            "measure": "entropy",
            "value": entropy_value,
        },
        "outcomes": decode_forecast_outcomes(value["outcomes"], f"{location}.outcomes"),
    }


def decode_candidate_run(
    value: object, location: str = "candidate run"
) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(
        value,
        {"candidate_id", "forecast", "runner", "schema_version", "task"},
        location,
    )
    require_schema_version(value["schema_version"], f"{location}.schema_version")

    runner = value["runner"]
    runner_location = f"{location}.runner"
    if type(runner) is not dict:
        raise ProtocolError(f"{runner_location} must be a JSON object")
    require_exact_keys(runner, {"adapter_id", "submission"}, runner_location)

    return {
        "candidate_id": require_sha256(
            value["candidate_id"], f"{location}.candidate_id"
        ),
        "forecast": decode_forecast(value["forecast"], f"{location}.forecast"),
        "runner": {
            "adapter_id": require_sha256(
                runner["adapter_id"], f"{runner_location}.adapter_id"
            ),
            "submission": normalize_json_value(
                runner["submission"], f"{runner_location}.submission"
            ),
        },
        "schema_version": AGENT_SCHEMA_VERSION,
        "task": decode_task(value["task"], f"{location}.task"),
    }


def decode_evaluator_result(
    value: object, location: str = "evaluator result"
) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(
        value,
        {"candidate_id", "evidence", "outcome", "passed", "safety_passed"},
        location,
    )
    return {
        "candidate_id": require_sha256(
            value["candidate_id"], f"{location}.candidate_id"
        ),
        "evidence": normalize_json_value(value["evidence"], f"{location}.evidence"),
        "outcome": require_nonempty_string(value["outcome"], f"{location}.outcome"),
        "passed": require_bool(value["passed"], f"{location}.passed"),
        "safety_passed": require_bool(
            value["safety_passed"], f"{location}.safety_passed"
        ),
    }


def decode_observer_evaluation(
    value: object, location: str = "observer evaluation"
) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(
        value,
        {
            "case_id",
            "evaluation",
            "evaluator_id",
            "results",
            "schema_version",
        },
        location,
    )
    require_schema_version(value["schema_version"], f"{location}.schema_version")
    raw_results = value["results"]
    if type(raw_results) is not list or len(raw_results) != 2:
        raise ProtocolError(f"{location}.results must contain exactly two results")
    results = [
        decode_evaluator_result(result, f"{location}.results[{index}]")
        for index, result in enumerate(raw_results)
    ]
    candidate_ids = [str(result["candidate_id"]) for result in results]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ProtocolError(f"{location}.results contains a duplicate candidate ID")
    results.sort(key=lambda item: str(item["candidate_id"]))
    return {
        "case_id": require_nonempty_string(value["case_id"], f"{location}.case_id"),
        "evaluation": require_nonempty_string(
            value["evaluation"], f"{location}.evaluation"
        ),
        "evaluator_id": require_sha256(
            value["evaluator_id"], f"{location}.evaluator_id"
        ),
        "results": results,
        "schema_version": AGENT_SCHEMA_VERSION,
    }
