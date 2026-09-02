#!/usr/bin/env python3
"""Interpret authenticated sandbox receipts for immutable solution candidates."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_digest, canonical_json, decode_json_object  # noqa: E402
from apps.agent_protocol import ProtocolError, require_exact_keys, require_sha256  # noqa: E402
from apps.coding_agent.candidate_runner import (  # noqa: E402
    EVIDENCE_KEY,
    RECEIPT_SCHEMA,
)
from apps.harness.runtime_manifest import RuntimeManifestError, load_runtime_manifest  # noqa: E402
from apps.population.contract import RESOURCE_NAMES  # noqa: E402


class SolutionEvaluatorError(RuntimeError):
    """Raised when coding execution evidence is malformed or unbound."""


def _receipt_root() -> Path:
    source = os.environ.get("METERING_CODING_EVALUATION_RECEIPT_DIR")
    if not source:
        raise SolutionEvaluatorError(
            "METERING_CODING_EVALUATION_RECEIPT_DIR must name durable storage"
        )
    root = Path(source).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise SolutionEvaluatorError("coding evaluation receipt directory is unsafe")
    return root


def load_evaluation_receipt(
    reference: object,
) -> tuple[dict[str, object], str]:
    if type(reference) is not dict:
        raise SolutionEvaluatorError("coding evaluation receipt reference is malformed")
    try:
        require_exact_keys(reference, {"sha256", "uri"}, "coding receipt reference")
        digest = require_sha256(reference["sha256"], "coding receipt reference.sha256")
    except ProtocolError as exc:
        raise SolutionEvaluatorError(str(exc)) from exc
    uri = reference["uri"]
    if type(uri) is not str:
        raise SolutionEvaluatorError("coding receipt URI must be text")
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise SolutionEvaluatorError("coding receipt URI must be local")
    path = Path(unquote(parsed.path)).absolute()
    expected = _receipt_root() / f"{digest}.json"
    if path != expected or path.is_symlink() or not path.is_file():
        raise SolutionEvaluatorError("coding receipt path is unsafe")
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != digest:
        raise SolutionEvaluatorError("coding receipt digest does not match")
    try:
        text = source.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SolutionEvaluatorError("coding receipt must be ASCII JSON") from exc
    document = decode_json_object(text, SolutionEvaluatorError)
    if text != canonical_json(document) + "\n":
        raise SolutionEvaluatorError("coding receipt is not canonical")
    return document, digest


def validate_evaluation_receipt(
    receipt: dict[str, object],
    *,
    candidate_id: str,
    task: dict[str, object],
    runtime_id: str,
) -> dict[str, object]:
    expected = {
        "assay",
        "candidate_content_sha256",
        "candidate_id",
        "cost",
        "execution",
        "isolation_enforced",
        "kernel_observations",
        "receipt_schema",
        "runtime_id",
        "task_id",
        "workspace_sha256",
    }
    try:
        require_exact_keys(receipt, expected, "coding evaluation receipt")
        require_sha256(
            receipt["candidate_content_sha256"],
            "coding evaluation receipt.candidate_content_sha256",
        )
        require_sha256(receipt["workspace_sha256"], "coding receipt.workspace_sha256")
    except ProtocolError as exc:
        raise SolutionEvaluatorError(str(exc)) from exc
    if (
        receipt["receipt_schema"] != RECEIPT_SCHEMA
        or receipt["candidate_id"] != candidate_id
        or receipt["runtime_id"] != runtime_id
        or receipt["task_id"] != canonical_digest(task)
    ):
        raise SolutionEvaluatorError(
            "coding receipt changed candidate, task, or runtime"
        )
    execution = receipt["execution"]
    if type(execution) is not dict or set(execution) != {
        "returncode",
        "stderr",
        "stdout",
        "timed_out",
    }:
        raise SolutionEvaluatorError("coding receipt execution is malformed")
    if (
        (
            execution["returncode"] is not None
            and type(execution["returncode"]) is not int
        )
        or type(execution["stderr"]) is not str
        or type(execution["stdout"]) is not str
        or type(execution["timed_out"]) is not bool
        or type(receipt["isolation_enforced"]) is not bool
    ):
        raise SolutionEvaluatorError("coding receipt execution is malformed")
    cost = receipt["cost"]
    if (
        type(cost) is not dict
        or set(cost) != set(RESOURCE_NAMES)
        or any(type(value) is not int or value < 0 for value in cost.values())
    ):
        raise SolutionEvaluatorError("coding receipt cost is malformed")
    return execution


def evaluate(request: dict[str, object]) -> dict[str, object]:
    if set(request) != {"case", "evaluation", "protocol_version", "submissions"}:
        raise SolutionEvaluatorError("solution evaluator request has the wrong keys")
    if request["protocol_version"] != 1:
        raise SolutionEvaluatorError("solution evaluator protocol_version must be 1")
    case = request["case"]
    if type(case) is not dict:
        raise SolutionEvaluatorError("solution evaluator case is malformed")
    runtime_path = os.environ.get("METERING_HARNESS_RUNTIME_MANIFEST")
    if not runtime_path:
        raise SolutionEvaluatorError(
            "METERING_HARNESS_RUNTIME_MANIFEST must name a profile"
        )
    runtime = load_runtime_manifest(Path(runtime_path))
    submissions = request["submissions"]
    if type(submissions) is not list or not submissions:
        raise SolutionEvaluatorError("solution evaluator submissions must be non-empty")
    results: list[dict[str, object]] = []
    for index, item in enumerate(submissions):
        if type(item) is not dict or set(item) != {"candidate_id", "submission"}:
            raise SolutionEvaluatorError(
                f"solution evaluator submissions[{index}] is malformed"
            )
        try:
            candidate_id = require_sha256(
                item["candidate_id"],
                f"solution evaluator submissions[{index}].candidate_id",
            )
            submission = item["submission"]
            if type(submission) is not dict or set(submission) != {
                EVIDENCE_KEY,
                "execution",
            }:
                raise SolutionEvaluatorError("solution submission is malformed")
            metadata = submission[EVIDENCE_KEY]
            if type(metadata) is not dict or set(metadata) != {"receipt", "runtime_id"}:
                raise SolutionEvaluatorError("solution receipt metadata is malformed")
            if metadata["runtime_id"] != runtime.runtime_id:
                raise SolutionEvaluatorError("solution submission changed runtime")
            receipt, digest = load_evaluation_receipt(metadata["receipt"])
            execution = validate_evaluation_receipt(
                receipt,
                candidate_id=candidate_id,
                task=case,
                runtime_id=runtime.runtime_id,
            )
            summary = submission["execution"]
            if type(summary) is not dict or set(summary) != {
                "returncode",
                "stderr_sha256",
                "stdout_sha256",
                "timed_out",
            }:
                raise SolutionEvaluatorError("solution execution summary is malformed")
            expected_summary = {
                "returncode": execution["returncode"],
                "stderr_sha256": hashlib.sha256(
                    str(execution["stderr"]).encode("utf-8")
                ).hexdigest(),
                "stdout_sha256": hashlib.sha256(
                    str(execution["stdout"]).encode("utf-8")
                ).hexdigest(),
                "timed_out": execution["timed_out"],
            }
            if summary != expected_summary:
                raise SolutionEvaluatorError("solution execution summary changed")
            passed = execution["returncode"] == 0 and execution["timed_out"] is False
            safety_passed = (
                receipt["isolation_enforced"] is True
                if runtime.isolation_enforced
                else True
            )
            evidence = {"receipt_sha256": digest}
        except (ProtocolError, SolutionEvaluatorError) as exc:
            candidate_id = require_sha256(
                item["candidate_id"],
                f"solution evaluator submissions[{index}].candidate_id",
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
        request = decode_json_object(sys.stdin.read(), SolutionEvaluatorError)
        response = evaluate(request)
    except (
        OSError,
        ProtocolError,
        RuntimeManifestError,
        SolutionEvaluatorError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
