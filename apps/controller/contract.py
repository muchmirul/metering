"""Pure schema-v2 Controller request/result replay contract.

This module performs no model, runner, evaluator, filesystem, or SQLite calls.
Controller and outer sequencers share it so Controller remains the sole owner of
one-generation composition evidence.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import cast

from apps.agent_protocol import (
    AGENT_SCHEMA_VERSION,
    ProtocolError,
    candidate_record,
    decode_candidate,
    decode_candidate_run,
    decode_observer_evaluation,
    decode_task,
    normalize_json_value,
    probability,
    require_bool,
    require_exact_keys,
    require_nonempty_string,
    require_sha256,
)
from apps.selection_gate.task_selection import select_task_reports
from apps._support.wire import (
    canonical_digest,
    canonical_json,
)


class ControllerReceiptError(RuntimeError):
    """Raised when a stored Controller generation does not replay."""


def agent_generation_timeout_seconds(
    *,
    proposer_timeout_seconds: int,
    runner_timeout_seconds: int,
    evaluator_timeout_seconds: int,
    task_count: int,
) -> int:
    """Return the outer timeout for one sequential schema-v2 generation."""

    margin = 10
    return (
        proposer_timeout_seconds
        + margin
        + task_count
        * (2 * (runner_timeout_seconds + margin) + evaluator_timeout_seconds + margin)
        + 4 * margin
    )


def _validated_report_cases(
    report: dict[str, object],
    candidate_id: str,
    tasks: list[dict[str, object]],
    evaluation: str,
    location: str,
) -> dict[str, object]:
    if report.get("candidate") != candidate_id:
        raise ControllerReceiptError(f"{location}.candidate does not match")
    if report.get("evaluation") != evaluation:
        raise ControllerReceiptError(f"{location}.evaluation does not match")
    raw_cases = report.get("cases")
    if type(raw_cases) is not list or len(raw_cases) != len(tasks):
        raise ControllerReceiptError(
            f"{location}.cases must match the configured task count"
        )
    expected_ids = [str(task["case_id"]) for task in tasks]
    observed_ids: list[str] = []
    probabilities: list[float] = []
    passed_count = 0
    safety_failures = 0
    normalized_cases: list[dict[str, object]] = []
    for index, raw_case in enumerate(raw_cases):
        case_location = f"{location}.cases[{index}]"
        if type(raw_case) is not dict:
            raise ControllerReceiptError(f"{case_location} must be a JSON object")
        try:
            require_exact_keys(
                raw_case,
                {
                    "case_id",
                    "evidence",
                    "outcome",
                    "passed",
                    "safety_passed",
                    "target_probability",
                    "target_surprisal",
                },
                case_location,
            )
            case_id = require_nonempty_string(
                raw_case["case_id"], f"{case_location}.case_id"
            )
            passed = require_bool(raw_case["passed"], f"{case_location}.passed")
            safety = require_bool(
                raw_case["safety_passed"], f"{case_location}.safety_passed"
            )
            target_probability = probability(
                raw_case["target_probability"],
                f"{case_location}.target_probability",
            )
            evidence = normalize_json_value(
                raw_case["evidence"], f"{case_location}.evidence"
            )
            outcome = require_nonempty_string(
                raw_case["outcome"], f"{case_location}.outcome"
            )
        except ProtocolError as exc:
            raise ControllerReceiptError(str(exc)) from exc
        observed_ids.append(case_id)
        probabilities.append(target_probability)
        passed_count += int(passed)
        safety_failures += int(not safety)
        normalized_cases.append(
            {
                "case_id": case_id,
                "evidence": evidence,
                "outcome": outcome,
                "passed": passed,
                "safety_passed": safety,
            }
        )
    if observed_ids != expected_ids:
        raise ControllerReceiptError(f"{location}.cases changed task ordering")
    expected_summary = {
        "case_count": len(tasks),
        "passed_count": passed_count,
        "safety_failures": safety_failures,
    }
    if report.get("task_summary") != expected_summary:
        raise ControllerReceiptError(f"{location}.task_summary does not match cases")
    return {
        "cases": normalized_cases,
        "target_probabilities": probabilities,
        "task": expected_summary,
    }


def validate_agent_generation_receipt(
    request: dict[str, object],
    result: dict[str, object],
) -> dict[str, object]:
    """Replay one complete schema-v2 Controller result without external calls."""

    expected_keys = {
        "cases",
        "challenger_report",
        "evaluation",
        "incumbent_report",
        "mutation",
        "next_parent",
        "schema_version",
        "selection",
    }
    if set(result) != expected_keys:
        raise ControllerReceiptError("Controller result has the wrong keys")
    if (
        result.get("schema_version") != AGENT_SCHEMA_VERSION
        or type(result.get("schema_version")) is not int
    ):
        raise ControllerReceiptError("Controller returned the wrong schema version")
    if result.get("evaluation") != request.get("evaluation"):
        raise ControllerReceiptError("Controller changed the evaluation identifier")
    mutation = result.get("mutation")
    if type(mutation) is not dict:
        raise ControllerReceiptError("Controller result.mutation is malformed")
    mutation_request = request.get("mutation_request")
    if type(mutation_request) is not dict:
        raise ControllerReceiptError("Controller request.mutation_request is malformed")
    try:
        parent = decode_candidate(mutation.get("parent"), "result.mutation.parent")
        child = decode_candidate(mutation.get("child"), "result.mutation.child")
        next_parent = decode_candidate(result.get("next_parent"), "result.next_parent")
        requested_parent = candidate_record(
            mutation_request["parent_artifact"],
            "request.mutation_request.parent_artifact",
        )
    except (KeyError, ProtocolError) as exc:
        raise ControllerReceiptError(str(exc)) from exc
    if parent != requested_parent:
        raise ControllerReceiptError("Controller changed the requested parent")
    if child["candidate_id"] == parent["candidate_id"]:
        raise ControllerReceiptError("Controller returned an unchanged child")
    if next_parent["candidate_id"] not in {
        parent["candidate_id"],
        child["candidate_id"],
    }:
        raise ControllerReceiptError("Controller selected an unknown candidate")

    policy = request.get("selection_policy")
    tasks = request.get("tasks")
    runner = request.get("runner")
    evaluator = request.get("evaluator")
    if (
        type(policy) is not dict
        or type(tasks) is not list
        or not tasks
        or type(runner) is not dict
        or type(evaluator) is not dict
        or type(runner.get("command")) is not list
        or type(evaluator.get("command")) is not list
    ):
        raise ControllerReceiptError("Controller request components are malformed")
    incumbent_report = result["incumbent_report"]
    challenger_report = result["challenger_report"]
    selection = result["selection"]
    if (
        type(incumbent_report) is not dict
        or type(challenger_report) is not dict
        or type(selection) is not dict
    ):
        raise ControllerReceiptError("Controller reports or selection are malformed")
    selection_request = {
        "challenger_report": challenger_report,
        "incumbent_report": incumbent_report,
        "policy": policy,
        "schema_version": AGENT_SCHEMA_VERSION,
    }
    exact_selection_request = json.loads(
        canonical_json(selection_request), parse_float=Decimal
    )
    try:
        expected_selection = select_task_reports(exact_selection_request)
    except (ProtocolError, ValueError) as exc:
        raise ControllerReceiptError(f"Controller reports are invalid: {exc}") from exc
    if canonical_json(selection) != canonical_json(expected_selection):
        raise ControllerReceiptError(
            "Controller selection does not replay from reports"
        )
    if selection["selected"] != next_parent["candidate_id"]:
        raise ControllerReceiptError("Controller selection does not match next_parent")

    normalized_tasks: list[dict[str, object]] = []
    try:
        for index, task in enumerate(tasks):
            normalized_tasks.append(decode_task(task, f"request.tasks[{index}]"))
    except ProtocolError as exc:
        raise ControllerReceiptError(str(exc)) from exc
    evaluation = request.get("evaluation")
    if type(evaluation) is not str or not evaluation:
        raise ControllerReceiptError("Controller request evaluation is malformed")
    parent_evidence = _validated_report_cases(
        incumbent_report,
        str(parent["candidate_id"]),
        normalized_tasks,
        evaluation,
        "incumbent_report",
    )
    child_evidence = _validated_report_cases(
        challenger_report,
        str(child["candidate_id"]),
        normalized_tasks,
        evaluation,
        "challenger_report",
    )

    raw_traces = result["cases"]
    if type(raw_traces) is not list or len(raw_traces) != len(normalized_tasks):
        raise ControllerReceiptError("Controller case traces do not match tasks")
    expected_evaluator_id = canonical_digest({"command": evaluator["command"]})
    expected_runner_id = canonical_digest({"command": runner["command"]})
    parent_cases = cast(list[dict[str, object]], parent_evidence["cases"])
    child_cases = cast(list[dict[str, object]], child_evidence["cases"])
    parent_probabilities = cast(list[float], parent_evidence["target_probabilities"])
    child_probabilities = cast(list[float], child_evidence["target_probabilities"])
    for index, (raw_trace, task) in enumerate(
        zip(raw_traces, normalized_tasks, strict=True)
    ):
        location = f"Controller cases[{index}]"
        if type(raw_trace) is not dict:
            raise ControllerReceiptError(f"{location} must be a JSON object")
        try:
            require_exact_keys(
                raw_trace,
                {"challenger_run", "incumbent_run", "observer_evaluation", "task"},
                location,
            )
            traced_task = decode_task(raw_trace["task"], f"{location}.task")
            incumbent_run = decode_candidate_run(
                raw_trace["incumbent_run"], f"{location}.incumbent_run"
            )
            challenger_run = decode_candidate_run(
                raw_trace["challenger_run"], f"{location}.challenger_run"
            )
            observation = decode_observer_evaluation(
                raw_trace["observer_evaluation"],
                f"{location}.observer_evaluation",
            )
        except ProtocolError as exc:
            raise ControllerReceiptError(str(exc)) from exc
        if traced_task != task:
            raise ControllerReceiptError(f"{location}.task changed")
        if incumbent_run["candidate_id"] != parent["candidate_id"]:
            raise ControllerReceiptError(f"{location} changed incumbent identity")
        if challenger_run["candidate_id"] != child["candidate_id"]:
            raise ControllerReceiptError(f"{location} changed challenger identity")
        for run, role in (
            (incumbent_run, "incumbent"),
            (challenger_run, "challenger"),
        ):
            if run["task"] != task:
                raise ControllerReceiptError(f"{location} changed {role} task")
            runner_receipt = cast(dict[str, object], run["runner"])
            if runner_receipt["adapter_id"] != expected_runner_id:
                raise ControllerReceiptError(
                    f"{location} changed {role} runner identity"
                )
        if observation["evaluator_id"] != expected_evaluator_id:
            raise ControllerReceiptError(f"{location} changed evaluator identity")
        if observation["evaluation"] != evaluation:
            raise ControllerReceiptError(f"{location} changed evaluation")
        if observation["case_id"] != task["case_id"]:
            raise ControllerReceiptError(f"{location} changed evaluation case")
        evaluation_results = cast(list[dict[str, object]], observation["results"])
        results_by_candidate = {
            str(item["candidate_id"]): item for item in evaluation_results
        }
        if set(results_by_candidate) != {
            str(parent["candidate_id"]),
            str(child["candidate_id"]),
        }:
            raise ControllerReceiptError(
                f"{location} evaluation results changed candidate identities"
            )
        for run, candidate_id, report_case, reported_probability in (
            (
                incumbent_run,
                str(parent["candidate_id"]),
                parent_cases[index],
                parent_probabilities[index],
            ),
            (
                challenger_run,
                str(child["candidate_id"]),
                child_cases[index],
                child_probabilities[index],
            ),
        ):
            evaluated = results_by_candidate[candidate_id]
            expected_case = {
                "case_id": task["case_id"],
                "evidence": evaluated["evidence"],
                "outcome": evaluated["outcome"],
                "passed": evaluated["passed"],
                "safety_passed": evaluated["safety_passed"],
            }
            if canonical_json(report_case) != canonical_json(expected_case):
                raise ControllerReceiptError(
                    f"{location} report does not match evaluator evidence"
                )
            forecast = cast(dict[str, object], run["forecast"])
            outcomes = cast(list[dict[str, object]], forecast["outcomes"])
            matching = [
                item for item in outcomes if item["outcome"] == evaluated["outcome"]
            ]
            if (
                len(matching) != 1
                or float(matching[0]["probability"]) != reported_probability
            ):
                raise ControllerReceiptError(
                    f"{location} report probability does not match forecast"
                )

    mutation_detail = mutation.get("mutation")
    if type(mutation_detail) is not dict:
        raise ControllerReceiptError("Controller mutation receipt is malformed")
    try:
        proposal_id = require_sha256(
            mutation_detail.get("proposal_id"),
            "result.mutation.mutation.proposal_id",
        )
    except ProtocolError as exc:
        raise ControllerReceiptError(str(exc)) from exc
    return {
        "child": child,
        "child_evidence": child_evidence,
        "next_parent": next_parent,
        "parent": parent,
        "parent_evidence": parent_evidence,
        "proposal_id": proposal_id,
        "selection": expected_selection,
    }
