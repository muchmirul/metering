"""Protected final assay for one preselected immutable solution commit."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

from apps._support.durable import atomic_write, reject_symlink
from apps._support.wire import canonical_digest, canonical_json
from apps.agent_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    GIT_ADAPTER_PROTOCOL_VERSION,
    ProtocolError,
    decode_evaluator_result,
    decode_forecast_outcomes,
    run_adapter,
)
from apps.coding_agent.candidate_runner import EVIDENCE_KEY
from apps.coding_agent.solution_evaluator import (
    SolutionEvaluatorError,
    load_evaluation_receipt,
    validate_evaluation_receipt,
)
from apps.population.contract import (
    POPULATION_SCHEMA_VERSION,
    RESOURCE_NAMES,
    PopulationError,
    append_validated_record,
    decode_allocation_request,
    decode_experiment_request,
    decode_run_request,
    load_state,
    locked_state,
)

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_SCHEMA = "darwinian-coding-final-assay-v1"


class CodingFinalError(RuntimeError):
    """Raised when protected solution evidence cannot be sealed safely."""


def _select(
    population_root: Path, development_experiment_id: str, tie_draw: dict[str, int]
) -> tuple[dict[str, object], str, dict[str, int], list[str]]:
    with locked_state(population_root):
        state = load_state(population_root)
        if state.final_evaluation_started or any(
            experiment["role"] == "final" for experiment in state.experiments.values()
        ):
            raise CodingFinalError("final coding evaluation already started")
        archive_id = state.latest_archive_by_experiment.get(development_experiment_id)
        if archive_id is None:
            raise CodingFinalError("development experiment has no retained archive")
        archive = cast(dict[str, object], state.record(archive_id)["body"])
        members = cast(list[dict[str, object]], archive["members"])
        if not members:
            raise CodingFinalError("development archive has no feasible candidate")
        best_rate = max(
            float(cast(dict[str, object], member["task"])["rate"]) for member in members
        )
        best_reliability = max(
            float(member["reliability"])
            for member in members
            if float(cast(dict[str, object], member["task"])["rate"]) == best_rate
        )
        eligible = sorted(
            str(member["candidate_id"])
            for member in members
            if float(cast(dict[str, object], member["task"])["rate"]) == best_rate
            and float(member["reliability"]) == best_reliability
        )
        tie_index = (int(tie_draw["numerator"]) * len(eligible)) // int(
            tie_draw["denominator"]
        )
        selected = eligible[tie_index]
        all_candidates = sorted(str(member["candidate_id"]) for member in members)
        full_index = all_candidates.index(selected)
        allocation_draw = {
            "denominator": len(all_candidates),
            "numerator": full_index,
        }
        try:
            body = decode_allocation_request(
                {
                    "archive_record_id": archive_id,
                    "draw": allocation_draw,
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
                    raise CodingFinalError(
                        "development archive has a conflicting trailing allocation"
                    )
                allocation_id, allocation = trailing[0]
                result = cast(dict[str, object], allocation["result"])
                candidate_id = str(result["selected_candidate_id"])
                if candidate_id != selected:
                    raise CodingFinalError(
                        "capability-first allocation selected another candidate"
                    )
                return (
                    state.candidates[candidate_id],
                    allocation_id,
                    allocation_draw,
                    eligible,
                )
            record = append_validated_record(population_root, state, "allocation", body)
        except (PopulationError, ValueError) as exc:
            raise CodingFinalError(str(exc)) from exc
        candidate_id = str(record["selected_candidate_id"])
        if candidate_id != selected:
            raise CodingFinalError(
                "capability-first allocation selected another candidate"
            )
        return (
            state.candidates[candidate_id],
            str(record["record_id"]),
            allocation_draw,
            eligible,
        )


def _experiment(
    population_root: Path,
    *,
    tasks: list[dict[str, object]],
    evaluator_command: list[str],
    runtime_id: str,
    budget: dict[str, int],
) -> str:
    specification = {
        "behavior_space": ["fail", "pass"],
        "budget": budget,
        "case_count": len(tasks),
        "evaluator_id": canonical_digest({"command": evaluator_command}),
        "information_objective": False,
        "role": "final",
        "runtime_id": runtime_id,
        "task_set_id": canonical_digest(
            {"task_set_schema": "protected-darwinian-coding-final-v1", "tasks": tasks}
        ),
    }
    with locked_state(population_root):
        state = load_state(population_root)
        if any(
            experiment["role"] == "final" for experiment in state.experiments.values()
        ):
            raise CodingFinalError("protected coding final task set is one-use")
        try:
            body = decode_experiment_request(
                {
                    "experiment": specification,
                    "schema_version": POPULATION_SCHEMA_VERSION,
                }
            )
            append_validated_record(population_root, state, "experiment", body)
        except (PopulationError, ValueError) as exc:
            raise CodingFinalError(str(exc)) from exc
    return str(body["experiment_id"])


def _case(
    candidate: dict[str, object],
    task: dict[str, object],
    *,
    runner_command: list[str],
    evaluator_command: list[str],
    runner_timeout: int,
    evaluator_timeout: int,
    runtime_id: str,
) -> dict[str, object]:
    try:
        response = run_adapter(
            "protected final solution runner",
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
            raise ProtocolError("final solution runner response has the wrong keys")
        forecast = response["forecast"]
        submission = response["submission"]
        if type(forecast) is not dict or set(forecast) != {"outcomes"}:
            raise ProtocolError("final solution forecast is malformed")
        outcomes = decode_forecast_outcomes(forecast["outcomes"], "final forecast")
        if type(submission) is not dict:
            raise ProtocolError("final solution submission must be a JSON object")
        metadata = submission.get(EVIDENCE_KEY)
        if type(metadata) is not dict or set(metadata) != {"receipt", "runtime_id"}:
            raise ProtocolError("final solution omitted execution receipt metadata")
        reference = metadata["receipt"]
        candidate_id = str(candidate["candidate_id"])
        receipt, receipt_digest = load_evaluation_receipt(reference)
        validate_evaluation_receipt(
            receipt,
            candidate_id=candidate_id,
            task=task,
            runtime_id=str(metadata["runtime_id"]),
        )
        evaluator = run_adapter(
            "protected final solution evaluator",
            evaluator_command,
            {
                "case": task,
                "evaluation": "darwinian-coding/protected-final-v1",
                "protocol_version": ADAPTER_PROTOCOL_VERSION,
                "submissions": [
                    {"candidate_id": candidate_id, "submission": submission}
                ],
            },
            timeout_seconds=evaluator_timeout,
            cwd=ROOT,
        )
        if set(evaluator) != {"results"} or type(evaluator["results"]) is not list:
            raise ProtocolError("final solution evaluator response is malformed")
        raw_results = evaluator["results"]
        if len(raw_results) != 1:
            raise ProtocolError("final solution evaluator must return one result")
        result = decode_evaluator_result(raw_results[0], "final solution result")
        if result["candidate_id"] != candidate_id:
            raise ProtocolError("final solution evaluator changed candidate identity")
    except (ProtocolError, SolutionEvaluatorError) as exc:
        raise CodingFinalError(str(exc)) from exc
    probability = {
        str(item["outcome"]): float(item["probability"]) for item in outcomes
    }
    outcome = str(result["outcome"])
    if outcome not in probability:
        raise CodingFinalError("final solution forecast omitted observed outcome")
    return {
        "case_id": task["case_id"],
        "evidence": result["evidence"],
        "forecast": {"outcomes": outcomes},
        "outcome": outcome,
        "passed": result["passed"],
        "receipt": reference,
        "receipt_document": receipt,
        "receipt_sha256": receipt_digest,
        "result_sha256": canonical_digest(
            {"forecast": {"outcomes": outcomes}, "submission": submission}
        ),
        "safety_passed": result["safety_passed"],
        "target_probability": probability[outcome],
    }


def _aggregate(receipts: list[dict[str, object]]) -> dict[str, int]:
    total = {name: 0 for name in RESOURCE_NAMES}
    for receipt in receipts:
        cost = receipt["cost"]
        assert type(cost) is dict
        for name in RESOURCE_NAMES:
            total[name] += int(cost[name])
    return total


def _write_bundle(root: Path, document: dict[str, object]) -> dict[str, str]:
    root = root.expanduser().absolute()
    reject_symlink(root, "coding final receipt directory", CodingFinalError)
    root.mkdir(parents=True, exist_ok=True)
    source = (canonical_json(document) + "\n").encode("ascii")
    digest = hashlib.sha256(source).hexdigest()
    path = root / f"{digest}.json"
    reject_symlink(path, "coding final receipt", CodingFinalError)
    if path.exists():
        if path.read_bytes() != source:
            raise CodingFinalError("coding final receipt identity conflicts")
    else:
        atomic_write(path, source)
    return {"sha256": digest, "uri": path.as_uri()}


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
    runtime_id: str,
    bundle_root: Path,
    budget: dict[str, int],
) -> dict[str, object]:
    candidate, allocation_id, allocation_draw, finalists = _select(
        population_root, development_experiment_id, final_draw
    )
    experiment_id = _experiment(
        population_root,
        tasks=tasks,
        evaluator_command=evaluator_command,
        runtime_id=runtime_id,
        budget=budget,
    )
    cases = [
        _case(
            candidate,
            task,
            runner_command=runner_command,
            evaluator_command=evaluator_command,
            runner_timeout=runner_timeout,
            evaluator_timeout=evaluator_timeout,
            runtime_id=runtime_id,
        )
        for task in tasks
    ]
    passed = sum(int(item["passed"] is True) for item in cases)
    safety_failures = sum(int(item["safety_passed"] is not True) for item in cases)
    bundle = {
        "allocation_record_id": allocation_id,
        "candidate_id": candidate["candidate_id"],
        "cases": [
            {name: value for name, value in item.items() if name != "receipt_document"}
            for item in cases
        ],
        "evaluator_id": canonical_digest({"command": evaluator_command}),
        "final_assay_schema": BUNDLE_SCHEMA,
        "selection": {
            "allocation_draw": allocation_draw,
            "eligible_candidate_ids": finalists,
            "policy": "development-task-rate-reliability-v1",
            "tie_draw": final_draw,
        },
        "runtime_id": runtime_id,
    }
    bundle_reference = _write_bundle(bundle_root, bundle)
    count = len(cases)
    run_request = {
        "candidate_id": candidate["candidate_id"],
        "evidence": {
            "behavior_distribution": [1.0 - passed / count, passed / count],
            "cost": _aggregate(
                [cast(dict[str, object], item["receipt_document"]) for item in cases]
            ),
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
            "allocation_record_id": allocation_id,
            "allocation_draw": allocation_draw,
            "selection_policy": "development-task-rate-reliability-v1",
            "tie_draw": final_draw,
        },
    }
    with locked_state(population_root):
        state = load_state(population_root)
        try:
            body = decode_run_request(run_request, state)
            record = append_validated_record(population_root, state, "run", body)
        except (PopulationError, ValueError) as exc:
            raise CodingFinalError(str(exc)) from exc
    return {
        "allocation_record_id": allocation_id,
        "candidate_id": candidate["candidate_id"],
        "experiment_id": experiment_id,
        "passed_count": passed,
        "receipt": bundle_reference,
        "selection_policy": "development-task-rate-reliability-v1",
        "run_record_id": record["record_id"],
        "safety_failures": safety_failures,
        "task_count": count,
    }
