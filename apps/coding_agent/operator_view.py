#!/usr/bin/env python3
"""Read-only human progress and history projections for Agentvolve runs."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

from apps._support.bounded_process import OutputLimitError, communicate_bounded
from apps._support.journal import (
    decode_canonical_records,
    read_complete_lines,
    validate_content_record,
)
from apps._support.wire import canonical_json, decode_json_object, write_document
from apps.coding_agent.agentvolve_worker import (
    WORKFLOW_NAME,
    AgentvolveWorkerError,
    load_worker_status,
    load_workflow_closure,
    load_workflow_request,
    worker_is_alive,
)
from apps.coding_agent.process_tracker import (
    STAGE_LABELS,
    load_process_status,
)
from apps.population_driver.population_driver_protocol import controller_timeout_seconds

ROOT = Path(__file__).resolve().parents[2]

PROGRESS_SCHEMA = "agentvolve-progress-view-v1"
HISTORY_SCHEMA = "agentvolve-history-view-v1"
TRACE_SCHEMA = "agentvolve-trace-view-v1"
VIEW_AUTHORITY = "projection-only"
MAX_HISTORY = 50
TRACE_PAGE_SIZE = 20
MAX_LEDGER_BYTES = 64 * 1024 * 1024
MAX_DIFF_CHARS = 16_000
MAX_DIFF_LINES = 40
MAX_GIT_OUTPUT_BYTES = 1_048_576
HEARTBEAT_STALE_SECONDS = 10
HEX_ID = re.compile(r"^[0-9a-f]{40,64}$")
LEGACY_RUN_NAME = re.compile(
    r"^(?P<kind>harness|solution)-pi-\d{8}T\d{6}(?:\d{3})?Z(?:-\d+)?$"
)


class OperatorViewError(RuntimeError):
    """Raised when an Agentvolve operator projection cannot be read safely."""


def _safe_text(value: object, limit: int = 2_000) -> str:
    text = value if type(value) is str else str(value)
    sanitized = "".join(
        character if character in "\n\t" or character.isprintable() else "?"
        for character in text
    )
    return sanitized if len(sanitized) <= limit else sanitized[: limit - 1] + "…"


def _regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise OperatorViewError(f"{label} is absent or unsafe: {path}")


def _document(path: Path, label: str) -> dict[str, object]:
    _regular_file(path, label)
    try:
        source = path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise OperatorViewError(f"cannot read {label}: {exc}") from exc
    document = decode_json_object(source, OperatorViewError)
    if source != canonical_json(document) + "\n":
        raise OperatorViewError(f"{label} is not canonical")
    return document


def _optional_document(path: Path, label: str) -> dict[str, object] | None:
    if not path.exists():
        return None
    return _document(path, label)


def _records(path: Path, label: str) -> list[dict[str, object]]:
    _regular_file(path, label)
    if path.stat().st_size > MAX_LEDGER_BYTES:
        raise OperatorViewError(f"{label} exceeds the operator-view bound")
    try:
        records = decode_canonical_records(
            read_complete_lines(path, OperatorViewError, label=label),
            OperatorViewError,
            label=label,
        )
    except OSError as exc:
        raise OperatorViewError(f"cannot read {label}: {exc}") from exc
    previous: str | None = None
    for index, record in enumerate(records):
        validate_content_record(record, OperatorViewError, f"{label} record {index}")
        if record.get("parent_record_id") != previous:
            raise OperatorViewError(f"{label} record {index} breaks first-parent order")
        previous = cast(str, record["record_id"])
    return records


def _inside(directory: Path, path: Path, label: str) -> Path:
    directory = directory.absolute()
    path = path.absolute()
    try:
        relative = path.relative_to(directory)
    except ValueError as exc:
        raise OperatorViewError(
            f"{label} escapes the Agentvolve runs directory"
        ) from exc
    if len(relative.parts) != 1:
        raise OperatorViewError(
            f"{label} must be a direct child of the Agentvolve runs directory"
        )
    if path.is_symlink():
        raise OperatorViewError(f"{label} must not be a symbolic link")
    return path


def _path_value(
    request: dict[str, object],
    key: str,
    runs_directory: Path,
    *,
    optional: bool = False,
    external: bool = False,
) -> Path | None:
    value = request.get(key)
    if optional and value is None:
        return None
    if type(value) is not str or not Path(value).is_absolute():
        raise OperatorViewError(f"workflow {key} is malformed")
    path = Path(value).absolute()
    return path if external else _inside(runs_directory, path, f"workflow {key}")


def _field(document: object, key: str) -> object | None:
    return document.get(key) if type(document) is dict else None


def _integer(value: object) -> int | None:
    return value if type(value) is int else None


def _model(runtime: dict[str, object] | None) -> dict[str, str] | None:
    raw = _field(runtime, "model")
    if type(raw) is not dict:
        return None
    keys = ("connector", "provider", "model", "reasoning")
    if any(type(raw.get(key)) is not str for key in keys):
        return None
    return {key: _safe_text(raw[key], 200) for key in keys}


def _task(profile: dict[str, object] | None) -> dict[str, object] | None:
    if profile is None:
        return None
    repository = _field(profile, "repository")
    limits = _field(profile, "limits")
    goal = profile.get("goal")
    return {
        "goal": _safe_text(goal, 2_000)
        if type(goal) is str
        else "Task goal unavailable",
        "max_rounds": _integer(_field(limits, "max_rounds")),
        "repository": (
            _safe_text(repository.get("path"), 1_000)
            if type(repository) is dict and type(repository.get("path")) is str
            else None
        ),
        "task_id": _safe_text(profile.get("task_id"), 128)
        if type(profile.get("task_id")) is str
        else None,
    }


def _summary_from_report(report: dict[str, object] | None) -> dict[str, object] | None:
    if report is None:
        return None
    development = _field(report, "development")
    final = _field(report, "final")
    selected = _field(report, "selected_solution") or _field(report, "selected_harness")
    artifact = _field(selected, "artifact")
    return {
        "archive_count": _integer(_field(development, "archive_count")),
        "candidate_count": _integer(_field(development, "candidate_count")),
        "completed_rounds": _integer(_field(development, "completed_rounds")),
        "development_status": (
            _safe_text(_field(development, "status"), 200)
            if type(_field(development, "status")) is str
            else None
        ),
        "final_passed": _integer(_field(final, "passed_count")),
        "final_safety_failures": _integer(_field(final, "safety_failures")),
        "final_tasks": _integer(_field(final, "task_count")),
        "proposal_calls": _integer(_field(development, "proposal_calls")),
        "selected_candidate_id": (
            _safe_text(_field(selected, "candidate_id"), 128)
            if type(_field(selected, "candidate_id")) is str
            else None
        ),
        "selected_commit": (
            _safe_text(_field(artifact, "commit"), 128)
            if type(_field(artifact, "commit")) is str
            else None
        ),
    }


def _load_run_report(run_root: Path | None, kind: str) -> dict[str, object] | None:
    if run_root is None or not run_root.is_dir() or run_root.is_symlink():
        return None
    report = _optional_document(
        run_root / "experiment-report.json", f"{kind} experiment report"
    )
    if report is None:
        return None
    expected = (
        "evolutionary-harness-experiment-v1"
        if kind == "harness"
        else "darwinian-coding-experiment-v1"
    )
    if report.get("schema") != expected:
        raise OperatorViewError(f"{kind} experiment report has an unexpected schema")
    return report


def _driver_projection(
    run_root: Path | None, *, all_rounds: bool = False
) -> dict[str, object] | None:
    if run_root is None:
        return None
    driver_path = run_root / "state" / "driver.jsonl"
    if not driver_path.is_file() or driver_path.is_symlink():
        return None
    records = _records(driver_path, "Population Driver ledger")
    if not records:
        return None
    header = records[0]
    configuration = _field(header, "configuration")
    limits = _field(configuration, "limits")
    rounds: list[dict[str, object]] = []
    proposal_calls = 0
    latest_archive: list[str] = []
    for record in records[1:]:
        if record.get("kind") != "round":
            continue
        attempts = record.get("attempts")
        selection = record.get("selection")
        comparison = _field(selection, "comparison")
        incumbent = _field(comparison, "incumbent")
        challenger = _field(comparison, "challenger")
        attempt_count = len(attempts) if type(attempts) is list else 0
        proposal_calls += attempt_count
        members = record.get("archive_member_candidate_ids")
        latest_archive = (
            [_safe_text(item, 128) for item in members if type(item) is str]
            if type(members) is list
            else []
        )
        rounds.append(
            {
                "archive_members": len(latest_archive),
                "attempts": attempt_count,
                "challenger_passed": _integer(_field(challenger, "passed_count")),
                "child_candidate_id": _safe_text(record.get("child_candidate_id"), 128),
                "decision": _safe_text(_field(selection, "decision"), 100),
                "parent_candidate_id": _safe_text(
                    record.get("parent_candidate_id"), 128
                ),
                "parent_passed": _integer(_field(incumbent, "passed_count")),
                "retries": max(0, attempt_count - 1),
                "round": _integer(record.get("round")),
                "selected_candidate_id": _safe_text(_field(selection, "selected"), 128),
            }
        )
    pending = _optional_document(
        run_root / "state" / "pending" / "round-intent.json", "pending round intent"
    )
    pending_stage = _field(pending, "stage")
    pending_round = _integer(_field(pending, "round"))
    pending_attempt_values = _field(pending, "attempts")
    pending_attempts = (
        len(pending_attempt_values) if type(pending_attempt_values) is list else 0
    )
    pending_parent = _field(pending, "parent_candidate_id")
    activity = None
    if pending_stage == "controller_pending":
        activity = (
            "Controller effect pending; proposal and evaluation are not distinguished "
            "until an immutable receipt exists"
        )
    elif pending_stage == "controller_complete":
        activity = "Controller receipt committed; adapting trusted evidence"
    elif pending_stage == "evidence_complete":
        activity = "Evidence receipt committed; appending Population records"
    elif not rounds and pending is None and _field(_field(configuration, "generation"), "evaluation") == "darwinian-coding/development-v1":
        # Explain historical zero-round failures from the recorded timeouts, not
        # current defaults or mutable worker-status text. This never resumes a run.
        wall_limit = _integer(_field(limits, "max_wall_seconds"))
        evidence_timeout = _integer(_field(_field(configuration, "evidence_adapter"), "timeout_seconds"))
        try:
            if wall_limit is None or evidence_timeout is None:
                raise ValueError("missing integer timeout")
            required = controller_timeout_seconds(cast(dict[str, object], configuration)) + evidence_timeout
        except (KeyError, TypeError, ValueError) as exc:
            raise OperatorViewError("recorded coding development timeouts are malformed") from exc
        if required > wall_limit:
            activity = (
                f"wall_reservation_limit: first development round requires {required} reserved seconds, "
                f"but the frozen budget is {wall_limit}. No proposal round started. "
                "Resume cannot increase this budget; close as incomplete and review a new task."
            )
    return {
        "activity": activity,
        "archive_member_count": len(latest_archive),
        "completed_rounds": len(rounds),
        "max_rounds": _integer(_field(limits, "max_rounds")),
        "pending_attempts": pending_attempts,
        "pending_parent_candidate_id": (
            _safe_text(pending_parent, 128) if type(pending_parent) is str else None
        ),
        "pending_round": pending_round,
        "pending_stage": _safe_text(pending_stage, 100)
        if type(pending_stage) is str
        else None,
        "proposal_calls": proposal_calls,
        "rounds": rounds if all_rounds else rounds[-TRACE_PAGE_SIZE:],
    }


def _population_candidates(run_root: Path | None) -> dict[str, str]:
    if run_root is None:
        return {}
    ledger = run_root / "state" / "population" / "population.jsonl"
    if not ledger.is_file() or ledger.is_symlink():
        return {}
    records = _records(ledger, "Population ledger")
    candidates: dict[str, str] = {}
    for record in records:
        if record.get("kind") != "candidate":
            continue
        body = _field(record, "body")
        candidate = _field(body, "candidate")
        artifact = _field(candidate, "artifact")
        candidate_id = _field(candidate, "candidate_id")
        commit = _field(artifact, "commit")
        if (
            type(candidate_id) is str
            and type(commit) is str
            and HEX_ID.fullmatch(commit)
        ):
            candidates[candidate_id] = commit
    return candidates


def _git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_PAGER": "cat",
            "LC_ALL": "C.UTF-8",
        }
    )
    environment.pop("GIT_EXTERNAL_DIFF", None)
    return environment


def _git_output(
    repository: Path, arguments: list[str], *, max_output_bytes: int = MAX_GIT_OUTPUT_BYTES
) -> str:
    git = shutil.which("git")
    if git is None:
        raise OperatorViewError("Git is unavailable for candidate diff projection")
    if repository.is_symlink() or not repository.is_dir():
        raise OperatorViewError("candidate Git repository is absent or unsafe")
    try:
        process = subprocess.Popen(
            [
                git,
                "--git-dir",
                str(repository),
                "-c",
                "color.ui=false",
                "-c",
                "core.quotepath=false",
                *arguments,
            ],
            cwd=ROOT,
            env=_git_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr = communicate_bounded(
            process,
            None,
            timeout_seconds=5,
            max_output_bytes=max_output_bytes,
        )
    except (OSError, OutputLimitError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise OperatorViewError(
            f"bounded candidate diff is unavailable: {exc}"
        ) from exc
    if process.returncode != 0:
        raise OperatorViewError(
            stderr[-2_000:].strip() or "Git rejected the candidate diff"
        )
    return stdout


def _diff_projection(
    run_root: Path | None, driver: dict[str, object] | None
) -> dict[str, object] | None:
    if run_root is None or driver is None:
        return None
    rounds = driver.get("rounds")
    if type(rounds) is not list or not rounds:
        return None
    latest = rounds[-1]
    if type(latest) is not dict:
        return None
    parent_id = latest.get("parent_candidate_id")
    child_id = latest.get("child_candidate_id")
    candidates = _population_candidates(run_root)
    if type(parent_id) is not str or type(child_id) is not str:
        return None
    parent_commit = candidates.get(parent_id)
    child_commit = candidates.get(child_id)
    if parent_commit is None or child_commit is None:
        return None
    repository = run_root / "candidate.git"
    numstat = _git_output(
        repository,
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--numstat",
            parent_commit,
            child_commit,
            "--",
        ],
    )
    numstat_lines = numstat.splitlines()
    files_truncated = len(numstat_lines) > 200
    files: list[dict[str, object]] = []
    insertions = 0
    deletions = 0
    for raw in numstat_lines[:200]:
        fields = raw.split("\t")
        if len(fields) < 3:
            continue
        added, removed, path = fields[0], fields[1], "\t".join(fields[2:])
        added_value = int(added) if added.isdigit() else None
        removed_value = int(removed) if removed.isdigit() else None
        insertions += added_value or 0
        deletions += removed_value or 0
        files.append(
            {
                "deletions": removed_value,
                "insertions": added_value,
                "path": _safe_text(path, 500),
            }
        )
    raw_preview = _git_output(
        repository,
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--unified=2",
            parent_commit,
            child_commit,
            "--",
        ],
    )
    preview = raw_preview[:MAX_DIFF_CHARS]
    preview_lines = preview.splitlines()
    preview_truncated = (
        len(raw_preview) > MAX_DIFF_CHARS or len(preview_lines) > MAX_DIFF_LINES
    )
    lines = [_safe_text(line, 500) for line in preview_lines[:MAX_DIFF_LINES]]
    return {
        "child_candidate_id": child_id,
        "deletions": deletions,
        "files": files,
        "insertions": insertions,
        "parent_candidate_id": parent_id,
        "preview_lines": lines,
        "round": latest.get("round"),
        "summary": f"{len(files)}{'+' if files_truncated else ''} files, +{insertions}/-{deletions}",
        "truncated": files_truncated or preview_truncated,
    }


def _optional_diff(
    run_root: Path | None,
    driver: dict[str, object] | None,
    *,
    include_diff: bool,
) -> tuple[dict[str, object] | None, list[str]]:
    if not include_diff:
        return None, []
    try:
        return _diff_projection(run_root, driver), []
    except OperatorViewError as exc:
        return None, [_safe_text(exc, 500)]


def _process_stage(run_root: Path | None, kind: str, fallback: int) -> int:
    if run_root is None or not run_root.is_dir():
        return fallback
    try:
        document = load_process_status(run_root, expected_run_kind=kind)
    except Exception:
        document = None
    if document is not None:
        return int(document["stage"])
    if (run_root / "experiment-report.json").is_file():
        return 3 if kind == "harness" else 6
    if kind == "solution" and (run_root / "protected-final.json").is_file():
        return 5
    if (run_root / "state" / "driver.jsonl").is_file():
        return 2 if kind == "harness" else 4
    return fallback


def _stage_summary(
    number: int,
    *,
    task: dict[str, object] | None,
    model: dict[str, str] | None,
    harness: dict[str, object] | None,
    solution: dict[str, object] | None,
    reused_harness: bool,
    solution_root: Path | None,
) -> str:
    if number == 1:
        worker = "worker runtime unavailable"
        if model is not None:
            worker = (
                f"worker {model['provider']}/{model['model']} ({model['reasoning']})"
            )
        goal = (
            _safe_text(task.get("goal"), 180)
            if task is not None
            else "task unavailable"
        )
        return f"Task/runtime bound: {goal} · {worker}"
    if number == 2:
        if reused_harness:
            return "Reused a previously sealed harness; no Level-2 search ran in this workflow."
        if harness is None:
            return "Harness candidates are proposed and checked in isolated development runs."
        return (
            f"Harness development finished: {harness.get('completed_rounds')} rounds, "
            f"{harness.get('candidate_count')} candidates, {harness.get('proposal_calls')} proposal calls."
        )
    if number == 3:
        if harness is None:
            return "The selected harness will be fixed before solution mutation starts."
        return (
            f"Harness {str(harness.get('selected_candidate_id') or 'unknown')[:12]} sealed; "
            f"protected assay {harness.get('final_passed')}/{harness.get('final_tasks')}, "
            f"safety failures {harness.get('final_safety_failures')}."
        )
    if number == 4:
        if solution is None:
            return "Solution commits are mutating under the frozen harness and reviewed development checks."
        return (
            f"Solution development finished: {solution.get('completed_rounds')} rounds, "
            f"{solution.get('candidate_count')} candidates, {solution.get('proposal_calls')} proposal calls."
        )
    if number == 5:
        if solution is None:
            return "Protected checks remain hidden until development allocation is committed."
        return (
            f"Protected assay sealed: {solution.get('final_passed')}/{solution.get('final_tasks')} passed; "
            f"safety failures {solution.get('final_safety_failures')}."
        )
    if solution is None:
        return "A selected immutable commit and patch will be returned for review, never auto-applied."
    patch = (
        str(solution_root / "selected.patch")
        if solution_root is not None
        else "unavailable"
    )
    return (
        f"Selected commit {str(solution.get('selected_commit') or 'unknown')[:12]}; "
        f"candidate {str(solution.get('selected_candidate_id') or 'unknown')[:12]}; patch {patch}."
    )


def _stages(
    stage: int,
    state: str,
    *,
    task: dict[str, object] | None,
    model: dict[str, str] | None,
    harness: dict[str, object] | None,
    solution: dict[str, object] | None,
    reused_harness: bool,
    solution_root: Path | None,
) -> list[dict[str, object]]:
    stages: list[dict[str, object]] = []
    complete_workflow = state in {"completed", "verified"}
    for number in range(1, 7):
        if not complete_workflow and number > stage:
            status = "pending"
        elif reused_harness and number in {2, 3}:
            status = "reused"
        elif complete_workflow or number < stage:
            status = "complete"
        elif state in {"closed-incomplete", "failed", "inconsistent", "interrupted", "stalled", "stopped"}:
            status = "failed"
        elif state == "waiting-retry":
            status = "waiting-retry"
        else:
            status = "running"
        stages.append(
            {
                "label": STAGE_LABELS[number],
                "number": number,
                "status": status,
                "summary": _stage_summary(
                    number,
                    task=task,
                    model=model,
                    harness=harness,
                    solution=solution,
                    reused_harness=reused_harness,
                    solution_root=solution_root,
                ),
            }
        )
    return stages


def _workflow_progress(
    runs_directory: Path, workflow_root: Path, *, include_diff: bool
) -> dict[str, object]:
    try:
        request = load_workflow_request(workflow_root)
        status = load_worker_status(workflow_root)
        closure = load_workflow_closure(workflow_root)
    except AgentvolveWorkerError as exc:
        raise OperatorViewError(str(exc)) from exc
    if status is None:
        if closure is None:
            raise OperatorViewError("Agentvolve workflow has no worker status")
        # Startup may fail before the first status write. Closure still belongs in history.
        status = {"stage": 1, "state": "closed-incomplete", "updated_unix_ns": closure["closed_unix_ns"]}
    harness_root = _path_value(
        request, "harness_run_root", runs_directory, optional=True
    )
    solution_root = cast(
        Path, _path_value(request, "solution_run_root", runs_directory)
    )
    runtime_source = (
        solution_root / "runtime.json"
        if (solution_root / "runtime.json").is_file()
        else Path(cast(str, request["runtime_manifest"]))
    )
    task_source = (
        solution_root / "task.json"
        if (solution_root / "task.json").is_file()
        else Path(cast(str, request["task_profile"]))
    )
    runtime = _optional_document(runtime_source, "workflow runtime")
    profile = _optional_document(task_source, "workflow task")
    model = _model(runtime)
    task = _task(profile)
    harness_report = _load_run_report(harness_root, "harness")
    if harness_report is None and request.get("harness_descriptor") is not None:
        descriptor = Path(cast(str, request["harness_descriptor"]))
        source_report = descriptor.parent / "experiment-report.json"
        harness_report = _optional_document(source_report, "reused harness report")
    solution_report = _load_run_report(solution_root, "solution")
    harness_summary = _summary_from_report(harness_report)
    solution_summary = _summary_from_report(solution_report)
    stage = _integer(status.get("stage")) or 1
    state = _safe_text(status.get("state"), 100)
    alive = worker_is_alive(workflow_root)
    updated = _integer(status.get("updated_unix_ns"))
    heartbeat_age = time.time_ns() - updated if updated is not None else None
    heartbeat_fresh = (
        heartbeat_age is not None
        and heartbeat_age <= HEARTBEAT_STALE_SECONDS * 1_000_000_000
    )
    if state in {"completed", "verified"} and solution_summary is None:
        state = "inconsistent"
    elif state in {"queued", "running"} and (
        not heartbeat_fresh
        or (
            not alive
            and heartbeat_age is not None
            and heartbeat_age >= 5 * 1_000_000_000
        )
    ):
        state = "completed" if solution_summary is not None else "stalled"
    active_root = solution_root if solution_root.exists() else harness_root
    active_kind = "solution" if solution_root.exists() else "harness"
    stage = max(stage, _process_stage(active_root, active_kind, stage))
    driver = _driver_projection(active_root)
    status_error = (
        _safe_text(status.get("error"), 1_000)
        if type(status.get("error")) is str
        else None
    )
    activity = _safe_text(status.get("activity"), 1_000)
    if driver is not None and type(driver.get("activity")) is str:
        activity = cast(str, driver["activity"])
    if state == "stalled":
        activity = (
            "Worker heartbeat is stale; inspect process identity and logs, then use resume "
            "or explicit retry only as authorized."
        )
    elif status_error is not None and state in {"failed", "stopped", "waiting-retry"}:
        activity = f"{activity} Detail: {status_error}"
    if closure is not None:
        state = "closed-incomplete"
        activity = f"Operator closed this workflow without success: {_safe_text(closure['reason'], 1_000)}. Evidence is preserved; this workflow cannot resume."
    diff, warnings = _optional_diff(active_root, driver, include_diff=include_diff)
    result = None
    if solution_summary is not None:
        patch = solution_root / "selected.patch"
        if patch.is_symlink() or not patch.is_file():
            warnings.append(
                "selected patch is absent or unsafe; run offline verification"
            )
        result = {
            **solution_summary,
            "patch_path": str(solution_root / "selected.patch"),
            "run_root": str(solution_root),
        }
    return {
        "activity": activity,
        "authority": VIEW_AUTHORITY,
        "diff": diff,
        "error": status_error,
        "evolution": None if driver is None else {**driver, "kind": active_kind},
        "progress_schema": PROGRESS_SCHEMA,
        "result": result,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "stages": _stages(
            stage,
            state,
            task=task,
            model=model,
            harness=harness_summary,
            solution=solution_summary,
            reused_harness=request.get("harness_descriptor") is not None,
            solution_root=solution_root,
        ),
        "state": state,
        "task": task,
        "updated_unix_ns": status.get("updated_unix_ns"),
        "worker": {
            "alive": alive,
            "effect_pid": status.get("effect_pid"),
            "model": model,
            "pid": status.get("worker_pid"),
            "separation": "detached-operator-worker-v1",
        },
        "warnings": warnings,
        "workflow_id": request["workflow_id"],
        "workflow_root": str(workflow_root),
    }


def _legacy_pid(run_root: Path) -> tuple[int | None, bool | None]:
    lock = run_root / "state.lock"
    if not lock.is_file() or lock.is_symlink():
        return None, None
    try:
        first = lock.read_text(encoding="ascii", errors="strict").split()[0]
        pid = int(first.removeprefix("pid="))
    except (OSError, UnicodeError, ValueError, IndexError):
        return None, None
    try:
        os.kill(pid, 0)
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
    except (OSError, ProcessLookupError):
        return pid, False
    return pid, str(run_root).encode() in command


def _legacy_progress(run_root: Path, *, include_diff: bool) -> dict[str, object]:
    match = LEGACY_RUN_NAME.fullmatch(run_root.name)
    if match is None:
        raise OperatorViewError("legacy Agentvolve run name is unsupported")
    kind = match.group("kind")
    report = _load_run_report(run_root, kind)
    fallback = 1 if kind == "harness" else 4
    stage = _process_stage(run_root, kind, fallback)
    pid, alive = _legacy_pid(run_root)
    state = "completed" if report is not None else "running" if alive else "interrupted"
    runtime = _optional_document(run_root / "runtime.json", "legacy runtime")
    profile = (
        _optional_document(run_root / "task.json", "legacy task")
        if kind == "solution"
        else None
    )
    model = _model(runtime)
    task = _task(profile)
    summary = _summary_from_report(report)
    driver = _driver_projection(run_root)
    harness_summary = summary if kind == "harness" else None
    solution_summary = summary if kind == "solution" else None
    result = None
    if solution_summary is not None:
        result = {
            **solution_summary,
            "patch_path": str(run_root / "selected.patch"),
            "run_root": str(run_root),
        }
    activity = (
        cast(str, driver["activity"])
        if driver is not None and type(driver.get("activity")) is str
        else (
            "Completed legacy run; use offline verify before relying on its evidence."
            if report is not None
            else "Legacy run is not owned by a detached Agentvolve worker."
        )
    )
    diff, warnings = _optional_diff(run_root, driver, include_diff=include_diff)
    if solution_summary is not None:
        patch = run_root / "selected.patch"
        if patch.is_symlink() or not patch.is_file():
            warnings.append(
                "selected patch is absent or unsafe; run offline verification"
            )
    return {
        "activity": activity,
        "authority": VIEW_AUTHORITY,
        "diff": diff,
        "error": None,
        "evolution": None if driver is None else {**driver, "kind": kind},
        "progress_schema": PROGRESS_SCHEMA,
        "result": result,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "stages": _stages(
            stage,
            state,
            task=task,
            model=model,
            harness=harness_summary,
            solution=solution_summary,
            reused_harness=kind == "solution",
            solution_root=run_root if kind == "solution" else None,
        ),
        "state": state,
        "task": task,
        "updated_unix_ns": run_root.stat().st_mtime_ns,
        "worker": {
            "alive": alive,
            "effect_pid": None,
            "model": model,
            "pid": pid,
            "separation": "legacy-inline-or-external",
        },
        "warnings": warnings,
        "workflow_id": run_root.name,
        "workflow_root": str(run_root),
    }


def _entries(runs_directory: Path) -> list[tuple[str, Path]]:
    workflows: list[tuple[str, Path]] = []
    legacy: list[tuple[str, Path]] = []
    referenced: set[Path] = set()
    for path in runs_directory.iterdir():
        if (
            not path.is_dir()
            or path.is_symlink()
            or not WORKFLOW_NAME.fullmatch(path.name)
        ):
            continue
        workflows.append(("workflow", path))
        try:
            request = load_workflow_request(path)
        except AgentvolveWorkerError:
            continue
        for key in ("harness_run_root", "solution_run_root"):
            value = request.get(key)
            if type(value) is str:
                referenced.add(Path(value).absolute())
    for path in runs_directory.iterdir():
        if (
            path.is_dir()
            and not path.is_symlink()
            and LEGACY_RUN_NAME.fullmatch(path.name)
            and path.absolute() not in referenced
        ):
            legacy.append(("legacy", path))

    def timestamp(item: tuple[str, Path]) -> str:
        name = item[1].name
        return name.split("-pi-", 1)[1] if "-pi-" in name else name

    return sorted(workflows + legacy, key=timestamp, reverse=True)


def _select_latest(runs_directory: Path) -> tuple[str, Path]:
    entries = _entries(runs_directory)
    if not entries:
        raise OperatorViewError(f"no Agentvolve runs exist under {runs_directory}")
    # An abandoned unfinished run must not displace a newer completed run.
    return entries[0]


def _selected_run(
    runs_directory: Path, selector: str | None
) -> tuple[str, Path]:
    runs_directory = runs_directory.expanduser().absolute()
    if runs_directory.is_symlink() or not runs_directory.is_dir():
        raise OperatorViewError(
            f"Agentvolve runs directory is absent or unsafe: {runs_directory}"
        )
    if selector is None:
        kind, root = _select_latest(runs_directory)
    else:
        supplied = Path(selector)
        root = (
            supplied.absolute()
            if supplied.is_absolute()
            else (runs_directory / selector).absolute()
        )
        _inside(runs_directory, root, "selected Agentvolve run")
        if not root.is_dir():
            raise OperatorViewError(f"selected Agentvolve run is unavailable: {root}")
        kind = "workflow" if WORKFLOW_NAME.fullmatch(root.name) else "legacy"
        if kind == "legacy" and not LEGACY_RUN_NAME.fullmatch(root.name):
            raise OperatorViewError("selected Agentvolve run name is unsupported")
    return kind, root


def progress_view(
    runs_directory: Path,
    selector: str | None = None,
    *,
    include_diff: bool = True,
) -> dict[str, object]:
    runs_directory = runs_directory.expanduser().absolute()
    kind, root = _selected_run(runs_directory, selector)
    return (
        _workflow_progress(runs_directory, root, include_diff=include_diff)
        if kind == "workflow"
        else _legacy_progress(root, include_diff=include_diff)
    )


def _page(offset: int, total: int, size: int) -> dict[str, object]:
    if type(offset) is not int or offset < 0:
        raise OperatorViewError("page offset must be a nonnegative integer")
    return {
        "offset": offset,
        "page_size": size,
        "next_offset": offset + size if offset + size < total else None,
    }


def trace_sources(
    runs_directory: Path, selector: str
) -> tuple[Path, list[tuple[str, Path, bool]]]:
    """Resolve only a selected run and its bound harness/solution sources."""
    runs_directory = runs_directory.expanduser().absolute()
    _kind, root = _selected_run(runs_directory, selector)
    sources: list[tuple[str, Path, bool]] = []
    if WORKFLOW_NAME.fullmatch(root.name):
        request = load_workflow_request(root)
        harness = _path_value(request, "harness_run_root", runs_directory, optional=True)
        if harness is not None:
            sources.append(("harness", harness, False))
        elif type(request.get("harness_descriptor")) is str:
            descriptor = Path(cast(str, request["harness_descriptor"]))
            _regular_file(descriptor, "reused harness descriptor")
            sources.append(("harness", descriptor.parent, True))
        solution = cast(Path, _path_value(request, "solution_run_root", runs_directory))
        sources.append(("solution", solution, False))
    else:
        match = LEGACY_RUN_NAME.fullmatch(root.name)
        assert match is not None  # _selected_run already checked the selected name
        sources.append((match.group("kind"), root, False))
    return root, sources


def trace_view(
    runs_directory: Path, selector: str, offset: int = 0
) -> dict[str, object]:
    """Page all recorded generations, keeping reused Level-2 evidence distinct."""
    root, sources = trace_sources(runs_directory, selector)
    experiments: list[dict[str, object]] = []
    rounds: list[dict[str, object]] = []
    for kind, run_root, reused in sources:
        if run_root.is_symlink():
            raise OperatorViewError("trace source must not be a symbolic link")
        driver = _driver_projection(run_root, all_rounds=True)
        experiments.append({
            "kind": kind,
            "run_root": str(run_root),
            "reused": reused,
            "report": _summary_from_report(_load_run_report(run_root, kind)),
        })
        if driver is not None:
            rounds.extend(
                {**record, "kind": kind, "run_root": str(run_root)}
                for record in cast(list[dict[str, object]], driver["rounds"])
            )
    page = _page(offset, len(rounds), TRACE_PAGE_SIZE)
    return {
        "authority": VIEW_AUTHORITY,
        "trace_schema": TRACE_SCHEMA,
        "workflow_root": str(root),
        "experiments": experiments,
        "rounds": rounds[offset:offset + TRACE_PAGE_SIZE],
        "total_rounds": len(rounds),
        **page,
    }


def history_view(runs_directory: Path, offset: int = 0) -> dict[str, object]:
    runs_directory = runs_directory.expanduser().absolute()
    if runs_directory.is_symlink() or (runs_directory.exists() and not runs_directory.is_dir()):
        raise OperatorViewError(f"Agentvolve runs directory is unsafe: {runs_directory}")
    entries = _entries(runs_directory) if runs_directory.exists() else []
    page = _page(offset, len(entries), MAX_HISTORY)
    runs: list[dict[str, object]] = []
    for _kind, path in entries[offset:offset + MAX_HISTORY]:
        try:
            progress = progress_view(runs_directory, path.name, include_diff=False)
            task = progress.get("task")
            runs.append(
                {
                    "goal": _field(task, "goal"),
                    "id": progress["workflow_id"],
                    "name": path.name,
                    "stage": progress["stage"],
                    "stage_label": progress["stage_label"],
                    "state": progress["state"],
                    "updated_unix_ns": progress["updated_unix_ns"],
                }
            )
        except Exception as exc:
            runs.append(
                {
                    "goal": None,
                    "id": path.name,
                    "name": path.name,
                    "stage": None,
                    "stage_label": "Unreadable",
                    "state": "unreadable",
                    "updated_unix_ns": path.stat().st_mtime_ns,
                    "warning": _safe_text(exc, 500),
                }
            )
    return {
        "authority": VIEW_AUTHORITY,
        "history_schema": HISTORY_SCHEMA,
        "runs": runs,
        "runs_directory": str(runs_directory),
        "total_runs": len(entries),
        **page,
    }


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(arguments) in {2, 3} and arguments[0] == "progress":
            result = progress_view(
                Path(arguments[1]), arguments[2] if len(arguments) == 3 else None
            )
        elif len(arguments) in {2, 3} and arguments[0] == "history":
            result = history_view(Path(arguments[1]), int(arguments[2]) if len(arguments) == 3 else 0)
        elif len(arguments) in {3, 4} and arguments[0] == "trace":
            result = trace_view(Path(arguments[1]), arguments[2], int(arguments[3]) if len(arguments) == 4 else 0)
        elif arguments and arguments[0] in {"tree", "candidate", "loops", "loop"}:
            from apps.coding_agent.candidate_view import inspect_view

            result = inspect_view(arguments)
        else:
            raise OperatorViewError(
                "usage: operator_view.py progress RUNS [RUN_NAME] | history RUNS [OFFSET] | trace RUNS RUN_NAME [OFFSET] | "
                "tree RUNS RUN [OFFSET] | candidate RUNS RUN H0|S0 [EVENT_OFFSET] [DIFF_OFFSET] | "
                "loops RUNS RUN [OFFSET] | loop RUNS RUN HR1|SR1 [EVENT_OFFSET]"
            )
    except (OSError, OperatorViewError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    write_document(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
