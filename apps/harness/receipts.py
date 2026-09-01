"""Content-addressed immutable receipts for harness execution evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import unquote, urlparse

from apps._support.durable import atomic_write, reject_symlink
from apps._support.wire import canonical_digest, canonical_json, decode_json_object
from apps.agent_protocol import ProtocolError, require_exact_keys, require_sha256
from apps.harness.protocol import HarnessCandidate
from apps.harness.runtime import HarnessCompletion
from apps.harness.runtime_manifest import RuntimeManifest
from apps.population.contract import RESOURCE_NAMES

RECEIPT_SCHEMA = "evolutionary-harness-run-receipt-v1"


class HarnessReceiptError(RuntimeError):
    """Raised when execution evidence is absent, mutable, or malformed."""


def receipt_document(
    *,
    candidate_id: str,
    case_id: str,
    task: dict[str, object],
    candidate: HarnessCandidate,
    runtime: RuntimeManifest,
    completion: HarnessCompletion,
) -> dict[str, object]:
    task_id = canonical_digest({"case_id": case_id, "input": task})
    return {
        "candidate_id": candidate_id,
        "case_id": case_id,
        "completion": {
            "result_sha256": completion_result_digest(
                completion.forecast, completion.submission
            ),
            "status": "finished",
            "transcript_sha256": completion.transcript_digest,
        },
        "cost": completion.population_cost,
        "isolation": {
            "enforced": runtime.isolation_enforced,
            "kernel_kind": runtime.kind,
            "network": "none" if runtime.isolation_enforced else "fixture-host-process",
            "unavailable_cost_coordinates": [
                "energy_millijoules",
                "gpu_milliseconds",
            ],
        },
        "kernel_observations": [
            item.document() for item in completion.kernel_observations
        ],
        "manifest_id": candidate.manifest_id,
        "model_observations": [
            item.document() for item in completion.model_observations
        ],
        "model_usage": {
            "actions": completion.actions,
            "calls": completion.model_calls,
            "input_tokens": completion.input_tokens,
            "output_tokens": completion.output_tokens,
        },
        "receipt_schema": RECEIPT_SCHEMA,
        "runtime_id": runtime.runtime_id,
        "task_id": task_id,
    }


def completion_result_digest(forecast: object, submission: object) -> str:
    """Bind the externally returned completion to its immutable run receipt."""

    return canonical_digest({"forecast": forecast, "submission": submission})


def write_receipt(root: Path, document: dict[str, object]) -> dict[str, str]:
    """Durably publish one canonical document under its SHA-256 identity."""

    root = root.expanduser().absolute()
    reject_symlink(root, "harness receipt directory", HarnessReceiptError)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HarnessReceiptError(
            f"cannot create harness receipt directory: {exc}"
        ) from exc
    source = (canonical_json(document) + "\n").encode("ascii")
    digest = hashlib.sha256(source).hexdigest()
    path = root / f"{digest}.json"
    reject_symlink(path, "harness receipt", HarnessReceiptError)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise HarnessReceiptError(
                f"cannot read existing harness receipt: {exc}"
            ) from exc
        if existing != source:
            raise HarnessReceiptError("content-addressed harness receipt conflicts")
    else:
        try:
            atomic_write(path, source)
        except OSError as exc:
            raise HarnessReceiptError(f"cannot write harness receipt: {exc}") from exc
    return {"sha256": digest, "uri": path.as_uri()}


def _receipt_path(reference: dict[str, object], root: Path) -> Path:
    try:
        require_exact_keys(reference, {"sha256", "uri"}, "harness receipt reference")
        digest = require_sha256(reference["sha256"], "harness receipt reference.sha256")
    except ProtocolError as exc:
        raise HarnessReceiptError(str(exc)) from exc
    uri = reference["uri"]
    if type(uri) is not str:
        raise HarnessReceiptError("harness receipt reference.uri must be a file URI")
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise HarnessReceiptError(
            "harness receipt reference.uri must be a local file URI"
        )
    path = Path(unquote(parsed.path)).absolute()
    expected = root.expanduser().absolute() / f"{digest}.json"
    if path != expected:
        raise HarnessReceiptError(
            "harness receipt URI escapes the configured receipt directory"
        )
    return path


def load_receipt(reference: dict[str, object], root: Path) -> dict[str, object]:
    path = _receipt_path(reference, root)
    reject_symlink(path, "harness receipt", HarnessReceiptError)
    try:
        source = path.read_bytes()
    except OSError as exc:
        raise HarnessReceiptError(f"cannot read harness receipt: {exc}") from exc
    digest = hashlib.sha256(source).hexdigest()
    if digest != reference["sha256"]:
        raise HarnessReceiptError("harness receipt digest does not match")
    try:
        text = source.decode("ascii")
    except UnicodeDecodeError as exc:
        raise HarnessReceiptError(
            "harness receipt must be canonical ASCII JSON"
        ) from exc
    document = decode_json_object(text, HarnessReceiptError)
    if text != canonical_json(document) + "\n":
        raise HarnessReceiptError("harness receipt is not canonical JSON")
    _validate_document(document)
    return document


def _nonnegative(value: object, location: str) -> int:
    if type(value) is not int or value < 0:
        raise HarnessReceiptError(f"{location} must be a non-negative integer")
    return value


def _validate_observation(value: object, location: str) -> None:
    if type(value) is not dict or set(value) != {
        "cpu_microseconds",
        "memory_peak_bytes",
        "processes_peak",
        "source",
        "storage_write_bytes",
        "wall_milliseconds",
    }:
        raise HarnessReceiptError(f"{location} is malformed")
    for name in (
        "cpu_microseconds",
        "memory_peak_bytes",
        "processes_peak",
        "storage_write_bytes",
    ):
        item = value[name]
        if item is not None:
            _nonnegative(item, f"{location}.{name}")
    _nonnegative(value["wall_milliseconds"], f"{location}.wall_milliseconds")
    if value["source"] not in {"cgroup-v2", "procfs", "unavailable"}:
        raise HarnessReceiptError(f"{location}.source is unsupported")


def _validate_document(document: dict[str, object]) -> None:
    expected = {
        "candidate_id",
        "case_id",
        "completion",
        "cost",
        "isolation",
        "kernel_observations",
        "manifest_id",
        "model_observations",
        "model_usage",
        "receipt_schema",
        "runtime_id",
        "task_id",
    }
    try:
        require_exact_keys(document, expected, "harness receipt")
        require_sha256(document["candidate_id"], "harness receipt.candidate_id")
        require_sha256(document["manifest_id"], "harness receipt.manifest_id")
        require_sha256(document["runtime_id"], "harness receipt.runtime_id")
        require_sha256(document["task_id"], "harness receipt.task_id")
    except ProtocolError as exc:
        raise HarnessReceiptError(str(exc)) from exc
    if document["receipt_schema"] != RECEIPT_SCHEMA:
        raise HarnessReceiptError(
            f"harness receipt.receipt_schema must be {RECEIPT_SCHEMA}"
        )
    if type(document["case_id"]) is not str or not document["case_id"]:
        raise HarnessReceiptError("harness receipt.case_id must be non-empty")
    cost = document["cost"]
    if type(cost) is not dict or set(cost) != set(RESOURCE_NAMES):
        raise HarnessReceiptError("harness receipt.cost has the wrong coordinates")
    for name in RESOURCE_NAMES:
        _nonnegative(cost[name], f"harness receipt.cost.{name}")
    usage = document["model_usage"]
    if type(usage) is not dict or set(usage) != {
        "actions",
        "calls",
        "input_tokens",
        "output_tokens",
    }:
        raise HarnessReceiptError("harness receipt.model_usage is malformed")
    for name, value in usage.items():
        _nonnegative(value, f"harness receipt.model_usage.{name}")
    observations = document["kernel_observations"]
    if type(observations) is not list or not observations:
        raise HarnessReceiptError(
            "harness receipt.kernel_observations must be non-empty"
        )
    for index, observation in enumerate(observations):
        _validate_observation(
            observation, f"harness receipt.kernel_observations[{index}]"
        )
    model_observations = document["model_observations"]
    if type(model_observations) is not list or not model_observations:
        raise HarnessReceiptError(
            "harness receipt.model_observations must be non-empty"
        )
    for index, observation in enumerate(model_observations):
        _validate_observation(
            observation, f"harness receipt.model_observations[{index}]"
        )
    isolation = document["isolation"]
    if type(isolation) is not dict or set(isolation) != {
        "enforced",
        "kernel_kind",
        "network",
        "unavailable_cost_coordinates",
    }:
        raise HarnessReceiptError("harness receipt.isolation is malformed")
    kind = isolation["kernel_kind"]
    if kind not in {"oci-v1", "process-fixture-v1"}:
        raise HarnessReceiptError("harness receipt kernel kind is unsupported")
    expected_enforced = kind == "oci-v1"
    expected_network = "none" if expected_enforced else "fixture-host-process"
    if (
        type(isolation["enforced"]) is not bool
        or isolation["enforced"] is not expected_enforced
        or isolation["network"] != expected_network
        or isolation["unavailable_cost_coordinates"]
        != ["energy_millijoules", "gpu_milliseconds"]
    ):
        raise HarnessReceiptError("harness receipt isolation claims are inconsistent")
    completion = document["completion"]
    if type(completion) is not dict or set(completion) != {
        "result_sha256",
        "status",
        "transcript_sha256",
    }:
        raise HarnessReceiptError("harness receipt.completion is malformed")
    if completion["status"] != "finished":
        raise HarnessReceiptError("harness receipt.completion.status must be finished")
    try:
        require_sha256(completion["result_sha256"], "harness receipt result")
        require_sha256(completion["transcript_sha256"], "harness receipt transcript")
    except ProtocolError as exc:
        raise HarnessReceiptError(str(exc)) from exc
    if usage["calls"] < 1 or usage["actions"] < usage["calls"]:
        raise HarnessReceiptError("harness receipt model usage is inconsistent")
    if len(model_observations) != usage["calls"]:
        raise HarnessReceiptError(
            "harness receipt model observations do not match model calls"
        )


def verify_receipt_binding(
    receipt: dict[str, object],
    *,
    candidate_id: str,
    case_id: str,
    task: dict[str, object],
    manifest_id: str,
    runtime: RuntimeManifest,
    forecast: object,
    submission: object,
) -> None:
    """Verify one receipt against the authenticated run and runtime profile."""

    _validate_document(receipt)
    expected_task = canonical_digest({"case_id": case_id, "input": task})
    completion = receipt["completion"]
    isolation = receipt["isolation"]
    assert type(completion) is dict and type(isolation) is dict
    if (
        receipt["candidate_id"] != candidate_id
        or receipt["case_id"] != case_id
        or receipt["task_id"] != expected_task
        or receipt["manifest_id"] != manifest_id
        or receipt["runtime_id"] != runtime.runtime_id
        or completion["result_sha256"] != completion_result_digest(forecast, submission)
        or isolation["enforced"] is not runtime.isolation_enforced
        or isolation["kernel_kind"] != runtime.kind
    ):
        raise HarnessReceiptError(
            "harness receipt changed candidate, task, result, manifest, or runtime"
        )
    observations = receipt["kernel_observations"]
    model_observations = receipt["model_observations"]
    usage = receipt["model_usage"]
    cost = receipt["cost"]
    assert type(observations) is list
    assert type(model_observations) is list
    assert type(usage) is dict
    assert type(cost) is dict
    available = {"wall"}
    for item in observations:
        assert type(item) is dict
        if item["cpu_microseconds"] is not None:
            available.add("cpu")
        if item["memory_peak_bytes"] is not None:
            available.add("memory")
        if item["processes_peak"] is not None:
            available.add("processes")
        if item["storage_write_bytes"] is not None:
            available.add("storage")
    missing = sorted(set(runtime.required_observations) - available)
    if missing:
        raise HarnessReceiptError(
            "harness receipt lacks required observations: " + ", ".join(missing)
        )
    if runtime.cost_mode == "deterministic-fixture-v1":
        expected_cost = {name: 0 for name in RESOURCE_NAMES}
    else:
        combined = [*observations, *model_observations]
        expected_cost = {
            "actions": int(usage["actions"]),
            "energy_millijoules": 0,
            "gpu_milliseconds": 0,
            "memory_bytes": max(
                (int(item["memory_peak_bytes"] or 0) for item in combined),
                default=0,
            ),
            "storage_bytes": sum(
                int(item["storage_write_bytes"] or 0) for item in combined
            ),
            "tokens": int(usage["input_tokens"]) + int(usage["output_tokens"]),
            "wall_milliseconds": sum(
                int(item["wall_milliseconds"]) for item in combined
            ),
        }
    if cost != expected_cost:
        raise HarnessReceiptError("harness receipt cost does not replay")


def aggregate_cost(receipts: list[dict[str, object]]) -> dict[str, int]:
    totals = {name: 0 for name in RESOURCE_NAMES}
    for receipt in receipts:
        cost = receipt["cost"]
        assert type(cost) is dict
        for name in RESOURCE_NAMES:
            totals[name] += int(cost[name])
    return totals
