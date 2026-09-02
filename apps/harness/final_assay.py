"""Protected one-candidate final assay that permanently seals Population search."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from apps._support.wire import canonical_digest
from apps.agent_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    GIT_ADAPTER_PROTOCOL_VERSION,
    ProtocolError,
    decode_evaluator_result,
    decode_forecast_outcomes,
    run_adapter,
)
from apps.harness.harness_runner import EVIDENCE_KEY
from apps.harness.receipts import (
    HarnessReceiptError,
    aggregate_cost,
    load_receipt,
    verify_receipt_binding,
    write_receipt,
)
from apps.harness.runtime_manifest import RuntimeManifest
from apps.population.contract import (
    POPULATION_SCHEMA_VERSION,
    RESOURCE_NAMES,
    PopulationError,
    RequestError,
    append_validated_record,
    decode_allocation_request,
    decode_experiment_request,
    decode_run_request,
    load_state,
    locked_state,
    normalize_resources,
)

ROOT = Path(__file__).resolve().parents[2]


class FinalAssayError(RuntimeError):
    """Raised when protected final evidence cannot be sealed."""


def _select_final_candidate(
    population_root: Path,
    development_experiment_id: str,
    draw: dict[str, int],
) -> tuple[dict[str, object], str]:
    with locked_state(population_root):
        state = load_state(population_root)
        if state.final_evaluation_started or any(
            experiment["role"] == "final" for experiment in state.experiments.values()
        ):
            raise FinalAssayError("final evaluation already started")
        archive_id = state.latest_archive_by_experiment.get(development_experiment_id)
        if archive_id is None:
            raise FinalAssayError("development experiment has no retained archive")
        try:
            body = decode_allocation_request(
                {
                    "archive_record_id": archive_id,
                    "draw": draw,
                    "schema_version": POPULATION_SCHEMA_VERSION,
                },
                state,
            )
            archive_record = state.record(archive_id)
            assert archive_record is not None
            trailing = [
                (record_id, allocation)
                for record_id, allocation in state.allocations
                if int(cast(dict[str, object], state.record(record_id))["sequence"])
                > int(archive_record["sequence"])
            ]
            if trailing:
                if len(trailing) != 1 or trailing[0][1] != body:
                    raise FinalAssayError(
                        "development archive has a conflicting trailing allocation"
                    )
                allocation_id, allocation = trailing[0]
                result = cast(dict[str, object], allocation["result"])
                candidate_id = str(result["selected_candidate_id"])
                return state.candidates[candidate_id], allocation_id
            record = append_validated_record(population_root, state, "allocation", body)
        except (PopulationError, ValueError) as exc:
            raise FinalAssayError(str(exc)) from exc
        candidate_id = str(record["selected_candidate_id"])
        return state.candidates[candidate_id], str(record["record_id"])


def _append_final_experiment(
    population_root: Path,
    *,
    tasks: list[dict[str, object]],
    evaluator_command: list[str],
    runtime: RuntimeManifest,
    budget: dict[str, int],
) -> str:
    specification = {
        "behavior_space": ["fail", "pass"],
        "budget": budget,
        "case_count": len(tasks),
        "evaluator_id": canonical_digest({"command": evaluator_command}),
        "information_objective": False,
        "role": "final",
        "runtime_id": runtime.runtime_id,
        "task_set_id": canonical_digest(
            {"task_set_schema": "protected-harness-final-v1", "tasks": tasks}
        ),
    }
    with locked_state(population_root):
        state = load_state(population_root)
        if any(
            experiment["role"] == "final" for experiment in state.experiments.values()
        ):
            raise FinalAssayError(
                "protected final evaluation already started; its task set is one-use"
            )
        try:
            body = decode_experiment_request(
                {
                    "experiment": specification,
                    "schema_version": POPULATION_SCHEMA_VERSION,
                }
            )
            append_validated_record(population_root, state, "experiment", body)
        except (PopulationError, ValueError) as exc:
            raise FinalAssayError(str(exc)) from exc
    return str(body["experiment_id"])


def _run_case(
    candidate: dict[str, object],
    task: dict[str, object],
    *,
    runner_command: list[str],
    evaluator_command: list[str],
    runner_timeout: int,
    evaluator_timeout: int,
    evaluation: str,
    receipt_root: Path,
    runtime: RuntimeManifest,
) -> dict[str, object]:
    try:
        response = run_adapter(
            "protected final harness runner",
            runner_command,
            {
                "candidate": candidate,
                "protocol_version": GIT_ADAPTER_PROTOCOL_VERSION,
                "task": task,
            },
            timeout_seconds=runner_timeout,
            cwd=ROOT,
        )
        if set(response) != {"forecast", "submission"}:
            raise ProtocolError("final runner response has the wrong keys")
        forecast = response["forecast"]
        submission = response["submission"]
        if type(forecast) is not dict or set(forecast) != {"outcomes"}:
            raise ProtocolError("final runner forecast is malformed")
        outcomes = decode_forecast_outcomes(forecast["outcomes"], "final forecast")
        if type(submission) is not dict:
            raise ProtocolError("final submission must be a JSON object")
        metadata = submission.get(EVIDENCE_KEY)
        if type(metadata) is not dict or set(metadata) != {
            "manifest_id",
            "receipt",
            "runtime_id",
        }:
            raise ProtocolError("final submission omitted harness receipt metadata")
        if metadata["runtime_id"] != runtime.runtime_id:
            raise ProtocolError("final submission changed runtime identity")
        reference = metadata["receipt"]
        if type(reference) is not dict:
            raise ProtocolError("final harness receipt reference is malformed")
        receipt = load_receipt(reference, receipt_root)
        candidate_id = str(candidate["candidate_id"])
        case_id = task.get("case_id")
        task_input = task.get("input")
        if type(case_id) is not str or type(task_input) is not dict:
            raise ProtocolError("final harness task is malformed")
        clean_submission = {
            name: value for name, value in submission.items() if name != EVIDENCE_KEY
        }
        verify_receipt_binding(
            receipt,
            candidate_id=candidate_id,
            case_id=case_id,
            task=task_input,
            manifest_id=str(metadata["manifest_id"]),
            runtime=runtime,
            forecast={"outcomes": outcomes},
            submission=clean_submission,
        )
        evaluator = run_adapter(
            "protected final evaluator",
            evaluator_command,
            {
                "case": task,
                "evaluation": evaluation,
                "protocol_version": ADAPTER_PROTOCOL_VERSION,
                "submissions": [
                    {"candidate_id": candidate_id, "submission": submission}
                ],
            },
            timeout_seconds=evaluator_timeout,
            cwd=ROOT,
        )
        if set(evaluator) != {"results"} or type(evaluator["results"]) is not list:
            raise ProtocolError("final evaluator response is malformed")
        raw_results = evaluator["results"]
        if len(raw_results) != 1:
            raise ProtocolError("final evaluator must return exactly one result")
        result = decode_evaluator_result(raw_results[0], "final evaluator result")
        if result["candidate_id"] != candidate_id:
            raise ProtocolError("final evaluator changed candidate identity")
    except (HarnessReceiptError, ProtocolError) as exc:
        raise FinalAssayError(str(exc)) from exc
    probability_by_outcome = {
        str(item["outcome"]): float(item["probability"]) for item in outcomes
    }
    outcome = str(result["outcome"])
    if outcome not in probability_by_outcome:
        raise FinalAssayError("final forecast omitted the observed outcome")
    return {
        "case_id": task["case_id"],
        "evidence": result["evidence"],
        "forecast": {"outcomes": outcomes},
        "outcome": outcome,
        "passed": result["passed"],
        "receipt": reference,
        "receipt_document": receipt,
        "result_sha256": cast(dict[str, object], receipt["completion"])[
            "result_sha256"
        ],
        "safety_passed": result["safety_passed"],
        "submission": clean_submission,
        "target_probability": probability_by_outcome[outcome],
    }


def run_final_assay(
    population_root: Path,
    *,
    development_experiment_id: str,
    tasks: list[dict[str, object]],
    final_draw: dict[str, int],
    runner_command: list[str],
    evaluator_command: list[str],
    runner_timeout: int,
    evaluator_timeout: int,
    runtime: RuntimeManifest,
    receipt_root: Path,
    budget: dict[str, int],
) -> dict[str, object]:
    """Select once, assay protected tasks, append one final run, and seal."""

    candidate, allocation_record_id = _select_final_candidate(
        population_root, development_experiment_id, final_draw
    )
    experiment_id = _append_final_experiment(
        population_root,
        tasks=tasks,
        evaluator_command=evaluator_command,
        runtime=runtime,
        budget=budget,
    )
    evaluation = "evolutionary-harness/protected-final-v1"
    cases = [
        _run_case(
            candidate,
            task,
            runner_command=runner_command,
            evaluator_command=evaluator_command,
            runner_timeout=runner_timeout,
            evaluator_timeout=evaluator_timeout,
            evaluation=evaluation,
            receipt_root=receipt_root,
            runtime=runtime,
        )
        for task in tasks
    ]
    receipts = [cast(dict[str, object], item["receipt_document"]) for item in cases]
    passed = sum(int(item["passed"] is True) for item in cases)
    safety_failures = sum(int(item["safety_passed"] is not True) for item in cases)
    bundle = {
        "allocation_record_id": allocation_record_id,
        "candidate_id": candidate["candidate_id"],
        "cases": [
            {
                "case_id": item["case_id"],
                "evidence": item["evidence"],
                "forecast": item["forecast"],
                "outcome": item["outcome"],
                "passed": item["passed"],
                "receipt": item["receipt"],
                "result_sha256": item["result_sha256"],
                "safety_passed": item["safety_passed"],
                "submission": item["submission"],
                "target_probability": item["target_probability"],
            }
            for item in cases
        ],
        "evaluator_id": canonical_digest({"command": evaluator_command}),
        "final_assay_schema": "evolutionary-harness-final-assay-v1",
        "runtime_id": runtime.runtime_id,
    }
    bundle_reference = write_receipt(receipt_root, bundle)
    count = len(cases)
    final_cost = aggregate_cost(receipts)
    for case in cases:
        evidence = cast(dict[str, object], case["evidence"])
        if "cost" not in evidence:
            continue
        try:
            evaluator_cost = normalize_resources(
                evidence["cost"],
                "protected evaluator evidence.cost",
                positive=False,
            )
        except (RequestError, ValueError) as exc:
            raise FinalAssayError(str(exc)) from exc
        for name in RESOURCE_NAMES:
            final_cost[name] += evaluator_cost[name]
    run_request = {
        "candidate_id": candidate["candidate_id"],
        "evidence": {
            "behavior_distribution": [1.0 - passed / count, passed / count],
            "cost": final_cost,
            "evidence_receipt": bundle_reference,
            "information_model": None,
            "protected_passed": safety_failures == 0,
            "target_probabilities": [item["target_probability"] for item in cases],
            "task": {
                "case_count": count,
                "passed_count": passed,
                "safety_failures": safety_failures,
            },
        },
        "experiment_id": experiment_id,
        "replicate_id": "protected-final-000001",
        "schema_version": POPULATION_SCHEMA_VERSION,
        "seed": {
            "allocation_record_id": allocation_record_id,
            "draw": final_draw,
        },
    }
    with locked_state(population_root):
        state = load_state(population_root)
        try:
            body = decode_run_request(run_request, state)
            record = append_validated_record(population_root, state, "run", body)
        except (PopulationError, ValueError) as exc:
            raise FinalAssayError(str(exc)) from exc
    return {
        "allocation_record_id": allocation_record_id,
        "candidate_id": candidate["candidate_id"],
        "experiment_id": experiment_id,
        "passed_count": passed,
        "receipt": bundle_reference,
        "run_record_id": record["record_id"],
        "safety_failures": safety_failures,
        "task_count": count,
    }
