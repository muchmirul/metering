#!/usr/bin/env python3
"""Detached operator/worker orchestration for the Agentvolve Pi workflow."""

from __future__ import annotations

import fcntl
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, cast

from apps._support.durable import atomic_write, reject_symlink
from apps._support.wire import (
    canonical_digest,
    canonical_json,
    decode_json_object,
    write_document,
)
from apps.coding_agent.harness_workspace_editor import CodingMutationError
from apps.coding_agent.preflight import preflight_task
from apps.coding_agent import pi_execution
from apps.coding_agent.process_tracker import (
    STAGE_LABELS,
    load_process_status,
)
from apps.coding_agent.protocol import CodingTaskError, load_task_profile
from apps.harness.runtime_manifest import RuntimeManifestError, load_runtime_manifest
from artifacts.git.git_repository import GitCandidateError

ROOT = Path(__file__).resolve().parents[2]

WORKFLOW_REQUEST_SCHEMA = "agentvolve-worker-request-v1"
WORKFLOW_JOB_SCHEMA = "agentvolve-worker-job-v1"
WORKFLOW_STATUS_SCHEMA = "agentvolve-worker-status-v1"
WORKFLOW_AUTHORITY = "operator-orchestration-only"
STATUS_AUTHORITY = "projection-only"
WORKFLOW_NAME = re.compile(r"^workflow-pi-\d{8}T\d{9}Z(?:-\d+)?$")
RUN_NAME = re.compile(r"^(?:harness|solution)-pi-\d{8}T\d{9}Z(?:-\d+)?$")
MAX_DIAGNOSTIC_BYTES = 8_192
HEARTBEAT_SECONDS = 2.0
STOP_GRACE_SECONDS = 5.0
STOP_POLL_SECONDS = 0.05


class AgentvolveWorkerError(RuntimeError):
    """Raised when detached workflow orchestration is malformed or unsafe."""


def _absolute_path(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise AgentvolveWorkerError(f"{label} must be an absolute path")
    return path.absolute()


def _regular_file(path: Path, label: str) -> None:
    reject_symlink(path, label, AgentvolveWorkerError)
    if not path.is_file():
        raise AgentvolveWorkerError(f"{label} is unavailable: {path}")


def _canonical_document(path: Path, label: str) -> dict[str, object]:
    _regular_file(path, label)
    try:
        source = path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise AgentvolveWorkerError(f"cannot read {label}: {exc}") from exc
    document = decode_json_object(source, AgentvolveWorkerError)
    if source != canonical_json(document) + "\n":
        raise AgentvolveWorkerError(f"{label} is not canonical")
    return document


def _write_canonical(path: Path, document: dict[str, object]) -> None:
    atomic_write(path, (canonical_json(document) + "\n").encode("ascii"))


def _timestamp() -> str:
    now = time.time_ns()
    seconds, nanoseconds = divmod(now, 1_000_000_000)
    return (
        time.strftime("%Y%m%dT%H%M%S", time.gmtime(seconds))
        + f"{nanoseconds // 1_000_000:03d}Z"
    )


def _new_path(parent: Path, prefix: str) -> Path:
    stamp = _timestamp()
    candidate = parent / f"{prefix}-pi-{stamp}"
    suffix = 1
    while candidate.exists():
        candidate = parent / f"{prefix}-pi-{stamp}-{suffix}"
        suffix += 1
    return candidate


def _validate_runs_directory(path: Path, *, create: bool) -> None:
    reject_symlink(path, "Agentvolve runs directory", AgentvolveWorkerError)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise AgentvolveWorkerError(f"Agentvolve runs directory is unavailable: {path}")


def _runtime_model(runtime_path: Path) -> dict[str, str]:
    document = _canonical_document(runtime_path, "runtime manifest")
    model = document.get("model")
    if type(model) is not dict:
        raise AgentvolveWorkerError("runtime manifest has no model identity")
    required = ("connector", "provider", "model", "reasoning")
    if any(
        type(model.get(key)) is not str or not str(model[key]).strip()
        for key in required
    ):
        raise AgentvolveWorkerError("runtime manifest model identity is malformed")
    return {key: str(model[key]) for key in required}


def _completed_run(run_root: Path, kind: str) -> bool:
    report_path = run_root / "experiment-report.json"
    if not report_path.exists():
        return False
    report = _canonical_document(report_path, f"{kind} experiment report")
    expected = (
        "evolutionary-harness-experiment-v1"
        if kind == "harness"
        else "darwinian-coding-experiment-v1"
    )
    if report.get("schema") != expected:
        raise AgentvolveWorkerError(
            f"{kind} experiment report has an unexpected schema"
        )
    marker = run_root / (
        "selected-harness.json" if kind == "harness" else "selected-solution.json"
    )
    _regular_file(marker, f"selected {kind} descriptor")
    return True


def _preflight_workflow(
    task_profile: Path,
    runtime_manifest: Path,
    harness_descriptor: Path | None,
) -> None:
    try:
        task = load_task_profile(task_profile)
        runtime = load_runtime_manifest(runtime_manifest)
        preflight_task(task, runtime=runtime, harness_source=harness_descriptor)
    except (
        CodingMutationError,
        CodingTaskError,
        GitCandidateError,
        OSError,
        RuntimeManifestError,
        TypeError,
        ValueError,
    ) as exc:
        raise AgentvolveWorkerError(str(exc) or type(exc).__name__) from exc


def _request_path(workflow_root: Path) -> Path:
    return workflow_root / "workflow.json"


def _status_path(workflow_root: Path) -> Path:
    return workflow_root / "worker-status.json"


def load_workflow_request(workflow_root: Path) -> dict[str, object]:
    """Load and replay one immutable operator workflow request."""

    request = _canonical_document(
        _request_path(workflow_root), "Agentvolve workflow request"
    )
    expected = {
        "agent",
        "authority",
        "created_unix_ns",
        "harness_descriptor",
        "harness_run_root",
        "repository_root",
        "runtime_manifest",
        "solution_run_root",
        "task_profile",
        "workflow_id",
        "workflow_schema",
    }
    schema = request.get("workflow_schema")
    if schema == pi_execution.WORKFLOW_SCHEMA:
        expected.add("pi_execution")
    if (
        set(request) != expected
        or schema not in (WORKFLOW_REQUEST_SCHEMA, pi_execution.WORKFLOW_SCHEMA)
    ):
        raise AgentvolveWorkerError(
            "Agentvolve workflow request has an unexpected schema"
        )
    if request.get("authority") != WORKFLOW_AUTHORITY or request.get("agent") != "pi":
        raise AgentvolveWorkerError(
            "Agentvolve workflow request changed its authority or agent"
        )
    workflow_id = request.get("workflow_id")
    identity = {key: value for key, value in request.items() if key != "workflow_id"}
    if type(workflow_id) is not str or workflow_id != canonical_digest(identity):
        raise AgentvolveWorkerError(
            "Agentvolve workflow request identity does not replay"
        )
    if request.get("repository_root") != str(ROOT):
        raise AgentvolveWorkerError("Agentvolve workflow repository root changed")
    if schema == pi_execution.WORKFLOW_SCHEMA:
        try:
            pi_execution.validate_record(request["pi_execution"], workflow_root)
            if request["harness_descriptor"] is None or request["harness_run_root"] is not None:
                raise pi_execution.PiConfigurationError("Configured Pi workflows require an explicit sealed harness")
        except ValueError as exc:
            raise AgentvolveWorkerError(str(exc)) from exc
    return request


def _execution_environment(workflow_root: Path, request: dict, *, probe: bool = False) -> dict[str, str]:
    try:
        return pi_execution.child_environment(workflow_root, request, probe=probe)
    except (ValueError, OSError) as exc:
        raise AgentvolveWorkerError(str(exc)) from exc


def _load_job(path: Path) -> dict[str, object]:
    job = _canonical_document(path, "Agentvolve worker job")
    if set(job) != {"action", "job_schema", "ordinal", "reason", "workflow_id"}:
        raise AgentvolveWorkerError("Agentvolve worker job has unexpected fields")
    if job.get("job_schema") != WORKFLOW_JOB_SCHEMA:
        raise AgentvolveWorkerError("Agentvolve worker job has an unexpected schema")
    action = job.get("action")
    reason = job.get("reason")
    if action not in {"start", "resume", "retry", "verify"}:
        raise AgentvolveWorkerError("Agentvolve worker job action is unsupported")
    if type(job.get("ordinal")) is not int or cast(int, job["ordinal"]) < 1:
        raise AgentvolveWorkerError("Agentvolve worker job ordinal is malformed")
    if action == "retry":
        if type(reason) is not str or not reason.strip() or "\x00" in reason:
            raise AgentvolveWorkerError(
                "Agentvolve retry reason must be non-empty text"
            )
    elif reason is not None:
        raise AgentvolveWorkerError("only an Agentvolve retry job may contain a reason")
    return job


def _process_start_token(pid: int) -> str | None:
    if pid <= 0:
        return None
    path = Path("/proc") / str(pid) / "stat"
    try:
        fields = path.read_text(encoding="ascii").split()
    except (OSError, UnicodeError):
        return None
    return fields[21] if len(fields) > 21 and fields[2] != "Z" else None


def _worker_alive(workflow_root: Path, status: dict[str, object]) -> bool:
    pid = status.get("worker_pid")
    token = status.get("worker_start_token")
    if type(pid) is not int or pid <= 0 or type(token) is not str:
        return False
    if _process_start_token(pid) != token:
        return False
    try:
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return (
        b"apps.coding_agent.agentvolve_worker" in command
        and str(workflow_root).encode() in command
    )


def load_worker_status(workflow_root: Path) -> dict[str, object] | None:
    path = _status_path(workflow_root)
    if not path.exists():
        return None
    status = _canonical_document(path, "Agentvolve worker status")
    expected = {
        "activity",
        "authority",
        "effect_pid",
        "error",
        "job_action",
        "job_ordinal",
        "job_started_unix_ns",
        "sequence",
        "stage",
        "stage_label",
        "state",
        "status_schema",
        "updated_unix_ns",
        "worker_pid",
        "worker_start_token",
        "workflow_id",
    }
    stage = status.get("stage")
    state = status.get("state")
    pid = status.get("worker_pid")
    effect_pid = status.get("effect_pid")
    if (
        set(status) != expected
        or status.get("status_schema") != WORKFLOW_STATUS_SCHEMA
        or status.get("authority") != STATUS_AUTHORITY
        or type(stage) is not int
        or stage not in STAGE_LABELS
        or status.get("stage_label") != STAGE_LABELS[cast(int, stage)]
        or state
        not in {
            "completed",
            "failed",
            "queued",
            "running",
            "stopped",
            "verified",
            "waiting-retry",
        }
        or status.get("job_action") not in {"start", "resume", "retry", "verify"}
        or type(status.get("job_ordinal")) is not int
        or cast(int, status["job_ordinal"]) < 1
        or type(status.get("sequence")) is not int
        or cast(int, status["sequence"]) < 0
        or type(status.get("job_started_unix_ns")) is not int
        or type(status.get("updated_unix_ns")) is not int
        or type(status.get("activity")) is not str
        or type(status.get("workflow_id")) is not str
        or (status.get("error") is not None and type(status.get("error")) is not str)
        or (pid is not None and (type(pid) is not int or pid <= 0))
        or (effect_pid is not None and (type(effect_pid) is not int or effect_pid <= 0))
        or (pid is None and status.get("worker_start_token") is not None)
        or (pid is not None and type(status.get("worker_start_token")) is not str)
    ):
        raise AgentvolveWorkerError("Agentvolve worker status has an unexpected schema")
    return status


def worker_is_alive(workflow_root: Path) -> bool:
    status = load_worker_status(workflow_root)
    return status is not None and _worker_alive(workflow_root, status)


def _open_registry_lock(runs_directory: Path) -> IO[bytes]:
    lock_path = runs_directory / ".agentvolve.lock"
    reject_symlink(lock_path, "Agentvolve registry lock", AgentvolveWorkerError)
    stream = lock_path.open("a+b")
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        stream.close()
        raise AgentvolveWorkerError(
            "another Agentvolve workflow launch is in progress"
        ) from exc
    return stream


def _open_lock(workflow_root: Path) -> IO[bytes]:
    lock_path = workflow_root / "worker.lock"
    reject_symlink(lock_path, "Agentvolve worker lock", AgentvolveWorkerError)
    stream = lock_path.open("a+b")
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        stream.close()
        raise AgentvolveWorkerError(
            "Agentvolve workflow already has a live worker"
        ) from exc
    return stream


def _status_document(
    workflow_root: Path,
    request: dict[str, object],
    job: dict[str, object],
    *,
    state: str,
    stage: int,
    activity: str,
    error: str | None = None,
    effect_pid: int | None = None,
    worker_pid: int | None = None,
) -> dict[str, object]:
    try:
        previous = load_worker_status(workflow_root)
    except AgentvolveWorkerError:
        reject_symlink(
            _status_path(workflow_root),
            "Agentvolve worker status",
            AgentvolveWorkerError,
        )
        previous = None
    sequence = 0 if previous is None else int(previous.get("sequence", -1)) + 1
    started = (
        time.time_ns()
        if previous is None or previous.get("job_ordinal") != job["ordinal"]
        else previous.get("job_started_unix_ns", time.time_ns())
    )
    pid = os.getpid() if worker_pid is None else worker_pid
    token = _process_start_token(pid) if pid > 0 else None
    return {
        "activity": activity,
        "authority": STATUS_AUTHORITY,
        "effect_pid": effect_pid,
        "error": error,
        "job_action": job["action"],
        "job_ordinal": job["ordinal"],
        "job_started_unix_ns": started,
        "sequence": sequence,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "state": state,
        "status_schema": WORKFLOW_STATUS_SCHEMA,
        "updated_unix_ns": time.time_ns(),
        "worker_pid": pid if pid > 0 else None,
        "worker_start_token": token,
        "workflow_id": request["workflow_id"],
    }


def _write_status(
    workflow_root: Path,
    request: dict[str, object],
    job: dict[str, object],
    *,
    state: str,
    stage: int,
    activity: str,
    error: str | None = None,
    effect_pid: int | None = None,
    worker_pid: int | None = None,
) -> dict[str, object]:
    document = _status_document(
        workflow_root,
        request,
        job,
        state=state,
        stage=stage,
        activity=activity,
        error=error,
        effect_pid=effect_pid,
        worker_pid=worker_pid,
    )
    _write_canonical(_status_path(workflow_root), document)
    return document


def _next_job(
    workflow_root: Path, workflow_id: str, action: str, reason: str | None
) -> Path:
    jobs = workflow_root / "jobs"
    reject_symlink(jobs, "Agentvolve worker jobs", AgentvolveWorkerError)
    jobs.mkdir(exist_ok=True)
    ordinals: list[int] = []
    for path in jobs.glob("*.json"):
        if path.is_file() and not path.is_symlink() and path.stem.isdigit():
            ordinals.append(int(path.stem))
    ordinal = max(ordinals, default=0) + 1
    job = {
        "action": action,
        "job_schema": WORKFLOW_JOB_SCHEMA,
        "ordinal": ordinal,
        "reason": reason,
        "workflow_id": workflow_id,
    }
    path = jobs / f"{ordinal:06d}.json"
    _write_canonical(path, job)
    return path


def _spawn_worker(
    workflow_root: Path,
    job_path: Path,
    inherited_lock: IO[bytes] | None = None,
) -> dict[str, object]:
    lock = inherited_lock if inherited_lock is not None else _open_lock(workflow_root)
    try:
        request = load_workflow_request(workflow_root)
        job = _load_job(job_path)
        if job["workflow_id"] != request["workflow_id"]:
            raise AgentvolveWorkerError(
                "Agentvolve worker job targets another workflow"
            )
        environment = dict(os.environ) if job["action"] == "verify" else _execution_environment(workflow_root, request, probe=True)
        _write_status(
            workflow_root,
            request,
            job,
            state="queued",
            stage=int((load_worker_status(workflow_root) or {}).get("stage", 1)),
            activity="detached worker is starting",
            worker_pid=0,
        )
        log_path = workflow_root / f"worker-{int(job['ordinal']):06d}.log"
        descriptor = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "apps.coding_agent.agentvolve_worker",
                    "_work",
                    str(workflow_root),
                    str(job_path),
                    str(lock.fileno()),
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=descriptor,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                pass_fds=(lock.fileno(),),
                env=environment,
            )
        finally:
            os.close(descriptor)
    except Exception:
        lock.close()
        raise
    lock.close()
    return {
        "action": job["action"],
        "pid": process.pid,
        "state": "queued",
        "worker_response_schema": "agentvolve-worker-response-v1",
        "workflow_id": request["workflow_id"],
        "workflow_root": str(workflow_root),
    }


def _referenced_run_roots(runs_directory: Path) -> set[Path]:
    roots: set[Path] = set()
    for workflow in runs_directory.iterdir():
        if (
            not workflow.is_dir()
            or workflow.is_symlink()
            or not WORKFLOW_NAME.fullmatch(workflow.name)
        ):
            continue
        try:
            request = load_workflow_request(workflow)
        except AgentvolveWorkerError:
            continue
        for key in ("harness_run_root", "solution_run_root"):
            value = request.get(key)
            if type(value) is str:
                roots.add(Path(value).absolute())
    return roots


def _operator_reason(reason: object) -> str:
    if type(reason) is not str or not reason.strip() or "\x00" in reason or len(reason) > 2_000:
        raise AgentvolveWorkerError("operator reason must be non-empty text of at most 2000 characters without NUL")
    return reason


def load_workflow_closure(workflow_root: Path) -> dict[str, object] | None:
    """Read an explicit orchestration closure, never an experimental success seal."""
    path = workflow_root / "closed.json"
    reject_symlink(path, "Agentvolve workflow closure", AgentvolveWorkerError)
    if not path.exists():
        return None
    document = _canonical_document(path, "Agentvolve workflow closure")
    if (
        set(document) != {"closure_schema", "authority", "workflow_id", "closed_unix_ns", "reason"}
        or document.get("closure_schema") != "agentvolve-workflow-closure-v1"
        or document.get("authority") != WORKFLOW_AUTHORITY
        or document.get("workflow_id") != load_workflow_request(workflow_root)["workflow_id"]
        or type(document.get("closed_unix_ns")) is not int
        or cast(int, document["closed_unix_ns"]) <= 0
    ):
        raise AgentvolveWorkerError("Agentvolve workflow closure is malformed or targets another workflow")
    _operator_reason(document.get("reason"))
    return document


def _lock_is_held(workflow_root: Path) -> bool:
    """Probe an existing lock without creating or trusting a status projection."""
    path = workflow_root / "worker.lock"
    reject_symlink(path, "Agentvolve worker lock", AgentvolveWorkerError)
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        return False
    with stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def workflow_control_state(workflow_root: Path) -> dict[str, object]:
    """Read-only menu hints. Effectful operations must check authority again."""
    workflow_root = workflow_root.expanduser().absolute()
    reject_symlink(workflow_root, "Agentvolve workflow", AgentvolveWorkerError)
    request = load_workflow_request(workflow_root)
    harness = _request_path_value(request, "harness_run_root", optional=True)
    solution = cast(Path, _request_path_value(request, "solution_run_root"))
    complete = _completed_run(solution, "solution")
    active_root = solution if solution.is_dir() and not complete else harness
    _pending, retry_required = _pending_state(active_root) if active_root is not None and not complete else (None, False)
    return {
        "control_schema": "agentvolve-workflow-control-v1",
        "authority": STATUS_AUTHORITY,
        "workflow_root": str(workflow_root),
        "workflow_id": request["workflow_id"],
        "runtime_manifest": request["runtime_manifest"],
        "active": _lock_is_held(workflow_root),
        "complete": complete,
        "closed": load_workflow_closure(workflow_root) is not None,
        "retry_required": retry_required,
    }


def registry_status(runs_directory: Path) -> dict[str, object]:
    """Inspect startup blockers without inference, writes, or legacy recovery."""
    runs_directory = runs_directory.expanduser().absolute()
    reject_symlink(runs_directory, "Agentvolve runs directory", AgentvolveWorkerError)
    blocker = None
    legacy_count = 0
    if runs_directory.exists():
        _validate_runs_directory(runs_directory, create=False)
        referenced = _referenced_run_roots(runs_directory)
        for run in sorted(runs_directory.iterdir()):
            if not run.is_dir() or run.is_symlink():
                continue
            if WORKFLOW_NAME.fullmatch(run.name):
                control = workflow_control_state(run)
                if control["active"] or not (control["complete"] or control["closed"]):
                    # A live lock takes precedence over an older inactive blocker.
                    if blocker is None or control["active"]:
                        blocker = control
            elif RUN_NAME.fullmatch(run.name) and run.absolute() not in referenced and not (run / "experiment-report.json").is_file():
                legacy_count += 1
    return {
        "registry_schema": "agentvolve-registry-status-v1",
        "authority": STATUS_AUTHORITY,
        "blocker": blocker,
        "legacy_unfinished_count": legacy_count,
    }


def _refuse_conflicting_work(runs_directory: Path) -> int:
    view = registry_status(runs_directory)
    blocker = view["blocker"]
    if type(blocker) is dict:
        if blocker["active"]:
            raise AgentvolveWorkerError(f"another Agentvolve worker is active: {blocker['workflow_root']}")
        raise AgentvolveWorkerError(
            "unfinished Agentvolve workflow requires resume, explicit retry, or close as incomplete: "
            f"{blocker['workflow_root']}. Ask Agentvolve to manage the workflow in this session."
        )
    return cast(int, view["legacy_unfinished_count"])


def close_workflow(workflow_root: Path, reason: str) -> dict[str, object]:
    """Permanently close inactive orchestration while leaving all run evidence intact."""
    reason = _operator_reason(reason)
    workflow_root = workflow_root.expanduser().absolute()
    reject_symlink(workflow_root, "Agentvolve workflow", AgentvolveWorkerError)
    request = load_workflow_request(workflow_root)
    lock = _open_lock(workflow_root)
    try:
        if load_workflow_closure(workflow_root) is not None:
            raise AgentvolveWorkerError("Agentvolve workflow is already closed")
        solution = cast(Path, _request_path_value(request, "solution_run_root"))
        if _completed_run(solution, "solution"):
            raise AgentvolveWorkerError("completed Agentvolve workflow cannot be closed as incomplete")
        _write_canonical(workflow_root / "closed.json", {
            "closure_schema": "agentvolve-workflow-closure-v1",
            "authority": WORKFLOW_AUTHORITY,
            "workflow_id": request["workflow_id"],
            "closed_unix_ns": time.time_ns(),
            "reason": reason,
        })
    finally:
        lock.close()
    return {
        "action": "close", "state": "closed-incomplete", "pid": 0,
        "worker_response_schema": "agentvolve-worker-response-v1",
        "workflow_id": request["workflow_id"], "workflow_root": str(workflow_root),
    }


def start_workflow(
    runs_directory: Path,
    task_profile: Path,
    runtime_manifest: Path,
    harness_descriptor: Path | None = None,
    *,
    execution: dict | None = None,
) -> dict[str, object]:
    # Only the new configured boundary binds a v2 request. Legacy calls stay v1.
    if execution is not None and (type(execution) is not dict or harness_descriptor is None
                                  or type(execution.get("worker_configuration")) is not str):
        raise AgentvolveWorkerError("Configured Pi start requires an explicit sealed harness and reviewed configuration")
    runs_directory = runs_directory.expanduser().absolute()
    task_profile = task_profile.expanduser().absolute()
    runtime_manifest = runtime_manifest.expanduser().absolute()
    harness_descriptor = (
        None
        if harness_descriptor is None
        else harness_descriptor.expanduser().absolute()
    )
    if execution is not None:
        # Fail before workflow/evidence creation when the selected filesystem
        # cannot enforce private job-owned model/auth snapshots.
        runs_directory = pi_execution.private_runs_directory(runs_directory, create=True)
    _validate_runs_directory(runs_directory, create=True)
    _regular_file(task_profile, "Agentvolve task profile")
    _regular_file(runtime_manifest, "Agentvolve runtime manifest")
    _runtime_model(runtime_manifest)
    if harness_descriptor is not None:
        _regular_file(harness_descriptor, "selected harness descriptor")
    _preflight_workflow(task_profile, runtime_manifest, harness_descriptor)
    registry_lock = _open_registry_lock(runs_directory)
    try:
        legacy_count = _refuse_conflicting_work(runs_directory)
        workflow_root = _new_path(runs_directory, "workflow")
        harness_root = (
            None
            if harness_descriptor is not None
            else _new_path(runs_directory, "harness")
        )
        solution_root = _new_path(runs_directory, "solution")
        workflow_root.mkdir(mode=0o700)
        identity: dict[str, object] = {
            "agent": "pi",
            "authority": WORKFLOW_AUTHORITY,
            "created_unix_ns": time.time_ns(),
            "harness_descriptor": None
            if harness_descriptor is None
            else str(harness_descriptor),
            "harness_run_root": None if harness_root is None else str(harness_root),
            "repository_root": str(ROOT),
            "runtime_manifest": str(runtime_manifest),
            "solution_run_root": str(solution_root),
            "task_profile": str(task_profile),
            "workflow_schema": WORKFLOW_REQUEST_SCHEMA,
        }
        if execution is not None:
            workflow_root.chmod(0o700)
            identity["workflow_schema"] = pi_execution.WORKFLOW_SCHEMA
            identity["pi_execution"] = pi_execution.execution_record(workflow_root, execution)
        request = {**identity, "workflow_id": canonical_digest(identity)}
        _write_canonical(_request_path(workflow_root), request)
        if execution is not None:
            pi_execution.snapshot_configuration(workflow_root, request["pi_execution"])
        job = _next_job(workflow_root, str(request["workflow_id"]), "start", None)
        return {**_spawn_worker(workflow_root, job), "legacy_unfinished_count": legacy_count}
    finally:
        registry_lock.close()


def launch_existing(
    workflow_root: Path, action: str, reason: str | None = None
) -> dict[str, object]:
    workflow_root = workflow_root.expanduser().absolute()
    if workflow_root.is_symlink() or not workflow_root.is_dir():
        raise AgentvolveWorkerError(
            f"Agentvolve workflow is absent or unsafe: {workflow_root}"
        )
    if action not in {"resume", "retry", "verify"}:
        raise AgentvolveWorkerError("Agentvolve continuation action is unsupported")
    lock = _open_lock(workflow_root)
    try:
        request = load_workflow_request(workflow_root)
        if load_workflow_closure(workflow_root) is not None:
            raise AgentvolveWorkerError("Agentvolve workflow was closed as incomplete; create a separately reviewed task")
        if action == "retry" and (
            reason is None or not reason.strip() or "\x00" in reason
        ):
            raise AgentvolveWorkerError("Agentvolve retry requires an operator reason")
        if action != "retry" and reason is not None:
            raise AgentvolveWorkerError("only Agentvolve retry accepts a reason")

        harness_root = _request_path_value(request, "harness_run_root", optional=True)
        solution_root = cast(Path, _request_path_value(request, "solution_run_root"))
        solution_complete = _completed_run(solution_root, "solution")
        active_root: Path | None = None
        if solution_root.is_dir() and not solution_complete:
            active_root = solution_root
        elif (
            harness_root is not None
            and harness_root.is_dir()
            and not _completed_run(harness_root, "harness")
        ):
            active_root = harness_root
        _pending, retry_required = (
            _pending_state(active_root) if active_root is not None else (None, False)
        )
        if action == "retry" and not retry_required:
            raise AgentvolveWorkerError(
                "Agentvolve retry is allowed only for an authoritative pending indeterminate attempt"
            )
        if action == "resume" and retry_required:
            raise AgentvolveWorkerError(
                "Agentvolve workflow requires explicit retry authorization, not resume"
            )
        if action == "resume" and solution_complete:
            raise AgentvolveWorkerError(
                "completed Agentvolve workflow has no effects to resume"
            )
        if action == "verify" and not solution_complete:
            raise AgentvolveWorkerError(
                "Agentvolve workflow must complete before offline verification"
            )
        if action != "verify":
            _execution_environment(workflow_root, request)
        job = _next_job(workflow_root, str(request["workflow_id"]), action, reason)
    except Exception:
        lock.close()
        raise
    return _spawn_worker(workflow_root, job, lock)


def _safe_tail(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - MAX_DIAGNOSTIC_BYTES))
            payload = stream.read(MAX_DIAGNOSTIC_BYTES)
    except OSError:
        return ""
    text = payload.decode("utf-8", errors="replace")
    return "".join(
        character if character in "\n\t" or character.isprintable() else "?"
        for character in text
    ).strip()


def _pending_state(run_root: Path) -> tuple[str | None, bool]:
    path = run_root / "state" / "pending" / "round-intent.json"
    if not path.is_file() or path.is_symlink():
        return None, False
    try:
        document = _canonical_document(path, "pending round intent")
    except AgentvolveWorkerError:
        return "unreadable pending intent", False
    stage = document.get("stage")
    retry_required = (
        stage == "controller_pending" and document.get("controller_receipt") is None
    )
    return str(stage) if type(stage) is str else "pending effect", retry_required


def _activity(run_root: Path, kind: str, stage: int) -> str:
    pending, _ = _pending_state(run_root)
    if pending == "controller_pending":
        return (
            f"{kind} Controller round is awaiting an immutable model/evaluation receipt"
        )
    if pending == "controller_complete":
        return f"{kind} Controller receipt is complete; trusted evidence adaptation is running"
    if pending == "evidence_complete":
        return f"{kind} evidence is complete; Population records are being committed"
    if stage == 5:
        return "protected final checks are running after development allocation"
    return f"{kind} evolution command is running"


class _EffectRunner:
    def __init__(
        self,
        workflow_root: Path,
        request: dict[str, object],
        job: dict[str, object],
    ) -> None:
        self.workflow_root = workflow_root
        self.request = request
        self.job = job
        self.process: subprocess.Popen[bytes] | None = None
        self.terminated = False

    def terminate(self, _signum: int, _frame: object) -> None:
        self.terminated = True
        if self.process is None or self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    def run(
        self, command: list[str], *, run_root: Path, kind: str, fallback_stage: int
    ) -> None:
        if self.terminated:
            raise AgentvolveWorkerError("Agentvolve worker was stopped by the operator")
        environment = dict(os.environ) if self.job["action"] == "verify" else _execution_environment(self.workflow_root, self.request, probe=True)
        ordinal = int(self.job["ordinal"])
        prefix = f"{ordinal:06d}-{kind}"
        stdout_path = self.workflow_root / f"{prefix}.stdout"
        stderr_path = self.workflow_root / f"{prefix}.stderr"
        stdout_fd = os.open(stdout_path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        stderr_fd = os.open(stderr_path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        try:
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=stdout_fd,
                stderr=stderr_fd,
                env=environment,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            os.close(stdout_fd)
            os.close(stderr_fd)
        last_stage = fallback_stage
        while self.process.poll() is None:
            if run_root.is_dir():
                try:
                    projection = load_process_status(run_root, expected_run_kind=kind)
                except Exception:
                    projection = None
                if projection is not None:
                    last_stage = int(projection["stage"])
            _write_status(
                self.workflow_root,
                self.request,
                self.job,
                state="running",
                stage=last_stage,
                activity=_activity(run_root, kind, last_stage),
                effect_pid=self.process.pid,
            )
            time.sleep(HEARTBEAT_SECONDS)
        return_code = self.process.returncode
        self.process = None
        if self.terminated:
            raise AgentvolveWorkerError("Agentvolve worker was stopped by the operator")
        if return_code != 0:
            # Configured provider diagnostics may contain private auth. Keep them
            # in private logs rather than copying them into status/session outputs.
            diagnostic = "" if "pi_execution" in self.request else (_safe_tail(stderr_path) or _safe_tail(stdout_path))
            raise AgentvolveWorkerError(
                diagnostic or f"{kind} evolution exited with status {return_code}"
            )
        if not _completed_run(run_root, kind):
            raise AgentvolveWorkerError(
                f"{kind} evolution did not produce a completed run"
            )


def _request_path_value(
    request: dict[str, object], key: str, *, optional: bool = False
) -> Path | None:
    value = request.get(key)
    if optional and value is None:
        return None
    if type(value) is not str:
        raise AgentvolveWorkerError(f"Agentvolve workflow {key} is malformed")
    return _absolute_path(value, f"Agentvolve workflow {key}")


def _run_command(
    kind: str, operation: str, root: Path, reason: str | None = None
) -> list[str]:
    module = (
        "apps.harness.experiment"
        if kind == "harness"
        else "apps.coding_agent.solution_experiment"
    )
    return [
        sys.executable,
        "-m",
        module,
        operation,
        str(root),
        *([] if reason is None else [reason]),
    ]


def _fresh_harness_command(root: Path, runtime: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "apps.harness.experiment",
        "coding-pi",
        str(root),
        str(runtime),
    ]


def _fresh_solution_command(
    root: Path, task: Path, runtime: Path, harness: Path
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "apps.coding_agent.solution_experiment",
        "pi",
        str(task),
        str(root),
        str(runtime),
        str(harness),
    ]


def _write_completion_report(workflow_root: Path, request: dict[str, object]) -> None:
    solution_root = cast(Path, _request_path_value(request, "solution_run_root"))
    report = _canonical_document(
        solution_root / "experiment-report.json", "solution experiment report"
    )
    final = report.get("final") if type(report.get("final")) is dict else {}
    selected = (
        report.get("selected_solution")
        if type(report.get("selected_solution")) is dict
        else {}
    )
    artifact = (
        selected.get("artifact") if type(selected.get("artifact")) is dict else {}
    )
    document = {
        "authority": STATUS_AUTHORITY,
        "candidate_id": selected.get("candidate_id"),
        "completed_rounds": (
            report.get("development", {}).get("completed_rounds")
            if type(report.get("development")) is dict
            else None
        ),
        "final_passed": final.get("passed_count"),
        "final_tasks": final.get("task_count"),
        "patch_path": str(solution_root / "selected.patch"),
        "report_schema": "agentvolve-workflow-report-v1",
        "selected_commit": artifact.get("commit"),
        "solution_run_root": str(solution_root),
        "workflow_id": request["workflow_id"],
    }
    _write_canonical(workflow_root / "workflow-report.json", document)


def _execute_job(workflow_root: Path, job_path: Path) -> None:
    request = load_workflow_request(workflow_root)
    if load_workflow_closure(workflow_root) is not None:
        raise AgentvolveWorkerError("Agentvolve workflow was closed as incomplete")
    job = _load_job(job_path)
    if request["workflow_id"] != job["workflow_id"]:
        raise AgentvolveWorkerError(
            "Agentvolve worker job identity does not match its workflow"
        )
    task = cast(Path, _request_path_value(request, "task_profile"))
    runtime = cast(Path, _request_path_value(request, "runtime_manifest"))
    harness_root = _request_path_value(request, "harness_run_root", optional=True)
    solution_root = cast(Path, _request_path_value(request, "solution_run_root"))
    configured_harness = _request_path_value(
        request, "harness_descriptor", optional=True
    )
    _regular_file(task, "Agentvolve task profile")
    _regular_file(runtime, "Agentvolve runtime manifest")
    _runtime_model(runtime)
    runner = _EffectRunner(workflow_root, request, job)
    previous_term = signal.signal(signal.SIGTERM, runner.terminate)
    previous_int = signal.signal(signal.SIGINT, runner.terminate)
    try:
        action = str(job["action"])
        # Offline evidence replay never needs the model client or private credentials.
        if action != "verify":
            _execution_environment(workflow_root, request)
        reason = cast(str | None, job["reason"])
        current_stage = int((load_worker_status(workflow_root) or {}).get("stage", 1))
        _write_status(
            workflow_root,
            request,
            job,
            state="running",
            stage=current_stage,
            activity="detached worker accepted the operator job",
        )
        if action == "verify":
            if not _completed_run(solution_root, "solution"):
                raise AgentvolveWorkerError(
                    "Agentvolve workflow has no completed solution to verify"
                )
            runner.run(
                _run_command("solution", "verify", solution_root),
                run_root=solution_root,
                kind="solution",
                fallback_stage=6,
            )
            _write_status(
                workflow_root,
                request,
                job,
                state="verified",
                stage=6,
                activity="offline replay verified the selected result",
            )
            return

        harness = configured_harness
        if harness is None:
            if harness_root is None:
                raise AgentvolveWorkerError(
                    "Agentvolve workflow omitted its harness run root"
                )
            if not _completed_run(harness_root, "harness"):
                if harness_root.exists():
                    operation = "retry" if action == "retry" else "resume"
                    runner.run(
                        _run_command(
                            "harness",
                            operation,
                            harness_root,
                            reason if operation == "retry" else None,
                        ),
                        run_root=harness_root,
                        kind="harness",
                        fallback_stage=2,
                    )
                    action = "resume"
                    reason = None
                else:
                    runner.run(
                        _fresh_harness_command(harness_root, runtime),
                        run_root=harness_root,
                        kind="harness",
                        fallback_stage=1,
                    )
            harness = harness_root / "selected-harness.json"
        _regular_file(harness, "selected harness descriptor")
        _write_status(
            workflow_root,
            request,
            job,
            state="running",
            stage=3,
            activity="sealed harness is fixed for solution evolution",
        )

        if not _completed_run(solution_root, "solution"):
            if solution_root.exists():
                operation = "retry" if action == "retry" else "resume"
                runner.run(
                    _run_command(
                        "solution",
                        operation,
                        solution_root,
                        reason if operation == "retry" else None,
                    ),
                    run_root=solution_root,
                    kind="solution",
                    fallback_stage=4,
                )
            else:
                if action == "retry":
                    raise AgentvolveWorkerError(
                        "no pending Agentvolve run exists to retry"
                    )
                runner.run(
                    _fresh_solution_command(solution_root, task, runtime, harness),
                    run_root=solution_root,
                    kind="solution",
                    fallback_stage=4,
                )
        _write_completion_report(workflow_root, request)
        _write_status(
            workflow_root,
            request,
            job,
            state="completed",
            stage=6,
            activity="selected commit and patch are ready for operator review",
        )
    except Exception as exc:
        active_root = solution_root if solution_root.exists() else harness_root
        pending, retry_required = (
            _pending_state(active_root) if active_root is not None else (None, False)
        )
        state = (
            "waiting-retry"
            if retry_required
            else "stopped"
            if runner.terminated
            else "failed"
        )
        stage = (
            4
            if solution_root.exists()
            else 2
            if harness_root is not None and harness_root.exists()
            else 1
        )
        if active_root is not None and active_root.is_dir():
            kind = "solution" if active_root == solution_root else "harness"
            try:
                projection = load_process_status(active_root, expected_run_kind=kind)
            except Exception:
                projection = None
            if projection is not None:
                stage = int(projection["stage"])
        detail = str(exc) or type(exc).__name__
        if pending:
            detail = f"{detail} (pending state: {pending})"
        _write_status(
            workflow_root,
            request,
            job,
            state=state,
            stage=stage,
            activity=(
                "operator retry authorization is required"
                if retry_required
                else "worker stopped; inspect the bounded worker logs"
            ),
            error=detail[-MAX_DIAGNOSTIC_BYTES:],
        )
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)


def _same_process(pid: int | None, token: str | None) -> bool:
    if type(pid) is not int or pid <= 0 or type(token) is not str:
        return False
    try:
        return _process_start_token(pid) == token and os.getpgid(pid) == pid
    except ProcessLookupError:
        return False


def _direct_child_start_token(pid: int | None, parent_pid: int) -> str | None:
    """Identify a current process-group leader still owned by the worker."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        status = (Path("/proc") / str(pid) / "status").read_text(encoding="ascii")
        parent = next(
            (int(line.split()[1]) for line in status.splitlines() if line.startswith("PPid:")),
            None,
        )
        if parent != parent_pid or os.getpgid(pid) != pid:
            return None
    except (OSError, UnicodeError, ValueError):
        return None
    return _process_start_token(pid)


def _signal_process_group(pid: int | None, token: str | None, sig: signal.Signals) -> None:
    if not _same_process(pid, token):
        return
    try:
        os.killpg(cast(int, pid), sig)
    except ProcessLookupError:
        pass


def _terminate_process_groups(
    worker_pid: int,
    worker_token: str,
    effect_pid: int | None,
    effect_token: str | None,
    *,
    grace_seconds: float = STOP_GRACE_SECONDS,
) -> bool:
    """Terminate one identity-checked detached worker tree, escalating if stuck."""
    # The effect owns a separate process group. Signal it directly as well as the
    # worker so stop does not depend on Python's signal handler making progress.
    _signal_process_group(effect_pid, effect_token, signal.SIGTERM)
    _signal_process_group(worker_pid, worker_token, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not _same_process(worker_pid, worker_token) and not _same_process(effect_pid, effect_token):
            return False
        time.sleep(STOP_POLL_SECONDS)
    forced = _same_process(worker_pid, worker_token) or _same_process(effect_pid, effect_token)
    _signal_process_group(effect_pid, effect_token, signal.SIGKILL)
    _signal_process_group(worker_pid, worker_token, signal.SIGKILL)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if not _same_process(worker_pid, worker_token) and not _same_process(effect_pid, effect_token):
            return forced
        time.sleep(STOP_POLL_SECONDS)
    if _same_process(worker_pid, worker_token) or _same_process(effect_pid, effect_token):
        raise AgentvolveWorkerError("Agentvolve process tree did not terminate")
    return forced


def stop_workflow(workflow_root: Path) -> dict[str, object]:
    workflow_root = workflow_root.expanduser().absolute()
    reject_symlink(workflow_root, "Agentvolve workflow", AgentvolveWorkerError)
    request = load_workflow_request(workflow_root)
    status = load_worker_status(workflow_root)
    if status is None or not _worker_alive(workflow_root, status):
        raise AgentvolveWorkerError("Agentvolve workflow has no live worker to stop")
    pid = cast(int, status["worker_pid"])
    worker_token = cast(str, status["worker_start_token"])
    effect_pid = cast(int | None, status["effect_pid"])
    effect_token = _direct_child_start_token(effect_pid, pid)
    forced = _terminate_process_groups(pid, worker_token, effect_pid, effect_token)
    lock = _open_lock(workflow_root)
    try:
        latest = load_worker_status(workflow_root) or status
        if latest["state"] not in {"stopped", "completed", "verified"}:
            ordinal = cast(int, latest["job_ordinal"])
            job = _load_job(workflow_root / "jobs" / f"{ordinal:06d}.json")
            latest = _write_status(
                workflow_root,
                request,
                job,
                state="stopped",
                stage=cast(int, latest["stage"]),
                activity="Agentvolve process tree was stopped",
                error="forced termination after grace period" if forced else "stopped on request",
                worker_pid=0,
            )
        final_state = cast(str, latest["state"])
    finally:
        lock.close()
    return {
        "action": "stop",
        "pid": pid,
        "state": final_state,
        "worker_response_schema": "agentvolve-worker-response-v1",
        "workflow_id": request["workflow_id"],
        "workflow_root": str(workflow_root),
    }


def _work_main(arguments: list[str]) -> int:
    if len(arguments) != 3:
        return 2
    workflow_root = _absolute_path(arguments[0], "Agentvolve workflow root")
    job_path = _absolute_path(arguments[1], "Agentvolve worker job")
    lock_fd: int | None = None
    try:
        lock_fd = int(arguments[2])
        lock_stat = os.fstat(lock_fd)
        expected_lock = workflow_root / "worker.lock"
        reject_symlink(expected_lock, "Agentvolve worker lock", AgentvolveWorkerError)
        expected_stat = expected_lock.stat()
        if (lock_stat.st_dev, lock_stat.st_ino) != (
            expected_stat.st_dev,
            expected_stat.st_ino,
        ):
            raise AgentvolveWorkerError(
                "detached worker did not inherit its workflow lock"
            )
        if job_path.parent != workflow_root / "jobs" or not re.fullmatch(
            r"\d{6}\.json", job_path.name
        ):
            raise AgentvolveWorkerError("detached worker job path escapes its workflow")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _execute_job(workflow_root, job_path)
    except Exception as exc:
        print(str(exc) or type(exc).__name__, flush=True)
        return 2
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "_work":
        return _work_main(arguments[1:])
    try:
        if len(arguments) == 2 and arguments[0] == "registry":
            result = registry_status(_absolute_path(arguments[1], "Agentvolve runs directory"))
        elif len(arguments) == 2 and arguments[0] == "control":
            result = workflow_control_state(_absolute_path(arguments[1], "Agentvolve workflow root"))
        elif len(arguments) == 3 and arguments[0] == "close":
            result = close_workflow(_absolute_path(arguments[1], "Agentvolve workflow root"), arguments[2])
        elif len(arguments) in {4, 5} and arguments[0] == "start":
            harness = (
                None
                if len(arguments) == 4
                else _absolute_path(arguments[4], "selected harness descriptor")
            )
            result = start_workflow(
                _absolute_path(arguments[1], "Agentvolve runs directory"),
                _absolute_path(arguments[2], "Agentvolve task profile"),
                _absolute_path(arguments[3], "Agentvolve runtime manifest"),
                harness,
            )
        elif len(arguments) == 2 and arguments[0] in {"resume", "verify"}:
            result = launch_existing(
                _absolute_path(arguments[1], "Agentvolve workflow root"), arguments[0]
            )
        elif len(arguments) == 3 and arguments[0] == "retry":
            result = launch_existing(
                _absolute_path(arguments[1], "Agentvolve workflow root"),
                "retry",
                arguments[2],
            )
        elif len(arguments) == 2 and arguments[0] == "stop":
            result = stop_workflow(
                _absolute_path(arguments[1], "Agentvolve workflow root")
            )
        else:
            raise AgentvolveWorkerError(
                "usage: agentvolve_worker.py start RUNS TASK.json RUNTIME.json "
                "[SELECTED-HARNESS.json] | resume WORKFLOW | retry WORKFLOW REASON | "
                "verify WORKFLOW | stop WORKFLOW | close WORKFLOW REASON | "
                "registry RUNS | control WORKFLOW"
            )
    except (AgentvolveWorkerError, OSError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    write_document(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
