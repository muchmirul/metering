"""Canonical runtime identities and reviewed isolation profiles for harness runs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from apps._support.wire import canonical_digest, canonical_json, decode_json_object
from apps.agent_protocol import ProtocolError, require_exact_keys, require_sha256

RUNTIME_SCHEMA = "evolutionary-harness-runtime-v1"
RUNTIME_SCHEMA_VERSION = 1
OBSERVATIONS = ("cpu", "memory", "processes", "storage", "wall")
_IMAGE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")


class RuntimeManifestError(ValueError):
    """Raised when a runtime profile is malformed or incompatible."""


@dataclass(frozen=True)
class KernelLimits:
    cpu_millis: int
    memory_bytes: int
    pids: int
    storage_bytes: int
    tmpfs_bytes: int
    wall_milliseconds: int


@dataclass(frozen=True)
class RuntimeManifest:
    document: dict[str, object]
    runtime_id: str
    path: Path
    kind: Literal["oci-v1", "process-fixture-v1"]
    command: tuple[str, ...]
    engine: str | None
    image: str | None
    limits: KernelLimits
    required_observations: tuple[str, ...]
    cost_mode: Literal["observed-v1", "deterministic-fixture-v1"]
    max_model_calls: int
    max_output_bytes: int
    model_timeout_seconds: int
    model: dict[str, str]
    supported_dependency_locks: tuple[str, ...]

    @property
    def isolation_enforced(self) -> bool:
        return self.kind == "oci-v1"


def _integer(value: object, location: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise RuntimeManifestError(
            f"{location} must be an integer from {minimum} through {maximum}"
        )
    return value


def _string(value: object, location: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise RuntimeManifestError(f"{location} must be a non-empty string without NUL")
    return value


def _command(value: object, location: str) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise RuntimeManifestError(f"{location} must be a non-empty string array")
    return tuple(
        _string(item, f"{location}[{index}]") for index, item in enumerate(value)
    )


def _limits(value: object) -> tuple[dict[str, int], KernelLimits]:
    location = "runtime.kernel.limits"
    if type(value) is not dict:
        raise RuntimeManifestError(f"{location} must be a JSON object")
    try:
        require_exact_keys(
            value,
            {
                "cpu_millis",
                "memory_bytes",
                "pids",
                "storage_bytes",
                "tmpfs_bytes",
                "wall_milliseconds",
            },
            location,
        )
    except ProtocolError as exc:
        raise RuntimeManifestError(str(exc)) from exc
    normalized = {
        "cpu_millis": _integer(
            value["cpu_millis"], f"{location}.cpu_millis", 100, 64_000
        ),
        "memory_bytes": _integer(
            value["memory_bytes"],
            f"{location}.memory_bytes",
            16_777_216,
            1_099_511_627_776,
        ),
        "pids": _integer(value["pids"], f"{location}.pids", 1, 4096),
        "storage_bytes": _integer(
            value["storage_bytes"],
            f"{location}.storage_bytes",
            1_048_576,
            1_099_511_627_776,
        ),
        "tmpfs_bytes": _integer(
            value["tmpfs_bytes"],
            f"{location}.tmpfs_bytes",
            1_048_576,
            1_099_511_627_776,
        ),
        "wall_milliseconds": _integer(
            value["wall_milliseconds"], f"{location}.wall_milliseconds", 100, 3_600_000
        ),
    }
    if normalized["tmpfs_bytes"] > normalized["storage_bytes"]:
        raise RuntimeManifestError(
            "runtime.kernel.limits.tmpfs_bytes exceeds storage_bytes"
        )
    return normalized, KernelLimits(**normalized)


def _observations(value: object) -> tuple[list[str], tuple[str, ...]]:
    location = "runtime.kernel.required_observations"
    if type(value) is not list or not value:
        raise RuntimeManifestError(f"{location} must be a non-empty array")
    observations: list[str] = []
    for index, item in enumerate(value):
        if type(item) is not str or item not in OBSERVATIONS or item in observations:
            raise RuntimeManifestError(
                f"{location}[{index}] is unsupported or duplicated"
            )
        observations.append(item)
    if observations != sorted(observations):
        raise RuntimeManifestError(f"{location} must be sorted")
    return observations, tuple(observations)


def _kernel(value: object) -> tuple[dict[str, object], dict[str, object]]:
    location = "runtime.kernel"
    if type(value) is not dict:
        raise RuntimeManifestError(f"{location} must be a JSON object")
    kind = value.get("kind")
    common = {"command", "kind", "limits", "required_observations"}
    try:
        if kind == "process-fixture-v1":
            require_exact_keys(value, common, location)
        elif kind == "oci-v1":
            require_exact_keys(value, common | {"engine", "image"}, location)
        else:
            raise RuntimeManifestError(
                f"{location}.kind must be oci-v1 or process-fixture-v1"
            )
    except ProtocolError as exc:
        raise RuntimeManifestError(str(exc)) from exc
    command = _command(value["command"], f"{location}.command")
    normalized_limits, limits = _limits(value["limits"])
    normalized_observations, observations = _observations(
        value["required_observations"]
    )
    normalized: dict[str, object] = {
        "command": list(command),
        "kind": kind,
        "limits": normalized_limits,
        "required_observations": normalized_observations,
    }
    engine: str | None = None
    image: str | None = None
    if kind == "oci-v1":
        engine = _string(value["engine"], f"{location}.engine")
        if engine != "docker-v1":
            raise RuntimeManifestError(f"{location}.engine must be docker-v1")
        image = _string(value["image"], f"{location}.image")
        if _IMAGE.fullmatch(image) is None:
            raise RuntimeManifestError(
                f"{location}.image must include an immutable sha256 digest"
            )
        if set(observations) != set(OBSERVATIONS):
            raise RuntimeManifestError(
                "oci-v1 requires cpu, memory, processes, storage, and wall observations"
            )
        normalized.update({"engine": engine, "image": image})
    return normalized, {
        "command": command,
        "engine": engine,
        "image": image,
        "kind": kind,
        "limits": limits,
        "observations": observations,
    }


def _model(value: object) -> dict[str, str]:
    location = "runtime.model"
    if type(value) is not dict:
        raise RuntimeManifestError(f"{location} must be a JSON object")
    try:
        require_exact_keys(
            value,
            {"connector", "implementation_version", "model", "provider", "reasoning"},
            location,
        )
    except ProtocolError as exc:
        raise RuntimeManifestError(str(exc)) from exc
    return {
        key: _string(value[key], f"{location}.{key}")
        for key in (
            "connector",
            "implementation_version",
            "model",
            "provider",
            "reasoning",
        )
    }


def _assay(value: object) -> tuple[dict[str, object], dict[str, object]]:
    location = "runtime.assay"
    if type(value) is not dict:
        raise RuntimeManifestError(f"{location} must be a JSON object")
    try:
        require_exact_keys(
            value,
            {
                "cost_mode",
                "max_model_calls",
                "max_output_bytes",
                "model_timeout_seconds",
            },
            location,
        )
    except ProtocolError as exc:
        raise RuntimeManifestError(str(exc)) from exc
    cost_mode = value["cost_mode"]
    if cost_mode not in {"observed-v1", "deterministic-fixture-v1"}:
        raise RuntimeManifestError(
            f"{location}.cost_mode must be observed-v1 or deterministic-fixture-v1"
        )
    normalized = {
        "cost_mode": cost_mode,
        "max_model_calls": _integer(
            value["max_model_calls"], f"{location}.max_model_calls", 1, 1024
        ),
        "max_output_bytes": _integer(
            value["max_output_bytes"], f"{location}.max_output_bytes", 1024, 16_777_216
        ),
        "model_timeout_seconds": _integer(
            value["model_timeout_seconds"],
            f"{location}.model_timeout_seconds",
            1,
            3600,
        ),
    }
    return normalized, normalized


def load_runtime_manifest(path: Path) -> RuntimeManifest:
    """Load one canonical runtime profile and derive its stable identity."""

    path = path.expanduser().absolute()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeManifestError(f"cannot read runtime manifest: {exc}") from exc
    document = decode_json_object(source, RuntimeManifestError)
    if source != canonical_json(document) + "\n":
        raise RuntimeManifestError(
            "runtime manifest must be canonical JSON followed by newline"
        )
    try:
        require_exact_keys(
            document,
            {
                "assay",
                "kernel",
                "model",
                "runtime_schema",
                "schema_version",
                "supported_dependency_locks",
            },
            "runtime manifest",
        )
    except ProtocolError as exc:
        raise RuntimeManifestError(str(exc)) from exc
    if document["runtime_schema"] != RUNTIME_SCHEMA:
        raise RuntimeManifestError(
            f"runtime manifest.runtime_schema must be {RUNTIME_SCHEMA}"
        )
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise RuntimeManifestError("runtime manifest.schema_version must be 1")
    kernel, kernel_values = _kernel(document["kernel"])
    model = _model(document["model"])
    assay, assay_values = _assay(document["assay"])
    raw_locks = document["supported_dependency_locks"]
    if type(raw_locks) is not list or not raw_locks:
        raise RuntimeManifestError(
            "runtime manifest.supported_dependency_locks must be non-empty"
        )
    locks: list[str] = []
    try:
        for index, item in enumerate(raw_locks):
            lock = require_sha256(
                item, f"runtime manifest.supported_dependency_locks[{index}]"
            )
            if lock in locks:
                raise ProtocolError("runtime manifest has a duplicate dependency lock")
            locks.append(lock)
    except ProtocolError as exc:
        raise RuntimeManifestError(str(exc)) from exc
    if locks != sorted(locks):
        raise RuntimeManifestError(
            "runtime manifest.supported_dependency_locks must be sorted"
        )
    if kernel_values["kind"] == "oci-v1" and assay["cost_mode"] != "observed-v1":
        raise RuntimeManifestError("oci-v1 requires observed-v1 cost semantics")
    if (
        kernel_values["kind"] == "process-fixture-v1"
        and assay["cost_mode"] != "deterministic-fixture-v1"
    ):
        raise RuntimeManifestError(
            "process-fixture-v1 requires deterministic-fixture-v1 cost semantics"
        )
    normalized = {
        "assay": assay,
        "kernel": kernel,
        "model": model,
        "runtime_schema": RUNTIME_SCHEMA,
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "supported_dependency_locks": locks,
    }
    if document != normalized:
        raise RuntimeManifestError("runtime manifest is not normalized")
    runtime_id = canonical_digest(
        {"runtime": normalized, "runtime_identity": RUNTIME_SCHEMA}
    )
    return RuntimeManifest(
        document=normalized,
        runtime_id=runtime_id,
        path=path,
        kind=cast(Literal["oci-v1", "process-fixture-v1"], kernel_values["kind"]),
        command=cast(tuple[str, ...], kernel_values["command"]),
        engine=cast(str | None, kernel_values["engine"]),
        image=cast(str | None, kernel_values["image"]),
        limits=cast(KernelLimits, kernel_values["limits"]),
        required_observations=cast(tuple[str, ...], kernel_values["observations"]),
        cost_mode=cast(
            Literal["observed-v1", "deterministic-fixture-v1"],
            assay_values["cost_mode"],
        ),
        max_model_calls=cast(int, assay_values["max_model_calls"]),
        max_output_bytes=cast(int, assay_values["max_output_bytes"]),
        model_timeout_seconds=cast(int, assay_values["model_timeout_seconds"]),
        model=model,
        supported_dependency_locks=tuple(locks),
    )


def assert_candidate_compatible(
    runtime: RuntimeManifest, dependency_lock: bytes
) -> None:
    """Reject a candidate dependency genome not present in the immutable image."""

    import hashlib

    digest = hashlib.sha256(dependency_lock).hexdigest()
    if digest not in runtime.supported_dependency_locks:
        raise RuntimeManifestError(
            "candidate dependency_lock is not supported by the immutable runtime"
        )
