#!/usr/bin/env python3
"""Translate authenticated solution execution receipts into Population evidence."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json, decode_json_object  # noqa: E402
from apps.coding_agent.candidate_runner import EVIDENCE_KEY  # noqa: E402
from apps.coding_agent.solution_evaluator import (  # noqa: E402
    SolutionEvaluatorError,
    load_evaluation_receipt,
    validate_evaluation_receipt,
)
from apps.harness.runtime_manifest import RuntimeManifestError, load_runtime_manifest  # noqa: E402
from apps.population.contract import RESOURCE_NAMES  # noqa: E402


class CodingEvidenceError(RuntimeError):
    """Raised when Controller traces do not bind solution execution receipts."""


def _report(result: dict[str, object], name: str) -> dict[str, object]:
    value = result.get(name)
    if type(value) is not dict:
        raise CodingEvidenceError(f"Controller result omitted {name}")
    return value


def _candidate_receipts(
    result: dict[str, object], candidate_id: str, runtime_id: str
) -> list[dict[str, object]]:
    traces = result.get("cases")
    if type(traces) is not list:
        raise CodingEvidenceError("Controller result.cases must be an array")
    receipts: list[dict[str, object]] = []
    for trace in traces:
        if type(trace) is not dict:
            raise CodingEvidenceError("Controller case trace is malformed")
        matched = False
        for key in ("incumbent_run", "challenger_run"):
            run = trace.get(key)
            if type(run) is not dict or run.get("candidate_id") != candidate_id:
                continue
            matched = True
            task = run.get("task")
            runner = run.get("runner")
            if type(task) is not dict or type(runner) is not dict:
                raise CodingEvidenceError("Controller solution run is malformed")
            submission = runner.get("submission")
            if type(submission) is not dict:
                raise CodingEvidenceError("solution submission is malformed")
            metadata = submission.get(EVIDENCE_KEY)
            if type(metadata) is not dict or set(metadata) != {"receipt", "runtime_id"}:
                raise CodingEvidenceError("solution receipt metadata is malformed")
            if metadata["runtime_id"] != runtime_id:
                raise CodingEvidenceError("solution receipt changed runtime identity")
            try:
                receipt, _ = load_evaluation_receipt(metadata["receipt"])
                validate_evaluation_receipt(
                    receipt,
                    candidate_id=candidate_id,
                    task=task,
                    runtime_id=runtime_id,
                )
            except SolutionEvaluatorError as exc:
                raise CodingEvidenceError(str(exc)) from exc
            receipts.append(receipt)
        if not matched:
            raise CodingEvidenceError(
                f"Controller trace omitted solution run {candidate_id}"
            )
    return receipts


def _aggregate_cost(receipts: list[dict[str, object]]) -> dict[str, int]:
    total = {name: 0 for name in RESOURCE_NAMES}
    for receipt in receipts:
        cost = receipt["cost"]
        if type(cost) is not dict:
            raise CodingEvidenceError("solution receipt cost is malformed")
        for name in RESOURCE_NAMES:
            value = cost.get(name)
            if type(value) is not int or value < 0:
                raise CodingEvidenceError("solution receipt cost is malformed")
            total[name] += value
    return total


def adapt(request: dict[str, object]) -> dict[str, object]:
    if set(request) != {
        "controller_receipt",
        "controller_result",
        "experiment",
        "protocol_version",
        "round",
    }:
        raise CodingEvidenceError("coding evidence request has the wrong keys")
    if request["protocol_version"] != 1:
        raise CodingEvidenceError("coding evidence protocol_version must be 1")
    result = request["controller_result"]
    experiment = request["experiment"]
    if type(result) is not dict or type(experiment) is not dict:
        raise CodingEvidenceError("coding evidence request is malformed")
    specification = experiment.get("specification")
    if type(specification) is not dict:
        raise CodingEvidenceError("Population experiment specification is malformed")
    runtime_path = os.environ.get("METERING_HARNESS_RUNTIME_MANIFEST")
    if not runtime_path:
        raise CodingEvidenceError(
            "METERING_HARNESS_RUNTIME_MANIFEST must name a profile"
        )
    runtime = load_runtime_manifest(Path(runtime_path))
    coding_runtime_id = os.environ.get("METERING_CODING_RUNTIME_ID")
    if not coding_runtime_id or specification.get("runtime_id") != coding_runtime_id:
        raise CodingEvidenceError(
            "Population experiment changed coding runtime identity"
        )
    candidates: list[dict[str, object]] = []
    for report_name in ("incumbent_report", "challenger_report"):
        report = _report(result, report_name)
        candidate_id = report.get("candidate")
        summary = report.get("task_summary")
        if type(candidate_id) is not str or type(summary) is not dict:
            raise CodingEvidenceError(f"Controller {report_name} is malformed")
        passed = summary.get("passed_count")
        count = summary.get("case_count")
        safety = summary.get("safety_failures")
        if (
            type(passed) is not int
            or type(count) is not int
            or count < 1
            or type(safety) is not int
        ):
            raise CodingEvidenceError(
                f"Controller {report_name} task summary is malformed"
            )
        receipts = _candidate_receipts(result, candidate_id, runtime.runtime_id)
        if len(receipts) != count:
            raise CodingEvidenceError(
                "solution receipt count does not match task assay"
            )
        rate = passed / count
        candidates.append(
            {
                "behavior_distribution": [1.0 - rate, rate],
                "candidate_id": candidate_id,
                "cost": _aggregate_cost(receipts),
                "protected_passed": safety == 0,
                "seed": {
                    "receipt_sha256": sorted(
                        str(
                            run["runner"]["submission"][EVIDENCE_KEY]["receipt"][
                                "sha256"
                            ]
                        )
                        for trace in result["cases"]
                        for run in (trace["incumbent_run"], trace["challenger_run"])
                        if run["candidate_id"] == candidate_id
                    ),
                    "round": request["round"],
                    "runtime_id": runtime.runtime_id,
                },
            }
        )
    return {"candidates": candidates, "protocol_version": 1}


def main() -> int:
    try:
        request = decode_json_object(sys.stdin.read(), CodingEvidenceError)
        response = adapt(request)
    except (
        CodingEvidenceError,
        OSError,
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
