"""Run one schema-v2 agent-artifact generation through the six applications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from apps.agent_protocol import (
    AGENT_SCHEMA_VERSION,
    ProtocolError,
    decode_candidate,
    decode_candidate_run,
    decode_command,
    decode_observer_evaluation,
    decode_task,
    normalize_json_value,
    require_exact_keys,
    require_nonempty_string,
    require_schema_version,
    require_timeout,
)
from apps.controller.component_runtime import (
    CANDIDATE_RUNNER,
    COMPONENT_TIMEOUT_SECONDS,
    FORECAST_ASSAY,
    MUTATOR,
    OBSERVER,
    SELECTION_GATE,
    ControllerError,
    RequestError,
    _run_component,
)


@dataclass(frozen=True)
class AgentComponent:
    command: list[str]
    timeout_seconds: int


@dataclass(frozen=True)
class AgentGenerationRequest:
    evaluation: str
    mutation_request: dict[str, object]
    tasks: list[dict[str, object]]
    runner: AgentComponent
    evaluator: AgentComponent
    selection_policy: dict[str, object]


def _decode_agent_component(value: object, location: str) -> AgentComponent:
    if type(value) is not dict:
        raise RequestError(f"{location} must be a JSON object")
    try:
        require_exact_keys(value, {"command", "timeout_seconds"}, location)
        command = decode_command(value["command"], f"{location}.command")
        timeout = require_timeout(
            value["timeout_seconds"], f"{location}.timeout_seconds"
        )
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc
    return AgentComponent(command=command, timeout_seconds=timeout)


def decode_agent_generation_request(
    request: dict[str, object],
) -> AgentGenerationRequest:
    try:
        require_exact_keys(
            request,
            {
                "schema_version",
                "evaluation",
                "mutation_request",
                "tasks",
                "runner",
                "evaluator",
                "selection_policy",
            },
            "schema_version 2 request",
        )
        require_schema_version(request["schema_version"])
        evaluation = require_nonempty_string(request["evaluation"], "evaluation")
        mutation_request = request["mutation_request"]
        if type(mutation_request) is not dict:
            raise ProtocolError("mutation_request must be a JSON object")
        require_schema_version(
            mutation_request.get("schema_version"),
            "mutation_request.schema_version",
        )
        raw_tasks = request["tasks"]
        if type(raw_tasks) is not list or not raw_tasks:
            raise ProtocolError("tasks must be a non-empty JSON array")
        tasks: list[dict[str, object]] = []
        seen: set[str] = set()
        for index, raw_task in enumerate(raw_tasks):
            location = f"tasks[{index}]"
            task = decode_task(raw_task, location)
            case_id = str(task["case_id"])
            if case_id in seen:
                raise ProtocolError(f"duplicate task case identifier: {case_id}")
            seen.add(case_id)
            tasks.append(task)
        selection_policy = request["selection_policy"]
        if type(selection_policy) is not dict:
            raise ProtocolError("selection_policy must be a JSON object")
        selection_policy = normalize_json_value(selection_policy, "selection_policy")
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc

    return AgentGenerationRequest(
        evaluation=evaluation,
        mutation_request=mutation_request,
        tasks=tasks,
        runner=_decode_agent_component(request["runner"], "runner"),
        evaluator=_decode_agent_component(request["evaluator"], "evaluator"),
        selection_policy=selection_policy,
    )


def _agent_candidate_record(
    mutation: dict[str, object], role: str
) -> dict[str, object]:
    try:
        return decode_candidate(mutation.get(role), f"Mutator {role}")
    except ProtocolError as exc:
        raise ControllerError(str(exc)) from exc


def _validated_agent_run(
    value: object,
    candidate_id: str,
    task: dict[str, object],
    role: str,
) -> dict[str, object]:
    location = f"Candidate Runner {role} response"
    try:
        run = decode_candidate_run(value, location)
    except ProtocolError as exc:
        raise ControllerError(str(exc)) from exc
    if run["candidate_id"] != candidate_id:
        raise ControllerError(f"Candidate Runner changed the {role} candidate ID")
    if run["task"] != task:
        raise ControllerError(f"Candidate Runner changed the {role} task")
    return run


def _validated_observer_evaluation(
    value: object,
    expected_ids: set[str],
    task: dict[str, object],
    evaluation: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    try:
        observation = decode_observer_evaluation(value, "Observer response")
    except ProtocolError as exc:
        raise ControllerError(str(exc)) from exc
    if observation["case_id"] != task["case_id"]:
        raise ControllerError("Observer changed the task case ID")
    if observation["evaluation"] != evaluation:
        raise ControllerError("Observer changed the evaluation identifier")

    result_documents = cast(list[dict[str, object]], observation["results"])
    results = {str(result["candidate_id"]): result for result in result_documents}
    if set(results) != expected_ids:
        raise ControllerError("Observer returned an unknown candidate ID")
    return observation, results


def _run_agent_candidate(
    candidate: dict[str, object],
    task: dict[str, object],
    runner: AgentComponent,
    role: str,
) -> dict[str, object]:
    candidate_id = str(candidate["candidate_id"])
    response = _run_component(
        "Candidate Runner",
        CANDIDATE_RUNNER,
        {
            "adapter_command": runner.command,
            "candidate": candidate,
            "schema_version": AGENT_SCHEMA_VERSION,
            "task": task,
            "timeout_seconds": runner.timeout_seconds,
        },
        timeout_seconds=runner.timeout_seconds + COMPONENT_TIMEOUT_SECONDS,
    )
    return _validated_agent_run(response, candidate_id, task, role)


def _run_agent_case(
    request: AgentGenerationRequest,
    task: dict[str, object],
    incumbent: dict[str, object],
    challenger: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    incumbent_id = str(incumbent["candidate_id"])
    challenger_id = str(challenger["candidate_id"])
    incumbent_run = _run_agent_candidate(incumbent, task, request.runner, "incumbent")
    challenger_run = _run_agent_candidate(
        challenger, task, request.runner, "challenger"
    )

    observation = _run_component(
        "Observer",
        OBSERVER,
        {
            "case": task,
            "challenger_run": challenger_run,
            "evaluation": request.evaluation,
            "evaluator_command": request.evaluator.command,
            "incumbent_run": incumbent_run,
            "schema_version": AGENT_SCHEMA_VERSION,
            "timeout_seconds": request.evaluator.timeout_seconds,
        },
        arguments=("--evaluate",),
        timeout_seconds=(request.evaluator.timeout_seconds + COMPONENT_TIMEOUT_SECONDS),
    )
    observation, results = _validated_observer_evaluation(
        observation,
        {incumbent_id, challenger_id},
        task,
        request.evaluation,
    )
    trace = {
        "challenger_run": challenger_run,
        "incumbent_run": incumbent_run,
        "observer_evaluation": observation,
        "task": task,
    }
    incumbent_case = {
        "case_id": task["case_id"],
        "forecast": incumbent_run["forecast"],
        "result": results[incumbent_id],
    }
    challenger_case = {
        "case_id": task["case_id"],
        "forecast": challenger_run["forecast"],
        "result": results[challenger_id],
    }
    return trace, incumbent_case, challenger_case


def _assay_agent_candidate(
    candidate_id: str,
    cases: list[dict[str, object]],
    evaluation: str,
) -> dict[str, object]:
    return _run_component(
        "Forecast Assay",
        FORECAST_ASSAY,
        {
            "candidate": candidate_id,
            "cases": cases,
            "evaluation": evaluation,
            "schema_version": AGENT_SCHEMA_VERSION,
        },
    )


def _mutation_component_timeout(mutation_request: dict[str, object]) -> int:
    proposer = mutation_request.get("proposer")
    if type(proposer) is not dict:
        return COMPONENT_TIMEOUT_SECONDS
    timeout = proposer.get("timeout_seconds")
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        return COMPONENT_TIMEOUT_SECONDS
    return timeout + COMPONENT_TIMEOUT_SECONDS


def run_agent_generation(request: AgentGenerationRequest) -> dict[str, object]:
    mutation = _run_component(
        "Mutator",
        MUTATOR,
        request.mutation_request,
        timeout_seconds=_mutation_component_timeout(request.mutation_request),
    )
    if mutation.get("schema_version") != AGENT_SCHEMA_VERSION:
        raise ControllerError(
            f"Mutator did not return schema version {AGENT_SCHEMA_VERSION}"
        )
    incumbent = _agent_candidate_record(mutation, "parent")
    challenger = _agent_candidate_record(mutation, "child")
    incumbent_id = str(incumbent["candidate_id"])
    challenger_id = str(challenger["candidate_id"])
    if incumbent_id == challenger_id:
        raise ControllerError("Mutator returned identical parent and child IDs")

    traces: list[dict[str, object]] = []
    incumbent_cases: list[dict[str, object]] = []
    challenger_cases: list[dict[str, object]] = []
    for task in request.tasks:
        trace, incumbent_case, challenger_case = _run_agent_case(
            request, task, incumbent, challenger
        )
        traces.append(trace)
        incumbent_cases.append(incumbent_case)
        challenger_cases.append(challenger_case)

    incumbent_report = _assay_agent_candidate(
        incumbent_id, incumbent_cases, request.evaluation
    )
    challenger_report = _assay_agent_candidate(
        challenger_id, challenger_cases, request.evaluation
    )
    selection = _run_component(
        "Selection Gate",
        SELECTION_GATE,
        {
            "challenger_report": challenger_report,
            "incumbent_report": incumbent_report,
            "policy": request.selection_policy,
            "schema_version": AGENT_SCHEMA_VERSION,
        },
    )
    selected = selection.get("selected")
    if selected == incumbent_id:
        next_parent = incumbent
    elif selected == challenger_id:
        next_parent = challenger
    else:
        raise ControllerError("Selection Gate returned an unknown candidate ID")

    return {
        "cases": traces,
        "challenger_report": challenger_report,
        "evaluation": request.evaluation,
        "incumbent_report": incumbent_report,
        "mutation": mutation,
        "next_parent": next_parent,
        "schema_version": AGENT_SCHEMA_VERSION,
        "selection": selection,
    }
