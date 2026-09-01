"""Run one real-Pi evolution and a separate constructed final assay.

This is an acceptance experiment for the checked-in Signal Relay task, not a
claim of general agent improvement. It refuses existing state so the final task
set is loaded only after the bounded development generation has completed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.agent_protocol import (  # noqa: E402
    AGENT_SCHEMA_VERSION,
    ProtocolError,
    decode_candidate,
    decode_task,
    require_exact_keys,
    require_nonempty_string,
)
from connectors.fixed.command import command_prefix  # noqa: E402
from apps.stdio_connector import (  # noqa: E402
    JsonProcessError,
    canonical_json,
    decode_json_object,
    error_document,
    run_json_process,
    write_document,
)

EVOLVER = ROOT / "apps" / "evolution_driver" / "evolver.py"
CONTROLLER = ROOT / "apps" / "controller" / "controller.py"
LIVE_REQUEST = ROOT / "apps" / "evolution_driver" / "signal-relay-live-request.json"
FINAL_TASKS = ROOT / "apps" / "evolution_driver" / "signal-relay-final-tasks.json"
SUMMARY_KEYS = {
    "completed_generations",
    "consecutive_rejections",
    "head",
    "last_record_id",
    "run_id",
    "schema_version",
    "state_path",
    "status",
}


class AcceptanceError(RuntimeError):
    """Raised when the constructed acceptance experiment does not pass."""


def _load_document(path: Path, location: str) -> dict[str, object]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AcceptanceError(f"cannot read {location}: {exc}") from exc
    return decode_json_object(source, AcceptanceError)


def _decode_process_response(source: str, location: str) -> dict[str, object]:
    response = decode_json_object(source, AcceptanceError)
    if source != canonical_json(response) + "\n":
        raise AcceptanceError(f"{location} returned non-canonical JSON")
    return response


def _run(
    command: list[str],
    request: dict[str, object],
    *,
    timeout_seconds: int,
    location: str,
) -> dict[str, object]:
    try:
        source = run_json_process(
            command,
            request,
            cwd=ROOT,
            timeout_seconds=timeout_seconds,
        )
    except JsonProcessError as exc:
        if exc.kind == "timeout":
            message = f"{location} exceeded its acceptance timeout"
        elif exc.kind == "exit":
            message = exc.stderr.strip() or f"{location} exited with {exc.returncode}"
        elif exc.kind == "start":
            message = f"cannot start {location}: {exc.detail}"
        else:
            message = f"{location} wrote unexpected standard error"
        raise AcceptanceError(message) from exc
    return _decode_process_response(source, location)


def _component_timeout(component: dict[str, object], location: str) -> int:
    timeout = component.get("timeout_seconds")
    if type(timeout) is not int or timeout < 1:
        raise AcceptanceError(f"{location}.timeout_seconds is invalid")
    return timeout


def _evolution_timeout(request: dict[str, object]) -> int:
    proposal = cast(dict[str, object], request["proposal"])
    generation = cast(dict[str, object], request["generation"])
    tasks = cast(list[dict[str, object]], generation["tasks"])
    runner = cast(dict[str, object], generation["runner"])
    evaluator = cast(dict[str, object], generation["evaluator"])
    return (
        _component_timeout(proposal, "proposal")
        + len(tasks)
        * (
            2 * _component_timeout(runner, "generation.runner")
            + _component_timeout(evaluator, "generation.evaluator")
        )
        + 300
    )


def _controller_timeout(
    tasks: list[dict[str, object]],
    runner: dict[str, object],
    evaluator: dict[str, object],
) -> int:
    return (
        len(tasks)
        * (
            2 * _component_timeout(runner, "generation.runner")
            + _component_timeout(evaluator, "generation.evaluator")
        )
        + 300
    )


def _agent_configuration() -> dict[str, object]:
    names = {
        "pi_model": "PI_MODEL",
        "pi_provider": "PI_PROVIDER",
        "pi_reasoning_level": "PI_REASONING_LEVEL",
    }
    configuration: dict[str, object] = {}
    for output_name, environment_name in names.items():
        value = os.environ.get(environment_name)
        if not value or "\x00" in value:
            raise AcceptanceError(
                f"{environment_name} must pin the live acceptance configuration"
            )
        configuration[output_name] = value
    try:
        command = command_prefix("METERING_PI_COMMAND", "PI_BIN", "pi")
    except ValueError as exc:
        raise AcceptanceError(str(exc)) from exc
    pi_bin = command[0]
    try:
        completed = subprocess.run(
            [*command, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AcceptanceError(f"cannot identify the Pi command: {exc}") from exc
    version = completed.stdout.strip()
    if completed.returncode != 0 or completed.stderr or not version or "\n" in version:
        raise AcceptanceError("Pi --version did not return one clean line")
    return {
        "pi_bin": pi_bin,
        "pi_command": command,
        "pi_version": version,
        **configuration,
    }


def _state_generation(path: Path) -> dict[str, object]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise AcceptanceError(f"cannot read evolution state: {exc}") from exc
    if len(lines) != 2:
        raise AcceptanceError("acceptance state must contain one completed generation")
    record = decode_json_object(lines[1], AcceptanceError)
    if lines[1] != canonical_json(record):
        raise AcceptanceError("acceptance generation record is not canonical JSON")
    if record.get("kind") != "generation" or record.get("generation") != 1:
        raise AcceptanceError("acceptance state has the wrong generation record")
    result = record.get("controller_result")
    if type(result) is not dict:
        raise AcceptanceError("acceptance state omitted the Controller result")
    return result


def _selection_proof(
    result: dict[str, object],
    *,
    evaluation: str,
    expected_cases: int,
    expected_head: dict[str, object],
) -> dict[str, object]:
    if result.get("schema_version") != AGENT_SCHEMA_VERSION:
        raise AcceptanceError("Controller result has the wrong schema version")
    if result.get("evaluation") != evaluation:
        raise AcceptanceError("Controller result changed the evaluation identifier")
    try:
        next_parent = decode_candidate(result.get("next_parent"), "next_parent")
    except ProtocolError as exc:
        raise AcceptanceError(str(exc)) from exc
    if next_parent != expected_head:
        raise AcceptanceError("Controller did not select the expected evolved head")

    selection = result.get("selection")
    if type(selection) is not dict:
        raise AcceptanceError("Controller result omitted selection evidence")
    if selection.get("decision") != "promote_challenger":
        raise AcceptanceError("challenger was not promoted")
    comparison = selection.get("comparison")
    if type(comparison) is not dict:
        raise AcceptanceError("selection comparison is missing")
    incumbent = comparison.get("incumbent")
    challenger = comparison.get("challenger")
    if type(incumbent) is not dict or type(challenger) is not dict:
        raise AcceptanceError("selection candidate summaries are missing")
    expected = {
        "challenger_passed": expected_cases,
        "challenger_safety_failures": 0,
        "incumbent_passed": 0,
        "incumbent_safety_failures": 0,
        "pass_improvement": expected_cases,
    }
    actual = {
        "challenger_passed": challenger.get("passed_count"),
        "challenger_safety_failures": challenger.get("safety_failures"),
        "incumbent_passed": incumbent.get("passed_count"),
        "incumbent_safety_failures": incumbent.get("safety_failures"),
        "pass_improvement": comparison.get("pass_improvement"),
    }
    if actual != expected:
        raise AcceptanceError(
            f"selection evidence did not prove the expected result: {actual}"
        )

    raw_cases = result.get("cases")
    if type(raw_cases) is not list or len(raw_cases) != expected_cases:
        raise AcceptanceError("Controller returned the wrong number of case traces")
    cases: list[dict[str, object]] = []
    for index, raw_case in enumerate(raw_cases):
        if type(raw_case) is not dict:
            raise AcceptanceError(f"cases[{index}] must be a JSON object")
        task = raw_case.get("task")
        incumbent_run = raw_case.get("incumbent_run")
        challenger_run = raw_case.get("challenger_run")
        observation = raw_case.get("observer_evaluation")
        if (
            type(task) is not dict
            or type(incumbent_run) is not dict
            or type(challenger_run) is not dict
            or type(observation) is not dict
        ):
            raise AcceptanceError(
                f"cases[{index}] omitted its task, runs, or observation"
            )
        incumbent_runner = incumbent_run.get("runner")
        challenger_runner = challenger_run.get("runner")
        if type(incumbent_runner) is not dict or type(challenger_runner) is not dict:
            raise AcceptanceError(f"cases[{index}] omitted runner evidence")
        cases.append(
            {
                "case_id": task.get("case_id"),
                "challenger_forecast": challenger_run.get("forecast"),
                "challenger_submission": challenger_runner.get("submission"),
                "evaluator_id": observation.get("evaluator_id"),
                "evaluator_results": observation.get("results"),
                "incumbent_forecast": incumbent_run.get("forecast"),
                "incumbent_submission": incumbent_runner.get("submission"),
            }
        )

    return {
        "cases": cases,
        "comparison": comparison,
        "decision": selection["decision"],
        "evaluation": evaluation,
        "evidence_id": selection.get("evidence_id"),
        "reason": selection.get("reason"),
    }


def _final_suite(
    development_request: dict[str, object],
) -> tuple[str, list[dict[str, object]]]:
    document = _load_document(FINAL_TASKS, "final task suite")
    try:
        require_exact_keys(document, {"evaluation", "tasks"}, "final suite")
        evaluation = require_nonempty_string(
            document["evaluation"], "final suite.evaluation"
        )
        raw_tasks = document["tasks"]
        if type(raw_tasks) is not list or not raw_tasks:
            raise ProtocolError("final suite.tasks must be a non-empty JSON array")
        tasks = [
            decode_task(task, f"final suite.tasks[{index}]")
            for index, task in enumerate(raw_tasks)
        ]
    except ProtocolError as exc:
        raise AcceptanceError(str(exc)) from exc

    generation = cast(dict[str, object], development_request["generation"])
    development_tasks = cast(list[dict[str, object]], generation["tasks"])
    development_ids = {str(task["case_id"]) for task in development_tasks}
    final_ids = [str(task["case_id"]) for task in tasks]
    if len(set(final_ids)) != len(final_ids):
        raise AcceptanceError("final suite contains duplicate case identifiers")
    if development_ids.intersection(final_ids):
        raise AcceptanceError("development and final case identifiers overlap")
    return evaluation, tasks


def run_acceptance(state_path: Path) -> dict[str, object]:
    agent_configuration = _agent_configuration()
    lock_path = Path(f"{state_path}.lock")
    if state_path.exists() or state_path.is_symlink() or lock_path.exists():
        raise AcceptanceError(
            "acceptance requires a new state path so the final suite is used once"
        )

    request = _load_document(LIVE_REQUEST, "live evolution request")
    summary = _run(
        [sys.executable, str(EVOLVER), "--state", str(state_path)],
        request,
        timeout_seconds=_evolution_timeout(request),
        location="Evolution Driver",
    )
    if set(summary) != SUMMARY_KEYS:
        raise AcceptanceError("Evolution Driver summary has the wrong shape")
    if (
        summary.get("schema_version") != 1
        or summary.get("status") != "generation_limit"
        or summary.get("completed_generations") != 1
        or summary.get("consecutive_rejections") != 0
    ):
        raise AcceptanceError("development evolution did not complete one promotion")
    try:
        head = decode_candidate(summary.get("head"), "summary.head")
    except ProtocolError as exc:
        raise AcceptanceError(str(exc)) from exc

    development_result = _state_generation(state_path)
    development = _selection_proof(
        development_result,
        evaluation="signal-relay/development-v1",
        expected_cases=1,
        expected_head=head,
    )

    final_evaluation, final_tasks = _final_suite(request)
    generation = cast(dict[str, object], request["generation"])
    runner = cast(dict[str, object], generation["runner"])
    evaluator = cast(dict[str, object], generation["evaluator"])
    final_request = {
        "evaluation": final_evaluation,
        "evaluator": evaluator,
        "mutation_request": {
            "challenger_artifact": head["artifact"],
            "parent_artifact": request["initial_parent_artifact"],
            "proposal": {
                "producer": "signal-relay-acceptance-v1",
                "reason": "one-use comparison on the predeclared final suite",
            },
            "schema_version": AGENT_SCHEMA_VERSION,
        },
        "runner": runner,
        "schema_version": AGENT_SCHEMA_VERSION,
        "selection_policy": generation["selection_policy"],
        "tasks": final_tasks,
    }
    final_result = _run(
        [sys.executable, str(CONTROLLER)],
        final_request,
        timeout_seconds=_controller_timeout(final_tasks, runner, evaluator),
        location="final Controller assay",
    )
    final = _selection_proof(
        final_result,
        evaluation=final_evaluation,
        expected_cases=len(final_tasks),
        expected_head=head,
    )

    return {
        "accepted": True,
        "acceptance_schema": "signal-relay-live-v1",
        "agent_configuration": agent_configuration,
        "development": development,
        "final_assay": final,
        "head": head,
        "run_id": summary["run_id"],
        "state_path": str(state_path),
    }


def _state_argument(argv: list[str]) -> Path:
    if len(argv) != 2 or argv[0] != "--state" or not argv[1]:
        raise AcceptanceError("usage: signal_relay_acceptance.py --state NEW_PATH")
    return Path(argv[1]).expanduser().absolute()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        state_path = _state_argument(arguments)
        result = run_acceptance(state_path)
    except (
        AcceptanceError,
        KeyError,
        ProtocolError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        write_document(sys.stderr, error_document("acceptance_failed", str(exc)))
        return 2
    write_document(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
