#!/usr/bin/env python3
"""Translate authenticated harness receipts into Population evidence coordinates."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json, decode_json_object  # noqa: E402
from apps.harness.harness_runner import EVIDENCE_KEY  # noqa: E402
from apps.harness.receipts import (  # noqa: E402
    HarnessReceiptError,
    aggregate_cost,
    load_receipt,
    verify_receipt_binding,
)
from apps.harness.runtime_manifest import (  # noqa: E402
    RuntimeManifest,
    RuntimeManifestError,
    load_runtime_manifest,
)
from apps.population.contract import (  # noqa: E402
    RESOURCE_NAMES,
    RequestError,
    normalize_resources,
)


class EvidenceAdapterError(RuntimeError):
    """Raised when Controller traces do not authenticate harness resources."""


def _configuration() -> tuple[Path, RuntimeManifest]:
    receipts = os.environ.get("METERING_HARNESS_RECEIPT_DIR")
    manifest = os.environ.get("METERING_HARNESS_RUNTIME_MANIFEST")
    if not receipts or not manifest:
        raise EvidenceAdapterError(
            "harness receipt directory and runtime manifest must be configured"
        )
    return Path(receipts), load_runtime_manifest(Path(manifest))


def _report(result: dict[str, object], name: str) -> dict[str, object]:
    value = result.get(name)
    if type(value) is not dict:
        raise EvidenceAdapterError(f"Controller result omitted {name}")
    return value


def _candidate_receipts(
    result: dict[str, object],
    candidate_id: str,
    receipt_root: Path,
    runtime: RuntimeManifest,
) -> tuple[list[dict[str, object]], list[str], list[dict[str, int]]]:
    traces = result.get("cases")
    if type(traces) is not list:
        raise EvidenceAdapterError("Controller result.cases must be an array")
    receipts: list[dict[str, object]] = []
    digests: list[str] = []
    evaluation_costs: list[dict[str, int]] = []
    for trace in traces:
        if type(trace) is not dict:
            raise EvidenceAdapterError("Controller case trace is malformed")
        matched = False
        for key in ("incumbent_run", "challenger_run"):
            run = trace.get(key)
            if type(run) is not dict or run.get("candidate_id") != candidate_id:
                continue
            matched = True
            task = run.get("task")
            runner = run.get("runner")
            forecast = run.get("forecast")
            if (
                type(task) is not dict
                or type(runner) is not dict
                or type(forecast) is not dict
                or set(forecast) != {"entropy", "outcomes"}
            ):
                raise EvidenceAdapterError("Controller candidate run is malformed")
            submission = runner.get("submission")
            if type(submission) is not dict:
                raise EvidenceAdapterError("harness submission is not a JSON object")
            metadata = submission.get(EVIDENCE_KEY)
            if type(metadata) is not dict or set(metadata) != {
                "manifest_id",
                "receipt",
                "runtime_id",
            }:
                raise EvidenceAdapterError(
                    "harness submission receipt metadata is malformed"
                )
            runtime_id = runtime.runtime_id
            if metadata["runtime_id"] != runtime_id:
                raise EvidenceAdapterError(
                    "harness submission changed runtime identity"
                )
            reference = metadata["receipt"]
            if type(reference) is not dict:
                raise EvidenceAdapterError("harness receipt reference is malformed")
            receipt = load_receipt(reference, receipt_root)
            task_input = task.get("input")
            case_id = task.get("case_id")
            if type(task_input) is not dict or type(case_id) is not str:
                raise EvidenceAdapterError("Controller harness task is malformed")
            observer = trace.get("observer_evaluation")
            if type(observer) is not dict or type(observer.get("results")) is not list:
                raise EvidenceAdapterError("Controller evaluator result is malformed")
            matches = [
                item
                for item in observer["results"]
                if type(item) is dict and item.get("candidate_id") == candidate_id
            ]
            if len(matches) != 1 or type(matches[0].get("evidence")) is not dict:
                raise EvidenceAdapterError("Controller evaluator candidate is absent")
            evaluator_evidence = matches[0]["evidence"]
            assert type(evaluator_evidence) is dict
            if "workspace" in task_input:
                try:
                    evaluation_costs.append(
                        normalize_resources(
                            evaluator_evidence.get("cost"),
                            "coding evaluator evidence.cost",
                            positive=False,
                        )
                    )
                except (RequestError, ValueError) as exc:
                    raise EvidenceAdapterError(str(exc)) from exc
            else:
                evaluation_costs.append({name: 0 for name in RESOURCE_NAMES})
            clean_submission = {
                name: value
                for name, value in submission.items()
                if name != EVIDENCE_KEY
            }
            try:
                verify_receipt_binding(
                    receipt,
                    candidate_id=candidate_id,
                    case_id=case_id,
                    task=task_input,
                    manifest_id=str(metadata["manifest_id"]),
                    runtime=runtime,
                    forecast={"outcomes": forecast["outcomes"]},
                    submission=clean_submission,
                )
            except HarnessReceiptError as exc:
                raise EvidenceAdapterError(str(exc)) from exc
            isolation = receipt["isolation"]
            if type(isolation) is not dict:
                raise EvidenceAdapterError(
                    "harness receipt isolation evidence is malformed"
                )
            if runtime.isolation_enforced and isolation.get("enforced") is not True:
                raise EvidenceAdapterError(
                    "live harness receipt lacks enforced isolation"
                )
            receipts.append(receipt)
            digest = reference.get("sha256")
            if type(digest) is not str:
                raise EvidenceAdapterError("harness receipt digest is malformed")
            digests.append(digest)
        if not matched:
            raise EvidenceAdapterError(
                f"Controller trace omitted candidate run {candidate_id}"
            )
    return receipts, digests, evaluation_costs


def adapt(request: dict[str, object]) -> dict[str, object]:
    if set(request) != {
        "controller_receipt",
        "controller_result",
        "experiment",
        "protocol_version",
        "round",
    }:
        raise EvidenceAdapterError("evidence adapter request has the wrong keys")
    if request["protocol_version"] != 1:
        raise EvidenceAdapterError("evidence adapter protocol_version must be 1")
    result = request["controller_result"]
    experiment = request["experiment"]
    if type(result) is not dict or type(experiment) is not dict:
        raise EvidenceAdapterError("evidence adapter request is malformed")
    specification = experiment.get("specification")
    if type(specification) is not dict:
        raise EvidenceAdapterError("Population experiment specification is malformed")
    receipt_root, runtime = _configuration()
    if specification.get("runtime_id") != runtime.runtime_id:
        raise EvidenceAdapterError("Population experiment changed runtime identity")
    candidates: list[dict[str, object]] = []
    for report_name in ("incumbent_report", "challenger_report"):
        report = _report(result, report_name)
        candidate_id = report.get("candidate")
        summary = report.get("task_summary")
        if type(candidate_id) is not str or type(summary) is not dict:
            raise EvidenceAdapterError(f"Controller {report_name} is malformed")
        passed = summary.get("passed_count")
        count = summary.get("case_count")
        safety = summary.get("safety_failures")
        if (
            type(passed) is not int
            or type(count) is not int
            or count < 1
            or type(safety) is not int
        ):
            raise EvidenceAdapterError(
                f"Controller {report_name} task summary is malformed"
            )
        receipts, digests, evaluation_costs = _candidate_receipts(
            result, candidate_id, receipt_root, runtime
        )
        if len(receipts) != count:
            raise EvidenceAdapterError(
                "harness receipt count does not match task assay"
            )
        rate = passed / count
        cost = aggregate_cost(receipts)
        for evaluation_cost in evaluation_costs:
            for name in RESOURCE_NAMES:
                cost[name] += evaluation_cost[name]
        candidates.append(
            {
                "behavior_distribution": [1.0 - rate, rate],
                "candidate_id": candidate_id,
                "cost": cost,
                "protected_passed": safety == 0,
                "seed": {
                    "receipt_sha256": sorted(digests),
                    "round": request["round"],
                    "runtime_id": runtime.runtime_id,
                },
            }
        )
    return {"candidates": candidates, "protocol_version": 1}


def main() -> int:
    try:
        request = decode_json_object(sys.stdin.read(), EvidenceAdapterError)
        response = adapt(request)
    except (
        EvidenceAdapterError,
        HarnessReceiptError,
        RuntimeManifestError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
