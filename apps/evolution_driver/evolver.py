"""Repeat the six-app agent-skill generation under explicit bounded state."""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, cast

ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from agent_protocol import (  # noqa: E402
    AGENT_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_SCHEMA,
    ProtocolError,
    candidate_record,
    decode_candidate,
    decode_command,
    decode_task,
    normalize_json_value,
    require_bool,
    require_exact_keys,
    require_nonempty_string,
    require_timeout,
)
from stdio_connector import (  # noqa: E402
    JsonProcessError,
    canonical_digest,
    canonical_json,
    decode_json_object,
    error_document,
    run_json_process,
    write_document,
)

DRIVER_SCHEMA_VERSION = 1
CONTROLLER = ROOT / "apps" / "controller" / "controller.py"
HEADER_KEYS = {
    "config_id",
    "kind",
    "record_id",
    "schema_version",
}
GENERATION_KEYS = {
    "controller_request",
    "controller_result",
    "generation",
    "kind",
    "parent_record_id",
    "record_id",
    "schema_version",
}


class RequestError(ValueError):
    """Raised when an evolution-driver request is malformed."""


class EvolutionError(RuntimeError):
    """Raised when recurrence, persistence, or a component fails."""


def _positive_integer(value: object, location: str) -> int:
    if type(value) is not int or value < 1:
        raise ProtocolError(f"{location} must be a positive integer")
    return value


def _single_skill_candidate(value: object, location: str) -> dict[str, object]:
    candidate = candidate_record(value, location)
    artifact = cast(dict[str, object], candidate["artifact"])
    if artifact["artifact_schema"] == DEFAULT_ARTIFACT_SCHEMA:
        return candidate
    files = cast(list[dict[str, object]], artifact["files"])
    if len(files) != 1 or files[0]["path"] != "SKILL.md":
        raise ProtocolError(f"{location} must contain exactly one SKILL.md file")
    if files[0]["executable"] is not False:
        raise ProtocolError(f"{location} SKILL.md must not be executable")
    return candidate


def _decode_component(value: object, location: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(value, {"command", "timeout_seconds"}, location)
    return {
        "command": decode_command(value["command"], f"{location}.command"),
        "timeout_seconds": require_timeout(
            value["timeout_seconds"], f"{location}.timeout_seconds"
        ),
    }


def decode_request(source: str) -> dict[str, object]:
    request = decode_json_object(source, RequestError)
    try:
        require_exact_keys(
            request,
            {
                "schema_version",
                "initial_parent_artifact",
                "proposal",
                "generation",
                "limits",
            },
            "request",
        )
        if (
            type(request["schema_version"]) is not int
            or request["schema_version"] != DRIVER_SCHEMA_VERSION
        ):
            raise ProtocolError(
                f"schema_version must be {DRIVER_SCHEMA_VERSION}"
            )
        initial_parent = _single_skill_candidate(
            request["initial_parent_artifact"], "initial_parent_artifact"
        )

        proposal = request["proposal"]
        if type(proposal) is not dict:
            raise ProtocolError("proposal must be a JSON object")
        require_exact_keys(
            proposal,
            {"command", "context", "timeout_seconds"},
            "proposal",
        )
        proposal_document = {
            "command": decode_command(proposal["command"], "proposal.command"),
            "context": normalize_json_value(proposal["context"], "proposal.context"),
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
        raw_tasks = generation["tasks"]
        if type(raw_tasks) is not list or not raw_tasks:
            raise ProtocolError("generation.tasks must be a non-empty JSON array")
        tasks: list[dict[str, object]] = []
        seen: set[str] = set()
        for index, raw_task in enumerate(raw_tasks):
            task = decode_task(raw_task, f"generation.tasks[{index}]")
            case_id = str(task["case_id"])
            if case_id in seen:
                raise ProtocolError(
                    f"duplicate generation task case identifier: {case_id}"
                )
            seen.add(case_id)
            tasks.append(task)
        policy = generation["selection_policy"]
        if type(policy) is not dict:
            raise ProtocolError("generation.selection_policy must be a JSON object")
        require_exact_keys(
            policy,
            {"minimum_pass_improvement", "reject_safety_regression", "type"},
            "generation.selection_policy",
        )
        if policy["type"] != "task-pass-count-v1":
            raise ProtocolError(
                "generation.selection_policy.type must be task-pass-count-v1"
            )
        minimum = _positive_integer(
            policy["minimum_pass_improvement"],
            "generation.selection_policy.minimum_pass_improvement",
        )
        reject_safety = require_bool(
            policy["reject_safety_regression"],
            "generation.selection_policy.reject_safety_regression",
        )
        generation_document = {
            "evaluation": require_nonempty_string(
                generation["evaluation"], "generation.evaluation"
            ),
            "evaluator": _decode_component(
                generation["evaluator"], "generation.evaluator"
            ),
            "runner": _decode_component(generation["runner"], "generation.runner"),
            "selection_policy": {
                "minimum_pass_improvement": minimum,
                "reject_safety_regression": reject_safety,
                "type": "task-pass-count-v1",
            },
            "tasks": tasks,
        }

        limits = request["limits"]
        if type(limits) is not dict:
            raise ProtocolError("limits must be a JSON object")
        require_exact_keys(
            limits,
            {"max_consecutive_rejections", "max_generations", "max_wall_seconds"},
            "limits",
        )
        limits_document = {
            "max_consecutive_rejections": _positive_integer(
                limits["max_consecutive_rejections"],
                "limits.max_consecutive_rejections",
            ),
            "max_generations": _positive_integer(
                limits["max_generations"], "limits.max_generations"
            ),
            "max_wall_seconds": _positive_integer(
                limits["max_wall_seconds"], "limits.max_wall_seconds"
            ),
        }
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc

    return {
        "generation": generation_document,
        "initial_parent": initial_parent,
        "limits": limits_document,
        "proposal": proposal_document,
        "schema_version": DRIVER_SCHEMA_VERSION,
    }


def _with_record_id(payload: dict[str, object]) -> dict[str, object]:
    return {**payload, "record_id": canonical_digest(payload)}


def _validate_record_id(record: dict[str, object], location: str) -> None:
    supplied = record.get("record_id")
    if (
        type(supplied) is not str
        or len(supplied) != 64
        or any(character not in "0123456789abcdef" for character in supplied)
    ):
        raise EvolutionError(f"{location}.record_id is invalid")
    payload = {key: value for key, value in record.items() if key != "record_id"}
    if canonical_digest(payload) != supplied:
        raise EvolutionError(f"{location}.record_id does not match its content")


def _read_records(path: Path) -> list[dict[str, object]]:
    if path.is_symlink():
        raise EvolutionError(f"state path may not be a symlink: {path}")
    if not path.exists():
        return []
    if not path.is_file():
        raise EvolutionError(f"state path is not a file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EvolutionError(f"cannot read state: {exc}") from exc
    if not text or not text.endswith("\n"):
        raise EvolutionError("state must contain complete newline-terminated records")

    records: list[dict[str, object]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise EvolutionError(f"state line {index} is empty")
        try:
            record = decode_json_object(line, EvolutionError)
        except EvolutionError:
            raise
        if line != canonical_json(record):
            raise EvolutionError(f"state line {index} is not canonical JSON")
        records.append(record)
    return records


def _append_record(path: Path, record: dict[str, object]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(record) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise EvolutionError(f"cannot append state: {exc}") from exc


@contextmanager
def _locked_state(path: Path) -> Iterator[None]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EvolutionError(f"cannot create state directory: {exc}") from exc
    lock = Path(f"{path}.lock")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise EvolutionError(f"state is locked: {lock}") from exc
    except OSError as exc:
        raise EvolutionError(f"cannot lock state: {exc}") from exc
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError as exc:
            raise EvolutionError(f"cannot remove state lock: {exc}") from exc


def _feedback(result: dict[str, object], generation: int) -> dict[str, object]:
    selection = result.get("selection")
    next_parent = result.get("next_parent")
    if type(selection) is not dict or type(next_parent) is not dict:
        raise EvolutionError("Controller result omitted selection or next_parent")
    return {
        "comparison": normalize_json_value(
            selection.get("comparison"), "selection.comparison"
        ),
        "decision": require_nonempty_string(
            selection.get("decision"), "selection.decision"
        ),
        "generation": generation,
        "reason": require_nonempty_string(selection.get("reason"), "selection.reason"),
        "selected_candidate_id": require_nonempty_string(
            next_parent.get("candidate_id"), "next_parent.candidate_id"
        ),
    }


def _controller_request(
    config: dict[str, object],
    parent: dict[str, object],
    generation_number: int,
    previous: dict[str, object] | None,
) -> dict[str, object]:
    generation = cast(dict[str, object], config["generation"])
    proposal = cast(dict[str, object], config["proposal"])
    return {
        "evaluation": generation["evaluation"],
        "evaluator": generation["evaluator"],
        "mutation_request": {
            "parent_artifact": parent["artifact"],
            "proposal_context": {
                "generation": generation_number,
                "objective": proposal["context"],
                "previous_generation": previous,
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


def _validate_controller_result(
    request: dict[str, object], result: dict[str, object]
) -> dict[str, object]:
    if result.get("schema_version") != AGENT_SCHEMA_VERSION or type(
        result.get("schema_version")
    ) is not int:
        raise EvolutionError("Controller returned the wrong schema version")
    mutation = result.get("mutation")
    if type(mutation) is not dict:
        raise EvolutionError("Controller result.mutation must be a JSON object")
    try:
        parent = decode_candidate(mutation.get("parent"), "result.mutation.parent")
        challenger = decode_candidate(
            mutation.get("child"), "result.mutation.child"
        )
        next_parent = decode_candidate(result.get("next_parent"), "result.next_parent")
        expected_parent = candidate_record(
            cast(dict[str, object], request["mutation_request"])["parent_artifact"],
            "request.mutation_request.parent_artifact",
        )
    except ProtocolError as exc:
        raise EvolutionError(str(exc)) from exc
    if parent != expected_parent:
        raise EvolutionError("Controller changed the requested parent")
    if parent["candidate_id"] == challenger["candidate_id"]:
        raise EvolutionError("Controller returned identical parent and challenger")
    if next_parent["candidate_id"] not in {
        parent["candidate_id"],
        challenger["candidate_id"],
    }:
        raise EvolutionError("Controller selected an unknown candidate")
    selection = result.get("selection")
    if type(selection) is not dict or selection.get("selected") != next_parent[
        "candidate_id"
    ]:
        raise EvolutionError("Controller selection does not match next_parent")
    expected_decision = (
        "promote_challenger"
        if next_parent["candidate_id"] == challenger["candidate_id"]
        else "retain_incumbent"
    )
    if selection.get("decision") != expected_decision:
        raise EvolutionError("Controller decision does not match next_parent")
    if result.get("evaluation") != request["evaluation"]:
        raise EvolutionError("Controller changed the evaluation identifier")
    return next_parent


def _verify_ledger(
    records: list[dict[str, object]], config: dict[str, object], config_id: str
) -> tuple[dict[str, object], dict[str, object] | None, int, int, str]:
    if not records:
        raise EvolutionError("state header is missing")
    header = records[0]
    if set(header) != HEADER_KEYS or header.get("kind") != "run":
        raise EvolutionError("state header has the wrong shape")
    if header.get("schema_version") != DRIVER_SCHEMA_VERSION or type(
        header.get("schema_version")
    ) is not int:
        raise EvolutionError("state header has the wrong schema version")
    if header.get("config_id") != config_id:
        raise EvolutionError("state belongs to a different evolution request")
    _validate_record_id(header, "state header")

    parent = cast(dict[str, object], config["initial_parent"])
    previous_feedback: dict[str, object] | None = None
    previous_id = str(header["record_id"])
    rejections = 0
    generation_count = 0
    for index, record in enumerate(records[1:], start=1):
        location = f"state generation {index}"
        if set(record) != GENERATION_KEYS or record.get("kind") != "generation":
            raise EvolutionError(f"{location} has the wrong shape")
        if record.get("schema_version") != DRIVER_SCHEMA_VERSION or type(
            record.get("schema_version")
        ) is not int:
            raise EvolutionError(f"{location} has the wrong schema version")
        if record.get("generation") != index or type(record.get("generation")) is not int:
            raise EvolutionError(f"{location} is out of sequence")
        if record.get("parent_record_id") != previous_id:
            raise EvolutionError(f"{location} has a broken parent link")
        _validate_record_id(record, location)
        expected_request = _controller_request(
            config, parent, index, previous_feedback
        )
        if record.get("controller_request") != expected_request:
            raise EvolutionError(f"{location} request does not match recurrence")
        result = record.get("controller_result")
        if type(result) is not dict:
            raise EvolutionError(f"{location} result must be a JSON object")
        next_parent = _validate_controller_result(expected_request, result)
        previous_feedback = _feedback(result, index)
        decision = previous_feedback["decision"]
        rejections = rejections + 1 if decision == "retain_incumbent" else 0
        parent = next_parent
        previous_id = str(record["record_id"])
        generation_count = index
    return parent, previous_feedback, generation_count, rejections, previous_id


def _controller_timeout(config: dict[str, object]) -> int:
    generation = cast(dict[str, object], config["generation"])
    proposal = cast(dict[str, object], config["proposal"])
    runner = cast(dict[str, object], generation["runner"])
    evaluator = cast(dict[str, object], generation["evaluator"])
    tasks = cast(list[dict[str, object]], generation["tasks"])
    component_margin = 10
    return (
        int(proposal["timeout_seconds"])
        + component_margin
        + len(tasks)
        * (
            2 * (int(runner["timeout_seconds"]) + component_margin)
            + int(evaluator["timeout_seconds"])
            + component_margin
        )
        + 4 * component_margin
    )


def _run_controller(
    request: dict[str, object], timeout_seconds: int
) -> dict[str, object]:
    try:
        source = run_json_process(
            [sys.executable, str(CONTROLLER)],
            request,
            cwd=ROOT,
            timeout_seconds=timeout_seconds,
        )
    except JsonProcessError as exc:
        if exc.kind == "timeout":
            message = "Controller exceeded its derived component timeout"
        elif exc.kind == "start":
            message = f"cannot start Controller: {exc.detail}"
        elif exc.kind == "exit":
            message = exc.stderr.strip() or f"Controller exited with {exc.returncode}"
        else:
            message = "Controller wrote unexpected standard error"
        raise EvolutionError(message) from exc
    try:
        result = decode_json_object(source, EvolutionError)
    except EvolutionError:
        raise
    if source != canonical_json(result) + "\n":
        raise EvolutionError("Controller returned non-canonical JSON")
    return result


def evolve(config: dict[str, object], state_path: Path) -> dict[str, object]:
    config_id = canonical_digest(config)
    limits = cast(dict[str, int], config["limits"])
    with _locked_state(state_path):
        records = _read_records(state_path)
        if not records:
            header = _with_record_id(
                {
                    "config_id": config_id,
                    "kind": "run",
                    "schema_version": DRIVER_SCHEMA_VERSION,
                }
            )
            _append_record(state_path, header)
            records = [header]

        (
            parent,
            previous_feedback,
            generation_count,
            rejection_count,
            previous_id,
        ) = _verify_ledger(records, config, config_id)
        deadline_ns = time.monotonic_ns() + limits["max_wall_seconds"] * 1_000_000_000
        controller_timeout = _controller_timeout(config)

        while True:
            now_ns = time.monotonic_ns()
            if rejection_count >= limits["max_consecutive_rejections"]:
                status = "rejection_limit"
                break
            if generation_count >= limits["max_generations"]:
                status = "generation_limit"
                break
            if now_ns >= deadline_ns:
                status = "wall_clock_limit"
                break

            generation_number = generation_count + 1
            controller_request = _controller_request(
                config,
                parent,
                generation_number,
                previous_feedback,
            )
            controller_result = _run_controller(
                controller_request, controller_timeout
            )
            next_parent = _validate_controller_result(
                controller_request, controller_result
            )
            record = _with_record_id(
                {
                    "controller_request": controller_request,
                    "controller_result": controller_result,
                    "generation": generation_number,
                    "kind": "generation",
                    "parent_record_id": previous_id,
                    "schema_version": DRIVER_SCHEMA_VERSION,
                }
            )
            _append_record(state_path, record)
            previous_id = str(record["record_id"])
            generation_count = generation_number
            previous_feedback = _feedback(controller_result, generation_number)
            if previous_feedback["decision"] == "retain_incumbent":
                rejection_count += 1
            else:
                rejection_count = 0
            parent = next_parent

    return {
        "completed_generations": generation_count,
        "consecutive_rejections": rejection_count,
        "head": parent,
        "last_record_id": previous_id,
        "run_id": config_id,
        "schema_version": DRIVER_SCHEMA_VERSION,
        "state_path": str(state_path),
        "status": status,
    }


def _read_stdin() -> str:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return sys.stdin.read()
    try:
        return stream.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RequestError("standard input must be valid UTF-8 JSON") from exc


def _state_argument(argv: list[str]) -> Path:
    if len(argv) != 2 or argv[0] != "--state" or not argv[1]:
        raise RequestError("usage: evolver.py --state PATH")
    path = Path(argv[1]).expanduser().absolute()
    if path.name in {"", ".", ".."}:
        raise RequestError("state path must name a file")
    return path


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        state_path = _state_argument(arguments)
        config = decode_request(_read_stdin())
        response = evolve(config, state_path)
    except RequestError as exc:
        write_document(sys.stderr, error_document("invalid_request", str(exc)))
        return 2
    except (EvolutionError, ProtocolError, OSError) as exc:
        write_document(sys.stderr, error_document("evolution_error", str(exc)))
        return 2
    write_document(sys.stdout, response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
