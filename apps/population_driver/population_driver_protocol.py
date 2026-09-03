"""Strict request, Controller, and evidence contracts for Population Driver."""

from __future__ import annotations

from typing import cast

from apps.agent_protocol import (
    AGENT_SCHEMA_VERSION,
    GIT_ARTIFACT_SCHEMA,
    ProtocolError,
    candidate_record,
    decode_command,
    decode_task,
    normalize_json_value,
    require_bool,
    require_exact_keys,
    require_nonempty_string,
    require_sha256,
    require_timeout,
)
from apps.controller.contract import (
    ControllerReceiptError,
    agent_generation_timeout_seconds,
    validate_agent_generation_receipt,
)
from apps.population.contract import (
    MAX_PROTOCOL_INTEGER,
    POPULATION_SCHEMA_VERSION,
    RESOURCE_NAMES,
    PopulationError,
    PopulationState,
    RequestError as PopulationRequestError,
    normalize_distribution,
    normalize_draw,
    normalize_resources,
    decode_experiment_request,
    decode_initialize_request,
    decode_run_request,
)
from apps._support.wire import (
    canonical_digest,
    canonical_json,
    decode_json_object,
)

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
    return [
        normalize_draw(item, f"{location}[{index}]") for index, item in enumerate(value)
    ]


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
        "max_total_candidate_cost": normalize_resources(
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


def validate_controller_result(
    request: dict[str, object],
    result: dict[str, object],
    config: dict[str, object],
) -> dict[str, object]:
    """Replay Controller-owned evidence and enforce Population's Git boundary."""

    try:
        validation = validate_agent_generation_receipt(request, result)
    except ControllerReceiptError as exc:
        raise PopulationDriverError(str(exc)) from exc
    child = cast(dict[str, object], validation["child"])
    child_artifact = cast(dict[str, object], child["artifact"])
    if child_artifact["artifact_schema"] != GIT_ARTIFACT_SCHEMA:
        raise PopulationDriverError(
            "Controller child must be a git-candidate-v1 artifact"
        )
    population = cast(dict[str, object], config["population"])
    experiment = cast(dict[str, object], population["experiment"])
    generation = cast(dict[str, object], config["generation"])
    evaluator = cast(dict[str, object], generation["evaluator"])
    if experiment["evaluator_id"] != canonical_digest(
        {"command": evaluator["command"]}
    ):
        raise PopulationDriverError(
            "Population experiment changed the Controller evaluator identity"
        )
    return validation


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
            normalized_behavior = normalize_distribution(
                behavior,
                f"{location}.behavior_distribution",
                length=len(behavior_space),
            )
            decoded[candidate_id] = {
                "behavior_distribution": normalized_behavior,
                "cost": normalize_resources(
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


def population_run_body(
    *,
    candidate_id: str,
    experiment_id: str,
    replicate_id: str,
    report_evidence: dict[str, object],
    adapter_evidence: dict[str, object],
    evidence_reference: dict[str, object],
    state: PopulationState,
) -> dict[str, object]:
    """Construct one Population-owned run body from verified round evidence."""

    request = {
        "candidate_id": candidate_id,
        "evidence": {
            "behavior_distribution": adapter_evidence["behavior_distribution"],
            "cost": adapter_evidence["cost"],
            "evidence_receipt": {
                "sha256": evidence_reference["sha256"],
                "uri": evidence_reference["uri"],
            },
            "information_model": None,
            "protected_passed": adapter_evidence["protected_passed"],
            "target_probabilities": report_evidence["target_probabilities"],
            "task": report_evidence["task"],
        },
        "experiment_id": experiment_id,
        "replicate_id": replicate_id,
        "schema_version": POPULATION_SCHEMA_VERSION,
        "seed": adapter_evidence["seed"],
    }
    try:
        return decode_run_request(request, state)
    except (PopulationError, ValueError) as exc:
        raise PopulationDriverError(str(exc)) from exc


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
