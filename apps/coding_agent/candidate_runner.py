#!/usr/bin/env python3
"""Execute an immutable solution candidate under one trusted coding assay."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.durable import atomic_write, reject_symlink  # noqa: E402
from apps._support.wire import canonical_digest, canonical_json, decode_json_object  # noqa: E402
from apps.agent_protocol import ProtocolError, require_exact_keys, require_sha256  # noqa: E402
from apps.harness.kernel_contract import KernelContractError, KernelSession  # noqa: E402
from apps.harness.runtime_manifest import (  # noqa: E402
    RuntimeManifest,
    RuntimeManifestError,
    load_runtime_manifest,
)
from apps.harness.workspace import (  # noqa: E402
    WorkspaceError,
    files_digest,
    snapshot_directory,
)
from apps.population.contract import RESOURCE_NAMES  # noqa: E402

EVIDENCE_KEY = "_metering_coding_candidate"
RECEIPT_SCHEMA = "darwinian-coding-evaluation-receipt-v1"


class CodingRunnerError(RuntimeError):
    """Raised when a solution candidate cannot be evaluated safely."""


def _request(
    source: str,
) -> tuple[str, dict[str, object], dict[str, object], Path]:
    request = decode_json_object(source, CodingRunnerError)
    try:
        require_exact_keys(
            request, {"candidate", "protocol_version", "task"}, "request"
        )
        if request["protocol_version"] != 1:
            raise ProtocolError("request.protocol_version must be 1")
        candidate = request["candidate"]
        if type(candidate) is not dict:
            raise ProtocolError("request.candidate must be a JSON object")
        require_exact_keys(
            candidate,
            {"artifact", "candidate_id", "checkout_path"},
            "request.candidate",
        )
        candidate_id = require_sha256(
            candidate["candidate_id"], "request.candidate.candidate_id"
        )
        artifact = candidate["artifact"]
        if type(artifact) is not dict:
            raise ProtocolError("request.candidate.artifact must be a JSON object")
        checkout = candidate["checkout_path"]
        if type(checkout) is not str or not checkout or "\x00" in checkout:
            raise ProtocolError("request.candidate.checkout_path must be a path")
        task = request["task"]
        if type(task) is not dict:
            raise ProtocolError("request.task must be a JSON object")
        require_exact_keys(task, {"case_id", "input"}, "request.task")
        if type(task["case_id"]) is not str or not task["case_id"]:
            raise ProtocolError("request.task.case_id must be non-empty text")
        task_input = task["input"]
        if type(task_input) is not dict or set(task_input) != {
            "assay",
            "outcomes",
            "prompt",
        }:
            raise ProtocolError("solution task input is malformed")
    except ProtocolError as exc:
        raise CodingRunnerError(str(exc)) from exc
    return (
        candidate_id,
        cast(dict[str, object], artifact),
        cast(dict[str, object], task),
        Path(checkout),
    )


def _assay(task: dict[str, object]) -> tuple[list[str], int]:
    task_input = cast(dict[str, object], task["input"])
    assay = task_input["assay"]
    if type(assay) is not dict or set(assay) != {"argv", "timeout_ms"}:
        raise CodingRunnerError("solution task assay is malformed")
    argv = assay["argv"]
    timeout = assay["timeout_ms"]
    if (
        type(argv) is not list
        or not argv
        or any(type(item) is not str or not item or "\x00" in item for item in argv)
        or type(timeout) is not int
        or not 1 <= timeout <= 3_600_000
    ):
        raise CodingRunnerError("solution task assay is malformed")
    outcomes = task_input["outcomes"]
    if outcomes != ["fail", "pass"]:
        raise CodingRunnerError("solution task outcomes must be fail then pass")
    return cast(list[str], argv), timeout


def _runtime() -> RuntimeManifest:
    source = os.environ.get("METERING_HARNESS_RUNTIME_MANIFEST")
    if not source:
        raise CodingRunnerError("METERING_HARNESS_RUNTIME_MANIFEST must name a profile")
    return load_runtime_manifest(Path(source))


def _cost(runtime: RuntimeManifest, observations: list[object]) -> dict[str, int]:
    if runtime.cost_mode == "deterministic-fixture-v1":
        return {name: 0 for name in RESOURCE_NAMES}
    documents = [item.document() for item in observations]  # type: ignore[attr-defined]
    return {
        "actions": 1,
        "energy_millijoules": 0,
        "gpu_milliseconds": 0,
        "memory_bytes": max(
            (int(item["memory_peak_bytes"] or 0) for item in documents), default=0
        ),
        "storage_bytes": sum(
            int(item["storage_write_bytes"] or 0) for item in documents
        ),
        "tokens": 0,
        "wall_milliseconds": sum(int(item["wall_milliseconds"]) for item in documents),
    }


def _write_receipt(root: Path, document: dict[str, object]) -> dict[str, str]:
    root = root.expanduser().absolute()
    reject_symlink(root, "coding evaluation receipt directory", CodingRunnerError)
    root.mkdir(parents=True, exist_ok=True)
    source = (canonical_json(document) + "\n").encode("ascii")
    digest = hashlib.sha256(source).hexdigest()
    path = root / f"{digest}.json"
    reject_symlink(path, "coding evaluation receipt", CodingRunnerError)
    if path.exists():
        if path.read_bytes() != source:
            raise CodingRunnerError("coding evaluation receipt identity conflicts")
    else:
        atomic_write(path, source)
    return {"sha256": digest, "uri": path.as_uri()}


def execute(source: str) -> dict[str, object]:
    candidate_id, artifact, task, checkout = _request(source)
    runtime = _runtime()
    receipt_root = os.environ.get("METERING_CODING_EVALUATION_RECEIPT_DIR")
    if not receipt_root:
        raise CodingRunnerError(
            "METERING_CODING_EVALUATION_RECEIPT_DIR must name durable storage"
        )
    argv, timeout_ms = _assay(task)
    files = snapshot_directory(checkout)
    policy = {
        "allowed_write_paths": sorted(str(item["path"]) for item in files),
        "command_timeout_ms": timeout_ms,
        "max_bytes": 8_388_608,
        "max_files": 2_000,
        "max_output_characters": 65_536,
    }
    snapshot_policy = {
        "allowed_names": [],
        "max_bytes": 64,
        "mode": "disabled-v1",
        "restore_after_restart": False,
        "schema_version": 1,
    }
    allow_fixture = (
        runtime.kind == "process-fixture-v1"
        and os.environ.get("METERING_HARNESS_ALLOW_UNSAFE_FIXTURE") == "1"
    )
    session = KernelSession(
        runtime, "pass\n", snapshot_policy, allow_fixture=allow_fixture
    )
    try:
        session.initialize_workspace(files, policy)
        execution = session.run_workspace_command(argv, timeout_ms=timeout_ms)
    finally:
        observations = session.close()
    task_id = canonical_digest(task)
    execution_document = {
        "returncode": execution["returncode"],
        "stderr": execution["stderr"],
        "stdout": execution["stdout"],
        "timed_out": execution["timed_out"],
    }
    receipt = {
        "assay": {"argv": argv, "timeout_ms": timeout_ms},
        "candidate_content_sha256": artifact.get("content_sha256"),
        "candidate_id": candidate_id,
        "cost": _cost(runtime, cast(list[object], observations)),
        "execution": execution_document,
        "isolation_enforced": runtime.isolation_enforced,
        "kernel_observations": [item.document() for item in observations],
        "receipt_schema": RECEIPT_SCHEMA,
        "runtime_id": runtime.runtime_id,
        "task_id": task_id,
        "workspace_sha256": files_digest(files),
    }
    reference = _write_receipt(Path(receipt_root), receipt)
    forecast = {
        "outcomes": [
            {"outcome": "fail", "probability": 0.5},
            {"outcome": "pass", "probability": 0.5},
        ]
    }
    submission = {
        EVIDENCE_KEY: {
            "receipt": reference,
            "runtime_id": runtime.runtime_id,
        },
        "execution": {
            "returncode": execution["returncode"],
            "stderr_sha256": hashlib.sha256(
                str(execution["stderr"]).encode("utf-8")
            ).hexdigest(),
            "stdout_sha256": hashlib.sha256(
                str(execution["stdout"]).encode("utf-8")
            ).hexdigest(),
            "timed_out": execution["timed_out"],
        },
    }
    return {"forecast": forecast, "submission": submission}


def main() -> int:
    try:
        response = execute(sys.stdin.read())
    except (
        CodingRunnerError,
        KernelContractError,
        OSError,
        ProtocolError,
        RuntimeManifestError,
        TypeError,
        ValueError,
        WorkspaceError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
