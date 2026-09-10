"""Job-owned Pi configuration, not experiment identity or an environment protocol."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path

from apps._support.bounded_process import OutputLimitError, communicate_bounded
from apps._support.durable import atomic_write
from apps._support.wire import canonical_json
from apps.harness.runtime_manifest import load_runtime_manifest

WORKFLOW_SCHEMA = "agentvolve-worker-request-v2"
EXECUTION_SCHEMA = "agentvolve-pi-execution-v1"
MAX_CONFIGURATION_BYTES = 2_097_152
MAX_REVIEW_BYTES = 262_144
SNAPSHOT_NAME = "pi-configuration"
REQUIRED_FLAGS = frozenset({
    "--provider", "--model", "--thinking", "--no-session", "--no-skills",
    "--no-extensions", "--no-prompt-templates", "--no-themes", "--no-context-files",
    "--no-tools", "--mode", "--system-prompt", "--print",
})


class PiConfigurationError(ValueError):
    """A reviewed execution context is unavailable or has changed."""


def probe_command(command: list[str], option: str, *, environment: dict[str, str] | None = None) -> str:
    """Bounded no-inference CLI check, shared by review and job-owned execution."""
    try:
        with subprocess.Popen([*command, option], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              start_new_session=True, env=environment) as process:
            stdout, stderr = communicate_bounded(process, None, timeout_seconds=10, max_output_bytes=131072)
            if process.returncode or stderr:
                raise PiConfigurationError(f"Pi {option} failed; no experiment was started")
            return stdout.strip()
    except (OSError, UnicodeError, subprocess.TimeoutExpired, OutputLimitError) as exc:
        raise PiConfigurationError(f"Pi {option} probe failed: {type(exc).__name__}") from exc


def validate_bound_command(command: list[str], expected: str, environment: dict[str, str]) -> None:
    if probe_command(command, "--version", environment=environment) != expected:
        raise PiConfigurationError("Job-owned Pi command version changed; execution refused")
    flags = set(re.findall(r"--[a-z][a-z-]*", probe_command(command, "--help", environment=environment)))
    if REQUIRED_FLAGS - flags:
        raise PiConfigurationError("Job-owned Pi command lost required isolation/transport flags")


def resolved_path(value: object) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        raise PiConfigurationError("Pi configuration path must be absolute and without symlinks")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise PiConfigurationError("Pi configuration path must be absolute and without symlinks")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise PiConfigurationError("Pi configuration paths must not contain symlinks")
    return path.resolve()


def bounded_file(path: Path, *, limit: int = MAX_CONFIGURATION_BYTES,
                 optional: bool = False, private: bool = False) -> bytes | None:
    """Read only bounded regular bytes; diagnostics never contain file contents."""
    resolved_path(str(path))
    directory_fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # Anchor every directory component, not just the leaf, against link swaps.
        for part in path.parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except FileNotFoundError:
        if optional:
            return None
        raise PiConfigurationError("Required Pi configuration/review file is unavailable") from None
    except OSError:
        raise PiConfigurationError("Cannot safely read Pi configuration/review file") from None
    finally:
        os.close(directory_fd)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit
                or (private and stat.S_IMODE(info.st_mode) != 0o600)):
            raise PiConfigurationError("Pi configuration/review requires bounded regular private files (no links)")
        payload = stream.read(limit + 1)
        if len(payload) > limit:
            raise PiConfigurationError("Pi configuration/review file exceeds its byte bound")
    return payload


def configuration_source(path: Path) -> Path:
    source = resolved_path(str(path))
    interactive = Path(os.environ.get("PI_CODING_AGENT_DIR", str(Path.home() / ".pi/agent"))).expanduser().resolve()
    if not source.is_dir() or source == interactive or (
        interactive.is_dir() and source.samefile(interactive)
    ):
        raise PiConfigurationError("Choose a separate reviewed worker configuration directory, not interactive Pi configuration")
    return source


def private_runs_directory(path: Path, *, create: bool = False) -> Path:
    """Require a caller-selected registry that can protect per-job credentials."""
    directory = resolved_path(str(path.expanduser().absolute()))
    if create:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    try:
        info = directory.stat()
    except OSError:
        raise PiConfigurationError(
            "Prepare an existing private Agentvolve run registry (0700) on a permission-capable filesystem"
        ) from None
    if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.geteuid() or not os.access(directory, os.R_OK | os.W_OK | os.X_OK)):
        raise PiConfigurationError(
            "Agentvolve run registry must be an owner-controlled 0700 directory on a permission-capable filesystem; use an ext4-backed path such as ~/.local/share/metering/agentvolve-runs"
        )
    return directory


def validate_record(record: object, workflow_root: Path) -> dict:
    expected = {"execution_schema", "command", "runtime_id", "implementation_version",
                "configuration_directory", "configuration_source", "models_sha256"}
    if type(record) is not dict or set(record) != expected or record.get("execution_schema") != EXECUTION_SCHEMA:
        raise PiConfigurationError("Pi execution binding has an unexpected schema")
    for key in ("runtime_id", "models_sha256"):
        if type(record[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", record[key]):
            raise PiConfigurationError("Pi execution binding has an invalid digest")
    command = record["command"]
    if (type(command) is not list or not 1 <= len(command) <= 128
            or any(type(arg) is not str or not arg or "\x00" in arg or len(arg) > 8192 for arg in command)
            or not Path(command[0]).is_absolute() or ".." in Path(command[0]).parts
            or str(Path(command[0])) != command[0]):
        raise PiConfigurationError("Pi execution command must retain its absolute resolved prefix")
    if type(record["implementation_version"]) is not str or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?", record["implementation_version"]
    ):
        raise PiConfigurationError("Pi execution binding requires an exact version")
    # Source provenance is historical: recovery must not open it or require it to exist.
    source = record["configuration_source"]
    if type(source) is not str or "\x00" in source or not Path(source).is_absolute() or ".." in Path(source).parts:
        raise PiConfigurationError("Pi execution source provenance is malformed")
    snapshot = record["configuration_directory"]
    if snapshot != str(workflow_root.resolve() / SNAPSHOT_NAME):
        raise PiConfigurationError("Pi execution configuration must stay within its workflow root")
    return record


def execution_record(workflow_root: Path, approved: dict) -> dict:
    source = configuration_source(Path(approved["worker_configuration"]))
    snapshot = resolved_path(str(workflow_root)) / SNAPSHOT_NAME
    record = {
        "execution_schema": EXECUTION_SCHEMA,
        "command": approved["command"],
        "runtime_id": approved["runtime_id"],
        "implementation_version": approved["implementation_version"],
        "configuration_directory": str(snapshot),
        "configuration_source": str(source),
        "models_sha256": approved["worker_models_sha256"],
    }
    return validate_record(record, workflow_root)


def snapshot_configuration(workflow_root: Path, record: dict) -> None:
    record = validate_record(record, workflow_root)
    source = configuration_source(Path(record["configuration_source"]))
    snapshot = resolved_path(record["configuration_directory"])
    snapshot.mkdir(mode=0o700)  # Exclusive; failures retain the request and copied evidence.
    snapshot.chmod(0o700)
    models = bounded_file(source / "models.json")
    atomic_write(snapshot / "models.json", models)
    (snapshot / "models.json").chmod(0o600)
    if hashlib.sha256(models).hexdigest() != record["models_sha256"]:
        raise PiConfigurationError("Copied Pi models.json differs from the approved review SHA256; evidence retained")
    auth = bounded_file(source / "auth.json", optional=True)
    if auth is not None:
        atomic_write(snapshot / "auth.json", auth)
        (snapshot / "auth.json").chmod(0o600)


def child_environment(workflow_root: Path, request: dict, *, probe: bool = False) -> dict[str, str]:
    """Validate v2 bindings and derive a child-only environment; never mutate os.environ.

    v1 callers retain their ambient environment. Auth is private mutable data, not
    hashed identity. Neither recovery nor execution reads the original config source.
    """
    environment = dict(os.environ)
    if request.get("workflow_schema") == "agentvolve-worker-request-v1" and "pi_execution" not in request:
        return environment
    if request.get("workflow_schema") != WORKFLOW_SCHEMA:
        raise PiConfigurationError("Unsupported Pi workflow execution schema")
    record = validate_record(request.get("pi_execution"), workflow_root)
    if str(Path(record["command"][0]).resolve()) != record["command"][0]:
        raise PiConfigurationError("Job-owned Pi command path changed; execution refused")
    if request.get("harness_descriptor") is None or request.get("harness_run_root") is not None:
        raise PiConfigurationError("Configured Pi workflows require an explicit sealed harness")
    snapshot = resolved_path(record["configuration_directory"])
    if not snapshot.is_dir() or stat.S_IMODE(snapshot.stat().st_mode) != 0o700:
        raise PiConfigurationError("Pi configuration snapshot must remain a private 0700 directory")
    models = bounded_file(snapshot / "models.json", private=True)
    if hashlib.sha256(models).hexdigest() != record["models_sha256"]:
        raise PiConfigurationError("Job-owned Pi models.json changed; execution refused")
    bounded_file(snapshot / "auth.json", optional=True, private=True)
    runtime_paths = [Path(request["runtime_manifest"])]
    stored_runtime = Path(request["solution_run_root"]) / "runtime.json"
    if stored_runtime.exists() or stored_runtime.is_symlink():
        runtime_paths.append(stored_runtime)
    for path in runtime_paths:
        bounded_file(path)
        runtime = load_runtime_manifest(path)
        if (runtime.runtime_id != record["runtime_id"] or runtime.model["connector"] != "pi-v1"
                or not runtime.isolation_enforced
                or runtime.model["implementation_version"] != record["implementation_version"]):
            raise PiConfigurationError("Job-owned Pi runtime identity changed; execution refused")
    environment.update({
        "METERING_PI_CONFIG_DIR": str(snapshot),
        "PI_CODING_AGENT_DIR": str(snapshot),
        "METERING_PI_COMMAND": canonical_json(record["command"]),
    })
    if probe:
        validate_bound_command(record["command"], record["implementation_version"], environment)
    return environment
