#!/usr/bin/env python3
"""Independent sandboxed evaluator for coding-workspace submissions."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_digest, canonical_json, decode_json_object  # noqa: E402
from apps.agent_protocol import ProtocolError, require_exact_keys, require_sha256  # noqa: E402
from apps.harness.harness_runner import WORKSPACE_KEY  # noqa: E402
from apps.harness.kernel_contract import KernelContractError, KernelSession  # noqa: E402
from apps.harness.runtime_manifest import (  # noqa: E402
    RuntimeManifest,
    RuntimeManifestError,
    load_runtime_manifest,
)
from apps.harness.workspace import (  # noqa: E402
    WorkspaceError,
    changed_paths,
    decode_files,
    files_digest,
    normalize_policy,
    require_allowed_changes,
)
from apps.population.contract import RESOURCE_NAMES  # noqa: E402


class CodingEvaluatorError(RuntimeError):
    """Raised when a coding submission or trusted assay is malformed."""


def _runtime_path() -> Path:
    source = os.environ.get("METERING_HARNESS_RUNTIME_MANIFEST")
    if not source:
        raise CodingEvaluatorError(
            "METERING_HARNESS_RUNTIME_MANIFEST must name a profile"
        )
    return Path(source)


def _assay(value: object) -> tuple[list[str], int]:
    if type(value) is not dict:
        raise CodingEvaluatorError("coding task assay must be a JSON object")
    try:
        require_exact_keys(value, {"argv", "timeout_ms"}, "coding task assay")
    except ProtocolError as exc:
        raise CodingEvaluatorError(str(exc)) from exc
    argv = value["argv"]
    timeout = value["timeout_ms"]
    if (
        type(argv) is not list
        or not argv
        or any(type(item) is not str or not item or "\x00" in item for item in argv)
        or type(timeout) is not int
        or not 1 <= timeout <= 3_600_000
    ):
        raise CodingEvaluatorError("coding task assay is malformed")
    return cast(list[str], argv), timeout


def _workspace(
    submission: object,
    base_files: list[dict[str, object]],
    policy: dict[str, object],
) -> list[dict[str, object]]:
    if type(submission) is not dict:
        raise CodingEvaluatorError("candidate coding submission must be a JSON object")
    raw = submission.get(WORKSPACE_KEY)
    if type(raw) is not dict or set(raw) != {
        "base_sha256",
        "changed_paths",
        "files",
        "sha256",
    }:
        raise CodingEvaluatorError("candidate omitted its fixed coding workspace")
    try:
        base = require_sha256(raw["base_sha256"], "coding workspace.base_sha256")
        digest = require_sha256(raw["sha256"], "coding workspace.sha256")
        files = decode_files(
            raw["files"],
            max_files=int(policy["max_files"]),
            max_bytes=int(policy["max_bytes"]),
        )
    except (ProtocolError, WorkspaceError) as exc:
        raise CodingEvaluatorError(str(exc)) from exc
    changed = raw["changed_paths"]
    if (
        type(changed) is not list
        or any(type(item) is not str for item in changed)
        or changed != sorted(set(changed))
    ):
        raise CodingEvaluatorError("candidate coding changed_paths is malformed")
    expected_paths = changed_paths(base_files, files)
    try:
        require_allowed_changes(
            expected_paths, cast(list[str], policy["allowed_write_paths"])
        )
    except WorkspaceError as exc:
        raise CodingEvaluatorError(str(exc)) from exc
    expected_digest = canonical_digest(
        {"changed_paths": expected_paths, "files": files}
    )
    if (
        base != files_digest(base_files)
        or changed != expected_paths
        or digest != expected_digest
    ):
        raise CodingEvaluatorError("candidate coding workspace identity changed")
    return files


def evaluation_cost(
    observations: list[dict[str, object]], runtime: RuntimeManifest
) -> dict[str, int]:
    if runtime.cost_mode == "deterministic-fixture-v1":
        return {name: 0 for name in RESOURCE_NAMES}
    return {
        "actions": len(observations),
        "energy_millijoules": 0,
        "gpu_milliseconds": 0,
        "memory_bytes": max(
            (int(item["memory_peak_bytes"] or 0) for item in observations),
            default=0,
        ),
        "storage_bytes": sum(
            int(item["storage_write_bytes"] or 0) for item in observations
        ),
        "tokens": 0,
        "wall_milliseconds": sum(
            int(item["wall_milliseconds"]) for item in observations
        ),
    }


def _evaluate_submission(
    submission: object,
    *,
    files: list[dict[str, object]],
    policy: dict[str, object],
    argv: list[str],
    timeout_ms: int,
) -> tuple[bool, dict[str, object]]:
    runtime = load_runtime_manifest(_runtime_path())
    allow_fixture = os.environ.get("METERING_HARNESS_ALLOW_UNSAFE_FIXTURE") == "1"
    snapshot_policy = {
        "allowed_names": [],
        "max_bytes": 64,
        "mode": "disabled-v1",
        "restore_after_restart": False,
        "schema_version": 1,
    }
    session = KernelSession(
        runtime, "pass\n", snapshot_policy, allow_fixture=allow_fixture
    )
    try:
        session.initialize_workspace(files, policy)
        result = session.run_workspace_command(argv, timeout_ms=timeout_ms)
    finally:
        observations = session.close()
    passed = result["returncode"] == 0 and result["timed_out"] is False
    stdout = str(result["stdout"])
    stderr = str(result["stderr"])
    observation_documents = [item.document() for item in observations]
    evidence = {
        "assay_sha256": canonical_digest({"argv": argv, "timeout_ms": timeout_ms}),
        "cost": evaluation_cost(observation_documents, runtime),
        "isolation_enforced": runtime.isolation_enforced,
        "kernel_observations": observation_documents,
        "returncode": result["returncode"],
        "runtime_id": runtime.runtime_id,
        "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        "timed_out": result["timed_out"],
        "workspace_sha256": files_digest(files),
    }
    return passed, evidence


def evaluate(request: dict[str, object]) -> dict[str, object]:
    if set(request) != {"case", "evaluation", "protocol_version", "submissions"}:
        raise CodingEvaluatorError("coding evaluator request has the wrong keys")
    if request["protocol_version"] != 1:
        raise CodingEvaluatorError("coding evaluator protocol_version must be 1")
    case = request["case"]
    if type(case) is not dict or set(case) != {"case_id", "input"}:
        raise CodingEvaluatorError("coding evaluator case is malformed")
    task_input = case["input"]
    if type(task_input) is not dict or set(task_input) != {
        "assay",
        "outcomes",
        "prompt",
        "workspace",
    }:
        raise CodingEvaluatorError("coding evaluator task input is malformed")
    workspace = task_input["workspace"]
    if type(workspace) is not dict or set(workspace) != {"files", "policy"}:
        raise CodingEvaluatorError("coding evaluator workspace is malformed")
    try:
        policy = normalize_policy(workspace["policy"])
        base_files = decode_files(
            workspace["files"],
            max_files=int(policy["max_files"]),
            max_bytes=int(policy["max_bytes"]),
        )
    except WorkspaceError as exc:
        raise CodingEvaluatorError(str(exc)) from exc
    argv, timeout_ms = _assay(task_input["assay"])
    submissions = request["submissions"]
    if type(submissions) is not list or not submissions:
        raise CodingEvaluatorError("coding evaluator submissions must be non-empty")
    results: list[dict[str, object]] = []
    for index, item in enumerate(submissions):
        if type(item) is not dict or set(item) != {"candidate_id", "submission"}:
            raise CodingEvaluatorError(
                f"coding evaluator submissions[{index}] is malformed"
            )
        try:
            candidate_id = require_sha256(
                item["candidate_id"],
                f"coding evaluator submissions[{index}].candidate_id",
            )
            files = _workspace(item["submission"], base_files, policy)
            passed, evidence = _evaluate_submission(
                item["submission"],
                files=files,
                policy=policy,
                argv=argv,
                timeout_ms=timeout_ms,
            )
            safety_passed = True
        except (CodingEvaluatorError, KernelContractError, RuntimeManifestError) as exc:
            candidate_id = require_sha256(
                item["candidate_id"],
                f"coding evaluator submissions[{index}].candidate_id",
            )
            passed = False
            safety_passed = False
            evidence = {
                "error_sha256": hashlib.sha256(str(exc).encode("utf-8")).hexdigest()
            }
        results.append(
            {
                "candidate_id": candidate_id,
                "evidence": evidence,
                "outcome": "pass" if passed else "fail",
                "passed": passed,
                "safety_passed": safety_passed,
            }
        )
    return {"results": results}


def main() -> int:
    try:
        request = decode_json_object(sys.stdin.read(), CodingEvaluatorError)
        response = evaluate(request)
    except (
        CodingEvaluatorError,
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
