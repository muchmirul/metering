"""Run one complete Observer-backed candidate generation."""

from __future__ import annotations

import json
import math
import selectors
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

SCHEMA_VERSION = 1
COMPONENT_TIMEOUT_SECONDS = 10
ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_RUNNER = "apps/candidate_runner/candidate_runner.py"
FORECAST_ASSAY = "apps/forecast_assay/forecast_assay.py"
MUTATOR = "apps/mutator/mutator.py"
OBSERVER = "apps/observer/observer.py"
SELECTION_GATE = "apps/selection_gate/selection_gate.py"

APPS_ROOT = ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from agent_protocol import (  # noqa: E402
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
from stdio_connector import (  # noqa: E402
    JsonProcessError,
    canonical_json,
    decode_json_object,
    run_json_process,
    run_stdio_application,
)


class RequestError(ValueError):
    """Raised when a controller request violates its protocol."""


class ControllerError(RuntimeError):
    """Raised when a component or composition invariant fails."""


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


def _parse_json_number(token: str) -> float:
    try:
        exact = Decimal(token)
        converted = float(exact)
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise RequestError("JSON number exceeds supported numeric limits") from exc
    if not math.isfinite(converted):
        raise RequestError("JSON number is outside the finite double range")
    if (converted == 0.0 and exact != 0) or (
        converted == 1.0 and exact != 1
    ):
        raise RequestError(
            "JSON number would change whether its value is zero or one "
            "in double precision"
        )
    return converted


def _decode_json(source: str) -> dict[str, object]:
    return decode_json_object(
        source,
        RequestError,
        parse_float=_parse_json_number,
    )


def _require_exact_keys(
    value: dict[str, object], expected: set[str], location: str
) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing keys: {', '.join(missing)}")
    if extra:
        details.append(f"extra keys: {', '.join(extra)}")
    if details:
        raise RequestError(f"{location}: {'; '.join(details)}")


def _require_nonempty_string(value: object, location: str) -> str:
    if type(value) is not str or not value:
        raise RequestError(f"{location} must be a non-empty string")
    return value


def _decode_probe(raw_probe: object, location: str) -> dict[str, str]:
    if type(raw_probe) is not dict:
        raise RequestError(f"{location} must be a JSON object")
    operation = _require_nonempty_string(
        raw_probe.get("operation"), f"{location}.operation"
    )
    if operation == "list":
        _require_exact_keys(raw_probe, {"operation"}, location)
        return {"operation": "list"}
    if operation == "read":
        _require_exact_keys(raw_probe, {"operation", "path"}, location)
        path = _require_nonempty_string(raw_probe["path"], f"{location}.path")
        return {"operation": "read", "path": path}
    raise RequestError(f"{location}.operation must be one of: list, read")


def decode_request(
    source: str,
) -> tuple[str, str, dict[str, object], list[dict[str, str]], float]:
    request = _decode_json(source)
    _require_exact_keys(
        request,
        {
            "schema_version",
            "active_version",
            "evaluation",
            "mutation_request",
            "probes",
            "required_improvement_bits",
        },
        "request",
    )
    if (
        type(request["schema_version"]) is not int
        or request["schema_version"] != SCHEMA_VERSION
    ):
        raise RequestError(f"schema_version must be {SCHEMA_VERSION}")
    active_version = _require_nonempty_string(
        request["active_version"], "active_version"
    )
    if active_version not in {"v1", "v2", "v3", "v4"}:
        raise RequestError("active_version must be one of: v1, v2, v3, v4")
    evaluation = _require_nonempty_string(request["evaluation"], "evaluation")
    mutation_request = request["mutation_request"]
    if type(mutation_request) is not dict:
        raise RequestError("mutation_request must be a JSON object")
    raw_probes = request["probes"]
    if type(raw_probes) is not list or not raw_probes:
        raise RequestError("probes must be a non-empty JSON array")
    probes: list[dict[str, str]] = []
    seen_probes: set[str] = set()
    for index, raw_probe in enumerate(raw_probes):
        probe = _decode_probe(raw_probe, f"probes[{index}]")
        probe_key = canonical_json(probe)
        if probe_key in seen_probes:
            raise RequestError(f"duplicate probe: {probe_key}")
        seen_probes.add(probe_key)
        probes.append(probe)
    threshold = request["required_improvement_bits"]
    if type(threshold) is bool or not isinstance(threshold, (int, float)):
        raise RequestError("required_improvement_bits must be a finite JSON number")
    try:
        converted_threshold = float(threshold)
    except (OverflowError, ValueError) as exc:
        raise RequestError(
            "required_improvement_bits is outside the finite double range"
        ) from exc
    if not math.isfinite(converted_threshold) or converted_threshold < 0:
        raise RequestError(
            "required_improvement_bits must be finite and greater than or equal to 0"
        )
    return (
        active_version,
        evaluation,
        mutation_request,
        probes,
        0.0 if converted_threshold == 0.0 else converted_threshold,
    )


def _component_error_detail(stderr: str, returncode: int) -> str:
    detail = stderr.strip()
    if detail:
        try:
            document = json.loads(detail)
            error = document.get("error")
            if type(error) is dict and type(error.get("message")) is str:
                return str(error["message"])
        except (AttributeError, json.JSONDecodeError):
            pass
        return detail
    return f"exit status {returncode}"


def _decode_component_output(
    name: str, source: str, *, allow_error: bool = False
) -> dict[str, object]:
    try:
        response = json.loads(
            source,
            object_pairs_hook=lambda pairs: _component_unique_object(name, pairs),
            parse_constant=lambda token: _component_non_finite(name, token),
        )
    except (ControllerError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, ControllerError):
            raise
        raise ControllerError(f"{name} returned invalid JSON: {exc}") from exc
    if type(response) is not dict:
        raise ControllerError(f"{name} response must be one JSON object")
    if "error" in response and not allow_error:
        raise ControllerError(f"{name} returned an error response")
    return response


def _component_unique_object(
    name: str, pairs: list[tuple[str, object]]
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ControllerError(f"{name} returned duplicate key: {key}")
        result[key] = value
    return result


def _component_non_finite(name: str, token: str) -> object:
    raise ControllerError(f"{name} returned a non-finite number: {token}")


def _run_component(
    name: str,
    relative_path: str,
    request: dict[str, object],
    *,
    arguments: tuple[str, ...] = (),
    timeout_seconds: int = COMPONENT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    command = [sys.executable, str(ROOT / relative_path), *arguments]
    try:
        source = run_json_process(
            command,
            request,
            cwd=ROOT,
            timeout_seconds=timeout_seconds,
        )
    except JsonProcessError as error:
        if error.kind == "timeout":
            message = f"{name} exceeded the component timeout"
        elif error.kind == "start":
            message = f"cannot start {name}: {error.detail}"
        elif error.kind == "exit":
            returncode = error.returncode if error.returncode is not None else 1
            detail = _component_error_detail(error.stderr, returncode)
            message = f"{name} failed: {detail}"
        else:
            message = f"{name} wrote unexpected standard error"
        raise ControllerError(message) from error
    return _decode_component_output(name, source)


def _require_component_object(
    value: object, location: str
) -> dict[str, object]:
    if type(value) is not dict:
        raise ControllerError(f"{location} must be a JSON object")
    return value


def _candidate_record(
    mutation: dict[str, object], role: str
) -> tuple[str, dict[str, object]]:
    record = _require_component_object(mutation.get(role), f"Mutator {role}")
    candidate_id = record.get("candidate_id")
    genome = record.get("genome")
    if type(candidate_id) is not str or not candidate_id:
        raise ControllerError(f"Mutator {role}.candidate_id is invalid")
    if type(genome) is not dict:
        raise ControllerError(f"Mutator {role}.genome is invalid")
    return candidate_id, genome


def _runner_request(
    candidate_id: str,
    genome: dict[str, object],
    probe: dict[str, str],
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "genome": genome,
        "probe": probe,
        "schema_version": SCHEMA_VERSION,
    }


def _forecast_probabilities(
    response: dict[str, object],
    candidate_id: str,
    genome: dict[str, object],
    probe: dict[str, str],
) -> dict[str, float]:
    if response.get("candidate_id") != candidate_id:
        raise ControllerError("Candidate Runner changed the candidate_id")
    if response.get("genome") != genome:
        raise ControllerError("Candidate Runner changed the genome")
    if response.get("probe") != probe:
        raise ControllerError("Candidate Runner changed the probe")
    forecast = _require_component_object(
        response.get("forecast"), "Candidate Runner forecast"
    )
    outcomes = forecast.get("outcomes")
    if type(outcomes) is not list or not outcomes:
        raise ControllerError(
            "Candidate Runner forecast.outcomes must be a non-empty array"
        )
    probabilities: dict[str, float] = {}
    for index, outcome in enumerate(outcomes):
        location = f"Candidate Runner forecast.outcomes[{index}]"
        item = _require_component_object(outcome, location)
        if set(item) != {"target", "probability"}:
            raise ControllerError(f"{location} has the wrong keys")
        target = item["target"]
        probability = item["probability"]
        if type(target) is not str or not target:
            raise ControllerError(f"{location}.target is invalid")
        if target in probabilities:
            raise ControllerError(f"{location}.target is duplicated")
        if type(probability) is bool or not isinstance(probability, (int, float)):
            raise ControllerError(f"{location}.probability is invalid")
        converted = float(probability)
        if not math.isfinite(converted) or not 0 <= converted <= 1:
            raise ControllerError(f"{location}.probability is invalid")
        probabilities[target] = 0.0 if converted == 0.0 else converted
    if not math.isclose(
        math.fsum(probabilities.values()),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ControllerError("Candidate Runner forecast is not normalized")
    return probabilities


class ObserverSession:
    def __init__(self, active_version: str) -> None:
        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / OBSERVER),
                    "--jsonl",
                    "--active",
                    active_version,
                ],
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise ControllerError(f"cannot start Observer: {exc}") from exc
        if (
            self.process.stdin is None
            or self.process.stdout is None
            or self.process.stderr is None
        ):
            self.abort()
            raise ControllerError("Observer standard streams are unavailable")
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.closed = False

    def request(self, request: dict[str, object]) -> dict[str, object]:
        if self.closed:
            raise ControllerError("Observer session is closed")
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        try:
            self.process.stdin.write(canonical_json(request) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ControllerError("Observer stopped before reading a request") from exc
        if not self.selector.select(timeout=COMPONENT_TIMEOUT_SECONDS):
            raise ControllerError("Observer exceeded the component timeout")
        line = self.process.stdout.readline()
        if line == "":
            status = self.process.poll()
            detail = "closed its output"
            if status is not None:
                assert self.process.stderr is not None
                detail = _component_error_detail(
                    self.process.stderr.read(), status
                )
            raise ControllerError(f"Observer failed: {detail}")
        return _decode_component_output("Observer", line, allow_error=True)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.selector.close()
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        try:
            self.process.stdin.close()
            status = self.process.wait(timeout=COMPONENT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            self.process.kill()
            self.process.wait()
            raise ControllerError("Observer did not stop after input EOF") from exc
        remaining_output = self.process.stdout.read()
        stderr = self.process.stderr.read()
        if status != 0:
            detail = _component_error_detail(stderr, status)
            raise ControllerError(f"Observer failed: {detail}")
        if stderr:
            raise ControllerError("Observer wrote unexpected standard error")
        if remaining_output:
            raise ControllerError("Observer returned unexpected extra responses")

    def abort(self) -> None:
        self.closed = True
        selector = getattr(self, "selector", None)
        if selector is not None:
            selector.close()
        process = getattr(self, "process", None)
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()


def _observer_ok(response: dict[str, object], action: str) -> None:
    if response.get("ok") is not True:
        error = response.get("error")
        if type(error) is dict and type(error.get("message")) is str:
            raise ControllerError(f"Observer {action} failed: {error['message']}")
        raise ControllerError(f"Observer {action} returned an error")


def _available_probe_keys(state: dict[str, object]) -> set[str]:
    available = state.get("available_probes")
    if type(available) is not list:
        raise ControllerError("Observer state.available_probes is invalid")
    keys: set[str] = set()
    for index, item in enumerate(available):
        record = _require_component_object(
            item, f"Observer state.available_probes[{index}]"
        )
        probe = record.get("probe")
        if type(probe) is not dict:
            raise ControllerError(
                f"Observer state.available_probes[{index}].probe is invalid"
            )
        keys.add(canonical_json(probe))
    return keys


def _snapshot_ids(state: dict[str, object]) -> dict[str, str]:
    snapshots = state.get("snapshots")
    if type(snapshots) is not list:
        raise ControllerError("Observer state.snapshots is invalid")
    result: dict[str, str] = {}
    for index, item in enumerate(snapshots):
        record = _require_component_object(item, f"Observer snapshots[{index}]")
        name = record.get("name")
        snapshot_id = record.get("snapshot_id")
        if type(name) is not str or type(snapshot_id) is not str:
            raise ControllerError(f"Observer snapshots[{index}] is invalid")
        result[name] = snapshot_id
    return result


def _identified_version(response: dict[str, object]) -> str:
    belief = response.get("belief")
    if type(belief) is not dict:
        raise ControllerError("Observer final belief is invalid")
    identified = [
        name
        for name, probability in belief.items()
        if type(name) is str
        and type(probability) in {int, float}
        and float(probability) == 1.0
    ]
    if len(identified) != 1:
        raise ControllerError("Observer did not identify exactly one version")
    return identified[0]


def _assay_request(
    candidate_id: str,
    evaluation: str,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "candidate": candidate_id,
        "evaluation": evaluation,
        "observations": observations,
        "schema_version": SCHEMA_VERSION,
    }


def run_generation(
    active_version: str,
    evaluation: str,
    mutation_request: dict[str, object],
    probes: list[dict[str, str]],
    threshold: float,
) -> dict[str, object]:
    mutation = _run_component("Mutator", MUTATOR, mutation_request)
    incumbent_id, incumbent_genome = _candidate_record(mutation, "parent")
    challenger_id, challenger_genome = _candidate_record(mutation, "child")
    if incumbent_id == challenger_id:
        raise ControllerError("Mutator returned identical parent and child IDs")

    observer = ObserverSession(active_version)
    try:
        state = observer.request({"action": "state"})
        _observer_ok(state, "state")
        available_probe_keys = _available_probe_keys(state)
        for probe in probes:
            if canonical_json(probe) not in available_probe_keys:
                raise ControllerError(
                    f"requested probe is not advertised by Observer: "
                    f"{canonical_json(probe)}"
                )

        cases: list[dict[str, object]] = []
        incumbent_rows: list[dict[str, object]] = []
        challenger_rows: list[dict[str, object]] = []
        final_observation: dict[str, object] | None = None
        runner_model: object | None = None
        for index, probe in enumerate(probes):
            incumbent_forecast = _run_component(
                "Candidate Runner",
                CANDIDATE_RUNNER,
                _runner_request(incumbent_id, incumbent_genome, probe),
            )
            challenger_forecast = _run_component(
                "Candidate Runner",
                CANDIDATE_RUNNER,
                _runner_request(challenger_id, challenger_genome, probe),
            )
            incumbent_probabilities = _forecast_probabilities(
                incumbent_forecast,
                incumbent_id,
                incumbent_genome,
                probe,
            )
            challenger_probabilities = _forecast_probabilities(
                challenger_forecast,
                challenger_id,
                challenger_genome,
                probe,
            )
            incumbent_model = incumbent_forecast.get("runner_model")
            challenger_model = challenger_forecast.get("runner_model")
            if (
                type(incumbent_model) is not str
                or incumbent_model != challenger_model
            ):
                raise ControllerError(
                    "Candidate Runner used different models for the candidates"
                )
            if runner_model is None:
                runner_model = incumbent_model
            elif runner_model != incumbent_model:
                raise ControllerError("Candidate Runner model changed during the run")

            observation_response = observer.request(
                {"action": "observe", "probe": probe}
            )
            _observer_ok(observation_response, "observe")
            final_observation = observation_response
            observed_result = observation_response.get("observed_result")
            if type(observed_result) is not dict:
                raise ControllerError("Observer observed_result is invalid")
            target = canonical_json(observed_result)
            if target not in incumbent_probabilities:
                raise ControllerError(
                    "incumbent forecast did not contain the observed target"
                )
            if target not in challenger_probabilities:
                raise ControllerError(
                    "challenger forecast did not contain the observed target"
                )
            observation_id = f"probe-{index + 1}:{canonical_json(probe)}"
            incumbent_probability = incumbent_probabilities[target]
            challenger_probability = challenger_probabilities[target]
            incumbent_rows.append(
                {
                    "observation": observation_id,
                    "target": target,
                    "target_probability": incumbent_probability,
                }
            )
            challenger_rows.append(
                {
                    "observation": observation_id,
                    "target": target,
                    "target_probability": challenger_probability,
                }
            )
            cases.append(
                {
                    "challenger_forecast": challenger_forecast,
                    "incumbent_forecast": incumbent_forecast,
                    "observation": observation_id,
                    "observer_response": observation_response,
                    "probe": probe,
                    "target": target,
                }
            )
            done = observation_response.get("done")
            if type(done) is not bool:
                raise ControllerError("Observer observe response.done is invalid")
            if done and index != len(probes) - 1:
                raise ControllerError(
                    "Observer identified the version before the final requested probe"
                )

        if final_observation is None or final_observation.get("done") is not True:
            raise ControllerError(
                "requested probes did not identify one Observer version"
            )
        identified_version = _identified_version(final_observation)
        snapshots = _snapshot_ids(state)
        if identified_version not in snapshots:
            raise ControllerError("Observer omitted the identified snapshot")
        finish = observer.request(
            {
                "action": "finish",
                "snapshot_id": snapshots[identified_version],
            }
        )
        _observer_ok(finish, "finish")
        if finish.get("correct") is not True:
            raise ControllerError("Observer rejected the identified snapshot")
        observer.close()
    except BaseException:
        observer.abort()
        raise

    incumbent_report = _run_component(
        "Forecast Assay",
        FORECAST_ASSAY,
        _assay_request(incumbent_id, evaluation, incumbent_rows),
    )
    challenger_report = _run_component(
        "Forecast Assay",
        FORECAST_ASSAY,
        _assay_request(challenger_id, evaluation, challenger_rows),
    )
    if incumbent_report.get("candidate") != incumbent_id:
        raise ControllerError("Forecast Assay changed the incumbent ID")
    if challenger_report.get("candidate") != challenger_id:
        raise ControllerError("Forecast Assay changed the challenger ID")
    selection = _run_component(
        "Selection Gate",
        SELECTION_GATE,
        {
            "challenger_report": challenger_report,
            "incumbent_report": incumbent_report,
            "required_improvement_bits": threshold,
            "schema_version": SCHEMA_VERSION,
        },
    )
    selected = selection.get("selected")
    if selected == incumbent_id:
        next_parent = {"candidate_id": incumbent_id, "genome": incumbent_genome}
    elif selected == challenger_id:
        next_parent = {"candidate_id": challenger_id, "genome": challenger_genome}
    else:
        raise ControllerError("Selection Gate returned an unknown selected candidate")

    return {
        "cases": cases,
        "challenger_report": challenger_report,
        "evaluation": evaluation,
        "incumbent_report": incumbent_report,
        "mutation": mutation,
        "next_parent": next_parent,
        "observer": {
            "active_version": active_version,
            "finish": finish,
            "initial_state": state,
        },
        "runner_model": runner_model,
        "schema_version": SCHEMA_VERSION,
        "selection": selection,
    }


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


def _decode_agent_generation_request(
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


def run_agent_generation(request: AgentGenerationRequest) -> dict[str, object]:
    mutation = _run_component("Mutator", MUTATOR, request.mutation_request)
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


def _process(source: str) -> dict[str, object]:
    request = _decode_json(source)
    if request.get("schema_version") == AGENT_SCHEMA_VERSION:
        generation = _decode_agent_generation_request(request)
        return run_agent_generation(generation)
    active, evaluation, mutation, probes, threshold = decode_request(source)
    return run_generation(active, evaluation, mutation, probes, threshold)


def _unexpected_controller_error(error: Exception) -> tuple[str, str]:
    detail = str(error) or type(error).__name__
    return "controller_error", f"internal controller failure: {detail}"


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        _process,
        arguments,
        error_rules=(
            (RequestError, "invalid_request"),
            (ControllerError, "controller_error"),
        ),
        unexpected=_unexpected_controller_error,
        stream_error_code="controller_error",
    )


if __name__ == "__main__":
    raise SystemExit(main())
