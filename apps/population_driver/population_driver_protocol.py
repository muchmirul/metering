"""Strict request, Controller, and evidence contracts for Population Driver."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = ROOT / "apps"
CONTROLLER_ROOT = APPS_ROOT / "controller"
POPULATION_ROOT = APPS_ROOT / "population"
SELECTION_ROOT = APPS_ROOT / "selection_gate"
for import_root in (
    APPS_ROOT,
    CONTROLLER_ROOT,
    POPULATION_ROOT,
    SELECTION_ROOT,
):
    if str(import_root) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(import_root))

from agent_protocol import (  # noqa: E402
    AGENT_SCHEMA_VERSION,
    GIT_ARTIFACT_SCHEMA,
    ProtocolError,
    candidate_record,
    decode_candidate,
    decode_candidate_run,
    decode_command,
    decode_observer_evaluation,
    decode_task,
    normalize_json_value,
    probability,
    require_bool,
    require_exact_keys,
    require_nonempty_string,
    require_sha256,
    require_timeout,
)
from component_runtime import agent_generation_timeout_seconds  # noqa: E402
from population_policy import _draw  # noqa: E402
from population_protocol import (  # noqa: E402
    MAX_PROTOCOL_INTEGER,
    POPULATION_SCHEMA_VERSION,
    RESOURCE_NAMES,
    RequestError as PopulationRequestError,
    _distribution,
    _resources,
    decode_experiment_request,
    decode_initialize_request,
)
from stdio_connector import (  # noqa: E402
    canonical_digest,
    canonical_json,
    decode_json_object,
)
from task_selection import select_task_reports  # noqa: E402

DRIVER_SCHEMA_VERSION = 1
EVIDENCE_ADAPTER_PROTOCOL_VERSION = 1
TASK_SET_SCHEMA = "population-driver-task-set-v1"
MUTATION_POLICY_SCHEMA = "population-driver-mutation-policy-v1"
CONTROLLER_RECEIPT_SCHEMA = "population-driver-controller-receipt-v1"
EVIDENCE_RECEIPT_SCHEMA = "population-driver-evidence-receipt-v1"


class RequestError(ValueError):
    """Raised when a Population Driver request is malformed."""


class PopulationDriverError(RuntimeError):
    """Raised when Population Driver state or composition is invalid."""


def _positive_integer(value: object, location: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_PROTOCOL_INTEGER:
        raise ProtocolError(
            f"{location} must be a positive integer no greater than "
            f"{MAX_PROTOCOL_INTEGER}"
        )
    return value


def _component(value: object, location: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(value, {"command", "timeout_seconds"}, location)
    return {
        "command": decode_command(value["command"], f"{location}.command"),
        "timeout_seconds": require_timeout(
            value["timeout_seconds"], f"{location}.timeout_seconds"
        ),
    }


def _selection_policy(value: object, location: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(
        value,
        {"minimum_pass_improvement", "reject_safety_regression", "type"},
        location,
    )
    if value["type"] != "task-pass-count-v1":
        raise ProtocolError(f"{location}.type must be task-pass-count-v1")
    return {
        "minimum_pass_improvement": _positive_integer(
            value["minimum_pass_improvement"],
            f"{location}.minimum_pass_improvement",
        ),
        "reject_safety_regression": require_bool(
            value["reject_safety_regression"],
            f"{location}.reject_safety_regression",
        ),
        "type": "task-pass-count-v1",
    }


def _tasks(value: object, location: str) -> list[dict[str, object]]:
    if type(value) is not list or not value:
        raise ProtocolError(f"{location} must be a non-empty JSON array")
    tasks: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw_task in enumerate(value):
        task = decode_task(raw_task, f"{location}[{index}]")
        case_id = str(task["case_id"])
        if case_id in seen:
            raise ProtocolError(f"{location} contains duplicate case: {case_id}")
        seen.add(case_id)
        tasks.append(task)
    return tasks


def _draws(value: object, count: int, location: str) -> list[dict[str, int]]:
    if type(value) is not list or len(value) != count:
        raise ProtocolError(f"{location} must contain exactly {count} draws")
    return [_draw(item, f"{location}[{index}]") for index, item in enumerate(value)]


def _limits(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError("limits must be a JSON object")
    require_exact_keys(
        value,
        {
            "max_proposal_calls",
            "max_rounds",
            "max_total_candidate_cost",
            "max_wall_seconds",
        },
        "limits",
    )
    rounds = _positive_integer(value["max_rounds"], "limits.max_rounds")
    proposals = _positive_integer(
        value["max_proposal_calls"], "limits.max_proposal_calls"
    )
    if proposals < rounds:
        raise ProtocolError(
            "limits.max_proposal_calls must be at least limits.max_rounds"
        )
    return {
        "max_proposal_calls": proposals,
        "max_rounds": rounds,
        "max_total_candidate_cost": _resources(
            value["max_total_candidate_cost"],
            "limits.max_total_candidate_cost",
            positive=False,
        ),
        "max_wall_seconds": _positive_integer(
            value["max_wall_seconds"], "limits.max_wall_seconds"
        ),
    }


def decode_request(source: str) -> dict[str, object]:
    request = decode_json_object(source, RequestError)
    try:
        require_exact_keys(
            request,
            {
                "allocation_draws",
                "evidence_adapter",
                "generation",
                "initial_parent_artifact",
                "limits",
                "population",
                "proposal",
                "schema_version",
            },
            "request",
        )
        if (
            type(request["schema_version"]) is not int
            or request["schema_version"] != DRIVER_SCHEMA_VERSION
        ):
            raise ProtocolError(
                f"request.schema_version must be {DRIVER_SCHEMA_VERSION}"
            )

        initial_parent = candidate_record(
            request["initial_parent_artifact"], "initial_parent_artifact"
        )
        initial_artifact = cast(dict[str, object], initial_parent["artifact"])
        if initial_artifact["artifact_schema"] != GIT_ARTIFACT_SCHEMA:
            raise ProtocolError(
                "initial_parent_artifact must be a git-candidate-v1 artifact"
            )

        proposal = request["proposal"]
        if type(proposal) is not dict:
            raise ProtocolError("proposal must be a JSON object")
        require_exact_keys(
            proposal, {"command", "context", "timeout_seconds"}, "proposal"
        )
        context = normalize_json_value(proposal["context"], "proposal.context")
        if type(context) is not dict:
            raise ProtocolError("proposal.context must be a JSON object")
        proposal_document = {
            "command": decode_command(proposal["command"], "proposal.command"),
            "context": context,
            "timeout_seconds": require_timeout(
                proposal["timeout_seconds"], "proposal.timeout_seconds"
            ),
        }

        generation = request["generation"]
        if type(generation) is not dict:
            raise ProtocolError("generation must be a JSON object")
        require_exact_keys(
            generation,
            {"evaluation", "evaluator", "runner", "selection_policy", "tasks"},
            "generation",
        )
        evaluation = require_nonempty_string(
            generation["evaluation"], "generation.evaluation"
        )
        evaluator = _component(generation["evaluator"], "generation.evaluator")
        runner = _component(generation["runner"], "generation.runner")
        tasks = _tasks(generation["tasks"], "generation.tasks")
        generation_document = {
            "evaluation": evaluation,
            "evaluator": evaluator,
            "runner": runner,
            "selection_policy": _selection_policy(
                generation["selection_policy"], "generation.selection_policy"
            ),
            "tasks": tasks,
        }

        population = request["population"]
        if type(population) is not dict:
            raise ProtocolError("population must be a JSON object")
        require_exact_keys(population, {"configuration", "development"}, "population")
        configuration = decode_initialize_request(
            {
                "configuration": population["configuration"],
                "schema_version": POPULATION_SCHEMA_VERSION,
            }
        )
        development = population["development"]
        if type(development) is not dict:
            raise ProtocolError("population.development must be a JSON object")
        require_exact_keys(
            development,
            {"behavior_space", "budget", "runtime_id"},
            "population.development",
        )
        experiment_document = decode_experiment_request(
            {
                "experiment": {
                    "behavior_space": development["behavior_space"],
                    "budget": development["budget"],
                    "case_count": len(tasks),
                    "evaluator_id": canonical_digest({"command": evaluator["command"]}),
                    "information_objective": False,
                    "role": "development",
                    "runtime_id": development["runtime_id"],
                    "task_set_id": canonical_digest(
                        {
                            "evaluation": evaluation,
                            "task_set_schema": TASK_SET_SCHEMA,
                            "tasks": tasks,
                        }
                    ),
                },
                "schema_version": POPULATION_SCHEMA_VERSION,
            }
        )
        population_document = {
            "configuration": configuration,
            "experiment": experiment_document["experiment"],
            "experiment_id": experiment_document["experiment_id"],
        }

        evidence_adapter = _component(request["evidence_adapter"], "evidence_adapter")
        limits = _limits(request["limits"])
        rounds = int(limits["max_rounds"])
        draws = _draws(request["allocation_draws"], rounds - 1, "allocation_draws")
    except (ProtocolError, PopulationRequestError) as exc:
        raise RequestError(str(exc)) from exc

    mutation_policy_id = canonical_digest(
        {
            "command": proposal_document["command"],
            "context": proposal_document["context"],
            "mutation_policy_schema": MUTATION_POLICY_SCHEMA,
            "timeout_seconds": proposal_document["timeout_seconds"],
        }
    )
    return {
        "allocation_draws": draws,
        "evidence_adapter": evidence_adapter,
        "generation": generation_document,
        "initial_parent": initial_parent,
        "limits": limits,
        "mutation_policy_id": mutation_policy_id,
        "population": population_document,
        "proposal": proposal_document,
        "schema_version": DRIVER_SCHEMA_VERSION,
    }


def validate_normalized_config(value: object) -> dict[str, object]:
    """Reconstruct and validate one configuration stored in a driver header."""

    if type(value) is not dict:
        raise PopulationDriverError("stored driver configuration must be a JSON object")
    try:
        population = value["population"]
        initial_parent = value["initial_parent"]
        if type(population) is not dict or type(initial_parent) is not dict:
            raise KeyError("population or initial_parent")
        experiment = population["experiment"]
        if type(experiment) is not dict:
            raise KeyError("population.experiment")
        reconstructed_request = {
            "allocation_draws": value["allocation_draws"],
            "evidence_adapter": value["evidence_adapter"],
            "generation": value["generation"],
            "initial_parent_artifact": initial_parent["artifact"],
            "limits": value["limits"],
            "population": {
                "configuration": population["configuration"],
                "development": {
                    "behavior_space": experiment["behavior_space"],
                    "budget": experiment["budget"],
                    "runtime_id": experiment["runtime_id"],
                },
            },
            "proposal": value["proposal"],
            "schema_version": value["schema_version"],
        }
    except (KeyError, TypeError) as exc:
        detail = exc.args[0] if exc.args else type(exc).__name__
        raise PopulationDriverError(
            f"stored driver configuration is malformed near {detail}"
        ) from exc
    try:
        normalized = decode_request(canonical_json(reconstructed_request))
    except RequestError as exc:
        raise PopulationDriverError(
            f"stored driver configuration is invalid: {exc}"
        ) from exc
    if canonical_json(normalized) != canonical_json(value):
        raise PopulationDriverError(
            "stored driver configuration does not match its derived identities"
        )
    return normalized


def decode_retry_request(source: str) -> dict[str, object]:
    request = decode_json_object(source, RequestError)
    try:
        require_exact_keys(
            request, {"intent_id", "reason", "schema_version"}, "request"
        )
        if (
            type(request["schema_version"]) is not int
            or request["schema_version"] != DRIVER_SCHEMA_VERSION
        ):
            raise ProtocolError(
                f"request.schema_version must be {DRIVER_SCHEMA_VERSION}"
            )
        return {
            "intent_id": require_sha256(request["intent_id"], "request.intent_id"),
            "reason": require_nonempty_string(request["reason"], "request.reason"),
            "schema_version": DRIVER_SCHEMA_VERSION,
        }
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc


def controller_timeout_seconds(config: dict[str, object]) -> int:
    generation = cast(dict[str, object], config["generation"])
    proposal = cast(dict[str, object], config["proposal"])
    runner = cast(dict[str, object], generation["runner"])
    evaluator = cast(dict[str, object], generation["evaluator"])
    tasks = cast(list[dict[str, object]], generation["tasks"])
    return agent_generation_timeout_seconds(
        proposer_timeout_seconds=int(proposal["timeout_seconds"]),
        runner_timeout_seconds=int(runner["timeout_seconds"]),
        evaluator_timeout_seconds=int(evaluator["timeout_seconds"]),
        task_count=len(tasks),
    )


def safe_feedback(result: dict[str, object], round_number: int) -> dict[str, object]:
    selection = cast(dict[str, object], result["selection"])
    return {
        "comparison": normalize_json_value(
            selection["comparison"], "selection.comparison"
        ),
        "decision": require_nonempty_string(
            selection["decision"], "selection.decision"
        ),
        "reason": require_nonempty_string(selection["reason"], "selection.reason"),
        "round": round_number,
        "selected_candidate_id": require_sha256(
            selection["selected"], "selection.selected"
        ),
    }


def controller_request(
    config: dict[str, object],
    parent: dict[str, object],
    round_number: int,
    previous_feedback: dict[str, object] | None,
    *,
    parent_allocation_record_id: str | None,
) -> dict[str, object]:
    generation = cast(dict[str, object], config["generation"])
    proposal = cast(dict[str, object], config["proposal"])
    return {
        "evaluation": generation["evaluation"],
        "evaluator": generation["evaluator"],
        "mutation_request": {
            "parent_artifact": parent["artifact"],
            "proposal_context": {
                "generation": round_number,
                "objective": proposal["context"],
                "population_parent": {
                    "allocation_record_id": parent_allocation_record_id,
                    "candidate_id": parent["candidate_id"],
                },
                "previous_generation": previous_feedback,
            },
            "proposer": {
                "command": proposal["command"],
                "timeout_seconds": proposal["timeout_seconds"],
            },
            "schema_version": AGENT_SCHEMA_VERSION,
        },
        "runner": generation["runner"],
        "schema_version": AGENT_SCHEMA_VERSION,
        "selection_policy": generation["selection_policy"],
        "tasks": generation["tasks"],
    }


def _validated_report_cases(
    report: dict[str, object],
    candidate_id: str,
    tasks: list[dict[str, object]],
    evaluation: str,
    location: str,
) -> dict[str, object]:
    if report.get("candidate") != candidate_id:
        raise PopulationDriverError(f"{location}.candidate does not match")
    if report.get("evaluation") != evaluation:
        raise PopulationDriverError(f"{location}.evaluation does not match")
    raw_cases = report.get("cases")
    if type(raw_cases) is not list or len(raw_cases) != len(tasks):
        raise PopulationDriverError(
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
            raise PopulationDriverError(f"{case_location} must be a JSON object")
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
            raise PopulationDriverError(str(exc)) from exc
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
        raise PopulationDriverError(f"{location}.cases changed task ordering")
    summary = report.get("task_summary")
    expected_summary = {
        "case_count": len(tasks),
        "passed_count": passed_count,
        "safety_failures": safety_failures,
    }
    if summary != expected_summary:
        raise PopulationDriverError(f"{location}.task_summary does not match cases")
    return {
        "cases": normalized_cases,
        "target_probabilities": probabilities,
        "task": expected_summary,
    }


def validate_controller_result(
    request: dict[str, object],
    result: dict[str, object],
    config: dict[str, object],
) -> dict[str, object]:
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
        raise PopulationDriverError("Controller result has the wrong keys")
    if (
        result.get("schema_version") != AGENT_SCHEMA_VERSION
        or type(result.get("schema_version")) is not int
    ):
        raise PopulationDriverError("Controller returned the wrong schema version")
    if result.get("evaluation") != request["evaluation"]:
        raise PopulationDriverError("Controller changed the evaluation identifier")
    mutation = result.get("mutation")
    if type(mutation) is not dict:
        raise PopulationDriverError("Controller result.mutation is malformed")
    try:
        parent = decode_candidate(mutation.get("parent"), "result.mutation.parent")
        child = decode_candidate(mutation.get("child"), "result.mutation.child")
        next_parent = decode_candidate(result.get("next_parent"), "result.next_parent")
        requested_parent = candidate_record(
            cast(dict[str, object], request["mutation_request"])["parent_artifact"],
            "request.mutation_request.parent_artifact",
        )
    except ProtocolError as exc:
        raise PopulationDriverError(str(exc)) from exc
    if parent != requested_parent:
        raise PopulationDriverError("Controller changed the requested parent")
    child_artifact = cast(dict[str, object], child["artifact"])
    if child_artifact["artifact_schema"] != GIT_ARTIFACT_SCHEMA:
        raise PopulationDriverError(
            "Controller child must be a git-candidate-v1 artifact"
        )
    if child["candidate_id"] == parent["candidate_id"]:
        raise PopulationDriverError("Controller returned an unchanged child")
    if next_parent["candidate_id"] not in {
        parent["candidate_id"],
        child["candidate_id"],
    }:
        raise PopulationDriverError("Controller selected an unknown candidate")

    generation = cast(dict[str, object], config["generation"])
    policy = cast(dict[str, object], generation["selection_policy"])
    incumbent_report = result["incumbent_report"]
    challenger_report = result["challenger_report"]
    selection = result["selection"]
    if (
        type(incumbent_report) is not dict
        or type(challenger_report) is not dict
        or type(selection) is not dict
    ):
        raise PopulationDriverError("Controller reports or selection are malformed")
    selection_request = {
        "challenger_report": challenger_report,
        "incumbent_report": incumbent_report,
        "policy": policy,
        "schema_version": AGENT_SCHEMA_VERSION,
    }
    # Selection Gate intentionally validates exact JSON decimals. Reparse the
    # canonical receipt exactly as its stdio boundary does before replay.
    exact_selection_request = json.loads(
        canonical_json(selection_request), parse_float=Decimal
    )
    try:
        expected_selection = select_task_reports(exact_selection_request)
    except (ProtocolError, ValueError) as exc:
        raise PopulationDriverError(f"Controller reports are invalid: {exc}") from exc
    if canonical_json(selection) != canonical_json(expected_selection):
        raise PopulationDriverError("Controller selection does not replay from reports")
    if selection["selected"] != next_parent["candidate_id"]:
        raise PopulationDriverError("Controller selection does not match next_parent")

    tasks = cast(list[dict[str, object]], generation["tasks"])
    evaluation = str(generation["evaluation"])
    parent_evidence = _validated_report_cases(
        incumbent_report,
        str(parent["candidate_id"]),
        tasks,
        evaluation,
        "incumbent_report",
    )
    child_evidence = _validated_report_cases(
        challenger_report,
        str(child["candidate_id"]),
        tasks,
        evaluation,
        "challenger_report",
    )

    raw_traces = result["cases"]
    if type(raw_traces) is not list or len(raw_traces) != len(tasks):
        raise PopulationDriverError("Controller case traces do not match tasks")
    experiment = cast(
        dict[str, object], cast(dict[str, object], config["population"])["experiment"]
    )
    expected_evaluator_id = experiment["evaluator_id"]
    expected_runner_id = canonical_digest(
        {"command": cast(dict[str, object], generation["runner"])["command"]}
    )
    parent_cases = cast(list[dict[str, object]], parent_evidence["cases"])
    child_cases = cast(list[dict[str, object]], child_evidence["cases"])
    parent_probabilities = cast(list[float], parent_evidence["target_probabilities"])
    child_probabilities = cast(list[float], child_evidence["target_probabilities"])
    for index, (raw_trace, task) in enumerate(zip(raw_traces, tasks, strict=True)):
        location = f"Controller cases[{index}]"
        if type(raw_trace) is not dict:
            raise PopulationDriverError(f"{location} must be a JSON object")
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
            raise PopulationDriverError(str(exc)) from exc
        if traced_task != task:
            raise PopulationDriverError(f"{location}.task changed")
        if incumbent_run["candidate_id"] != parent["candidate_id"]:
            raise PopulationDriverError(f"{location} changed incumbent identity")
        if challenger_run["candidate_id"] != child["candidate_id"]:
            raise PopulationDriverError(f"{location} changed challenger identity")
        for run, role in (
            (incumbent_run, "incumbent"),
            (challenger_run, "challenger"),
        ):
            if run["task"] != task:
                raise PopulationDriverError(f"{location} changed {role} task")
            runner_receipt = cast(dict[str, object], run["runner"])
            if runner_receipt["adapter_id"] != expected_runner_id:
                raise PopulationDriverError(
                    f"{location} changed {role} runner identity"
                )
        if observation["evaluator_id"] != expected_evaluator_id:
            raise PopulationDriverError(f"{location} changed evaluator identity")
        if observation["evaluation"] != evaluation:
            raise PopulationDriverError(f"{location} changed evaluation")
        if observation["case_id"] != task["case_id"]:
            raise PopulationDriverError(f"{location} changed evaluation case")
        evaluation_results = cast(list[dict[str, object]], observation["results"])
        results_by_candidate = {
            str(item["candidate_id"]): item for item in evaluation_results
        }
        if set(results_by_candidate) != {
            str(parent["candidate_id"]),
            str(child["candidate_id"]),
        }:
            raise PopulationDriverError(
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
                raise PopulationDriverError(
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
                raise PopulationDriverError(
                    f"{location} report probability does not match forecast"
                )

    mutation_detail = mutation.get("mutation")
    if type(mutation_detail) is not dict:
        raise PopulationDriverError("Controller mutation receipt is malformed")
    try:
        proposal_id = require_sha256(
            mutation_detail.get("proposal_id"),
            "result.mutation.mutation.proposal_id",
        )
    except ProtocolError as exc:
        raise PopulationDriverError(str(exc)) from exc
    return {
        "child": child,
        "child_evidence": child_evidence,
        "next_parent": next_parent,
        "parent": parent,
        "parent_evidence": parent_evidence,
        "proposal_id": proposal_id,
        "selection": expected_selection,
    }


def evidence_adapter_request(
    *,
    config: dict[str, object],
    controller_receipt: dict[str, object],
    controller_result: dict[str, object],
    round_number: int,
) -> dict[str, object]:
    population = cast(dict[str, object], config["population"])
    return {
        "controller_receipt": {
            "sha256": controller_receipt["sha256"],
            "uri": controller_receipt["uri"],
        },
        "controller_result": controller_result,
        "experiment": {
            "experiment_id": population["experiment_id"],
            "specification": population["experiment"],
        },
        "protocol_version": EVIDENCE_ADAPTER_PROTOCOL_VERSION,
        "round": round_number,
    }


def decode_evidence_adapter_response(
    value: dict[str, object],
    *,
    candidate_ids: set[str],
    experiment: dict[str, object],
) -> dict[str, dict[str, object]]:
    try:
        require_exact_keys(value, {"candidates", "protocol_version"}, "response")
        if (
            type(value["protocol_version"]) is not int
            or value["protocol_version"] != EVIDENCE_ADAPTER_PROTOCOL_VERSION
        ):
            raise ProtocolError(
                f"response.protocol_version must be {EVIDENCE_ADAPTER_PROTOCOL_VERSION}"
            )
        raw_candidates = value["candidates"]
        if type(raw_candidates) is not list or len(raw_candidates) != 2:
            raise ProtocolError("response.candidates must contain exactly two entries")
        behavior_space = cast(list[str], experiment["behavior_space"])
        decoded: dict[str, dict[str, object]] = {}
        for index, raw_candidate in enumerate(raw_candidates):
            location = f"response.candidates[{index}]"
            if type(raw_candidate) is not dict:
                raise ProtocolError(f"{location} must be a JSON object")
            require_exact_keys(
                raw_candidate,
                {
                    "behavior_distribution",
                    "candidate_id",
                    "cost",
                    "protected_passed",
                    "seed",
                },
                location,
            )
            candidate_id = require_sha256(
                raw_candidate["candidate_id"], f"{location}.candidate_id"
            )
            if candidate_id not in candidate_ids or candidate_id in decoded:
                raise ProtocolError(
                    f"{location}.candidate_id must identify one unreported candidate"
                )
            behavior = raw_candidate["behavior_distribution"]
            if type(behavior) is not list or len(behavior) != len(behavior_space):
                raise ProtocolError(
                    f"{location}.behavior_distribution must contain exactly "
                    f"{len(behavior_space)} probabilities"
                )
            normalized_behavior = _distribution(
                behavior,
                f"{location}.behavior_distribution",
                length=len(behavior_space),
            )
            decoded[candidate_id] = {
                "behavior_distribution": normalized_behavior,
                "cost": _resources(
                    raw_candidate["cost"], f"{location}.cost", positive=False
                ),
                "protected_passed": require_bool(
                    raw_candidate["protected_passed"],
                    f"{location}.protected_passed",
                ),
                "seed": normalize_json_value(raw_candidate["seed"], f"{location}.seed"),
            }
        if set(decoded) != candidate_ids:
            raise ProtocolError("response.candidates omitted a candidate")
        return decoded
    except ProtocolError as exc:
        raise PopulationDriverError(
            f"evidence adapter response is invalid: {exc}"
        ) from exc


def total_cost(runs: list[dict[str, object]], experiment_id: str) -> dict[str, int]:
    totals = {name: 0 for name in RESOURCE_NAMES}
    for body in runs:
        run = cast(dict[str, object], body["run"])
        if run["experiment_id"] != experiment_id:
            continue
        evidence = cast(dict[str, object], body["evidence"])
        cost = cast(dict[str, int], evidence["cost"])
        for name in RESOURCE_NAMES:
            totals[name] += cost[name]
    return totals
