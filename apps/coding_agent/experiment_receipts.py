"""Read-only solution execution and retry receipt validation."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import cast

from apps._support.wire import canonical_digest, canonical_json, decode_json_object
from apps.coding_agent.experiment_artifacts import canonical_document
from apps.coding_agent.experiment_config import (
    EVALUATOR,
    SolutionExperimentError,
    control_python_executable,
)
from apps.coding_agent.solution_evaluator import validate_evaluation_receipt
from apps.harness.runtime_manifest import RuntimeManifest
from apps.population.contract import RESOURCE_NAMES


def receipt_files(
    root: Path, schema: str, *, schema_key: str = "receipt_schema"
) -> dict[str, dict[str, object]]:
    if root.is_symlink() or not root.is_dir():
        raise SolutionExperimentError(f"receipt directory is absent or unsafe: {root}")
    receipts: dict[str, dict[str, object]] = {}
    for path in sorted(root.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise SolutionExperimentError("receipt directory contains an unsafe entry")
        source = path.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        if path.name != f"{digest}.json":
            raise SolutionExperimentError("receipt filename does not match content")
        document = decode_json_object(source.decode("ascii"), SolutionExperimentError)
        if source.decode("ascii") != canonical_json(document) + "\n":
            raise SolutionExperimentError("receipt is not canonical")
        if document.get(schema_key) != schema:
            raise SolutionExperimentError("receipt schema is unexpected")
        receipts[digest] = document
    return receipts


def verify_bound_evaluation_receipt(
    receipt: dict[str, object],
    *,
    candidate_id: str,
    candidate_content_sha256: object,
    workspace_sha256: str,
    task: dict[str, object],
    runtime: RuntimeManifest,
) -> dict[str, object]:
    execution = validate_evaluation_receipt(
        receipt,
        candidate_id=candidate_id,
        task=task,
        runtime_id=runtime.runtime_id,
    )
    task_input = cast(dict[str, object], task["input"])
    observations = receipt["kernel_observations"]
    if (
        receipt["candidate_content_sha256"] != candidate_content_sha256
        or receipt["workspace_sha256"] != workspace_sha256
        or receipt["assay"] != task_input["assay"]
        or receipt["isolation_enforced"] is not runtime.isolation_enforced
        or type(observations) is not list
        or not observations
    ):
        raise SolutionExperimentError("coding evaluation receipt changed execution")
    observation_keys = {
        "cpu_microseconds",
        "memory_peak_bytes",
        "processes_peak",
        "source",
        "storage_write_bytes",
        "wall_milliseconds",
    }
    normalized_observations: list[dict[str, object]] = []
    for raw in observations:
        if type(raw) is not dict or set(raw) != observation_keys:
            raise SolutionExperimentError("coding kernel observation is malformed")
        for name in (
            "cpu_microseconds",
            "memory_peak_bytes",
            "processes_peak",
            "storage_write_bytes",
        ):
            value = raw[name]
            if value is not None and (type(value) is not int or value < 0):
                raise SolutionExperimentError("coding kernel observation is malformed")
        if (
            type(raw["wall_milliseconds"]) is not int
            or raw["wall_milliseconds"] < 0
            or type(raw["source"]) is not str
            or not raw["source"]
        ):
            raise SolutionExperimentError("coding kernel observation is malformed")
        if runtime.isolation_enforced:
            required = {
                "cpu": "cpu_microseconds",
                "memory": "memory_peak_bytes",
                "processes": "processes_peak",
                "storage": "storage_write_bytes",
                "wall": "wall_milliseconds",
            }
            if raw["source"] != "cgroup-v2" or any(
                raw[required[name]] is None for name in runtime.required_observations
            ):
                raise SolutionExperimentError(
                    "coding kernel observation omitted required isolation evidence"
                )
        normalized_observations.append(raw)
    if runtime.cost_mode == "deterministic-fixture-v1":
        expected_cost = {name: 0 for name in RESOURCE_NAMES}
    else:
        expected_cost = {
            "actions": 1,
            "energy_millijoules": 0,
            "gpu_milliseconds": 0,
            "memory_bytes": max(
                int(item["memory_peak_bytes"] or 0) for item in normalized_observations
            ),
            "storage_bytes": sum(
                int(item["storage_write_bytes"] or 0)
                for item in normalized_observations
            ),
            "tokens": 0,
            "wall_milliseconds": sum(
                int(item["wall_milliseconds"]) for item in normalized_observations
            ),
        }
    if receipt["cost"] != expected_cost:
        raise SolutionExperimentError("coding evaluation receipt cost does not replay")
    return execution


def verified_recorded_evaluator_command(
    generation: dict[str, object],
) -> list[str]:
    evaluator = generation.get("evaluator")
    if type(evaluator) is not dict:
        raise SolutionExperimentError("coding evaluator configuration is malformed")
    command = evaluator.get("command")
    if (
        type(command) is not list
        or len(command) != 2
        or any(type(item) is not str or not item for item in command)
        or command[1] != str(EVALUATOR)
    ):
        raise SolutionExperimentError("coding evaluator command changed")
    executable = Path(cast(str, command[0]))
    if not executable.is_absolute():
        raise SolutionExperimentError("coding evaluator executable is not absolute")
    try:
        if executable.resolve(strict=True) != Path(sys.executable).resolve(strict=True):
            raise SolutionExperimentError("coding evaluator interpreter changed")
    except OSError as exc:
        raise SolutionExperimentError(
            "coding evaluator interpreter is unavailable"
        ) from exc
    return cast(list[str], command)


def equivalent_evaluator_ids(recorded_command: list[str]) -> set[str]:
    expected = Path(recorded_command[0]).resolve(strict=True)
    candidates = {
        Path(recorded_command[0]),
        Path(sys.executable),
        Path(control_python_executable()),
    }
    bin_directory = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
    if bin_directory.is_dir():
        candidates.update(list(bin_directory.glob("python*"))[:32])
    commands = []
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.resolve(strict=True) == expected:
                commands.append([str(candidate.absolute()), str(EVALUATOR)])
        except OSError:
            continue
    return {canonical_digest({"command": command}) for command in commands}


def retry_effect_receipts(
    root: Path, driver_lines: list[str]
) -> tuple[set[str], set[str]]:
    expected: dict[str, tuple[str, str]] = {}
    for line in driver_lines[1:]:
        record = decode_json_object(line, SolutionExperimentError)
        attempts = record.get("attempts")
        intent_id = record.get("intent_id")
        if type(attempts) is not list or type(intent_id) is not str:
            raise SolutionExperimentError("coding Driver retry attempts are malformed")
        for index, attempt in enumerate(attempts[:-1]):
            next_attempt = attempts[index + 1]
            if (
                type(attempt) is not dict
                or type(attempt.get("attempt_id")) is not str
                or type(next_attempt) is not dict
                or type(next_attempt.get("reason")) is not str
            ):
                raise SolutionExperimentError(
                    "coding Driver retry attempt is malformed"
                )
            expected[str(attempt["attempt_id"])] = (
                intent_id,
                str(next_attempt["reason"]),
            )
    retry_root = root / "state" / "retry-effects"
    actual: set[str] = set()
    mutation: set[str] = set()
    evaluation: set[str] = set()
    if retry_root.exists():
        if retry_root.is_symlink() or not retry_root.is_dir():
            raise SolutionExperimentError("coding retry-effects directory is unsafe")
        for path in sorted(retry_root.iterdir()):
            document = canonical_document(path, "coding retry-effects receipt")
            if set(document) != {
                "attempt_id",
                "evaluation_receipt_sha256",
                "intent_id",
                "mutation_receipt_sha256",
                "retry_effects_schema",
            }:
                raise SolutionExperimentError(
                    "coding retry-effects receipt is malformed"
                )
            attempt_id = document["attempt_id"]
            mutation_values = document["mutation_receipt_sha256"]
            evaluation_values = document["evaluation_receipt_sha256"]
            schema = document["retry_effects_schema"]
            lists = (mutation_values, evaluation_values)
            expected_identity = expected.get(cast(str, attempt_id))
            if (
                type(schema) is not str
                or schema
                not in {
                    "darwinian-coding-retry-effects-v1",
                    "darwinian-coding-retry-effects-v2",
                }
                or type(attempt_id) is not str
                or path.name != f"{attempt_id}.json"
                or expected_identity is None
                or expected_identity[0] != document["intent_id"]
                or any(
                    type(values) is not list
                    or values != sorted(set(values))
                    or any(
                        type(digest) is not str
                        or len(digest) != 64
                        or any(
                            character not in "0123456789abcdef" for character in digest
                        )
                        for digest in values
                    )
                    for values in lists
                )
            ):
                raise SolutionExperimentError(
                    "coding retry-effects identity is malformed"
                )
            marker = "\nretry-effects-sha256:"
            if schema == "darwinian-coding-retry-effects-v2":
                source = path.read_bytes()
                receipt_id = hashlib.sha256(source).hexdigest()
                suffix = f"{marker}{receipt_id}"
                if (
                    not expected_identity[1].endswith(suffix)
                    or not expected_identity[1][: -len(suffix)].strip()
                ):
                    raise SolutionExperimentError(
                        "coding retry-effects receipt is not bound to retry"
                    )
            elif marker in expected_identity[1]:
                raise SolutionExperimentError(
                    "coding retry-effects schema was downgraded"
                )
            actual.add(attempt_id)
            mutation.update(cast(list[str], mutation_values))
            evaluation.update(cast(list[str], evaluation_values))
    if actual != set(expected):
        raise SolutionExperimentError("coding retry-effects receipt set is incomplete")
    return mutation, evaluation
