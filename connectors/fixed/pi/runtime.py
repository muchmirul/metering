"""Upgrade-safe Pi operator transport, outside immutable experiment mechanics.

Resolve a manifest's exact Pi release offline. Never reinterpret a runtime ID,
install packages implicitly, or grant retry authority. Configured starts bind a
private job context; worker controls and experiment version checks remain intact.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
from pathlib import Path

from apps._support.wire import canonical_json, decode_json_object
from apps.coding_agent.pi_execution import (
    MAX_REVIEW_BYTES,
    REQUIRED_FLAGS,
    PiConfigurationError,
    bounded_file,
    child_environment,
    configuration_source,
    private_runs_directory,
)
from apps.coding_agent import pi_execution
from connectors.fixed.pi.readiness import local_model
from apps.harness.runtime_manifest import load_runtime_manifest
from connectors.fixed.command import command_prefix

VERSION = re.compile(
    r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?\Z"
)


class PiRuntimeError(ValueError):
    """An exact, CLI-compatible implementation cannot be selected safely."""


def _probe(command: list[str], option: str, *, environment: dict[str, str] | None = None) -> str:
    try:
        return pi_execution.probe_command(command, option, environment=environment)
    except PiConfigurationError as exc:
        raise PiRuntimeError(str(exc)) from exc


def _absolute(command: list[str]) -> list[str]:
    executable = shutil.which(command[0])
    if executable is None:
        raise PiRuntimeError("Pi executable is unavailable")
    return [str(Path(executable).absolute().resolve()), *command[1:]]


def resolve(expected: str, *, configuration: Path | None = None) -> dict:
    """Accept any release with the required CLI contract, but only at its exact pin."""
    if not VERSION.fullmatch(expected):
        raise PiRuntimeError(
            "Pi runtime must pin an exact release, not 'latest' or a version range"
        )
    command = command_prefix("METERING_PI_COMMAND", "PI_BIN", "pi")
    explicit = "METERING_PI_COMMAND" in os.environ or "PI_BIN" in os.environ
    probe_options = {} if configuration is None else {"environment": {
        **os.environ, "METERING_PI_CONFIG_DIR": str(configuration), "PI_CODING_AGENT_DIR": str(configuration),
    }}
    observed = "unavailable"
    try:
        command = _absolute(command)
        observed = _probe(command, "--version", **probe_options)
    except PiRuntimeError:
        if explicit:
            raise
    source = "explicit" if explicit else "PATH"
    if observed != expected:
        if explicit:
            raise PiRuntimeError(
                f"Explicit Pi reports {observed}; runtime requires {expected}. Fix the override; it will not be silently replaced."
            )
        cache = Path(
            os.environ.get(
                "METERING_PI_RUNTIME_DIR", str(Path.home() / ".cache/metering/pi")
            )
        ).expanduser()
        if not cache.is_absolute():
            raise PiRuntimeError("METERING_PI_RUNTIME_DIR must be absolute")
        prefix = cache / expected
        binary = prefix / "node_modules/.bin/pi"
        if not binary.is_file():
            raise PiRuntimeError(
                f"Runtime requires Pi {expected}; PATH reports {observed}. Install a separate copy, without changing the global Pi or manifest: npm install --prefix {prefix} --save-exact @earendil-works/pi-coding-agent@{expected}"
            )
        command = _absolute([str(binary)])
        actual = _probe(command, "--version", **probe_options)
        if actual != expected:
            raise PiRuntimeError(
                f"Cached Pi reports {actual}; expected exactly {expected}"
            )
        source = "version-cache"
    flags = set(re.findall(r"--[a-z][a-z-]*", _probe(command, "--help", **probe_options)))
    missing = REQUIRED_FLAGS - flags
    if missing:
        raise PiRuntimeError(
            f"Pi {expected} is missing required isolation/transport flags: {', '.join(sorted(missing))}"
        )
    return {
        "runtime_selection_schema": "agentvolve-pi-runtime-selection-v1",
        "authority": "diagnostic-only",
        "command": command,
        "implementation_version": expected,
        "source": source,
        "cli_contract": "tool-free-json-cli-v1",
        "inference_performed": False,
    }


def check(path: Path, *, configuration: Path | None = None) -> dict:
    runtime = load_runtime_manifest(path)
    connector = runtime.model["connector"]
    if connector not in {"pi-v1", "pi-v2"}:
        raise PiRuntimeError("Pi runtime resolution requires a pi-v1 or pi-v2 manifest")
    selection = resolve(
        runtime.model["implementation_version"],
        **({} if configuration is None else {"configuration": configuration}),
    )
    if connector == "pi-v2":
        selection["cli_contract"] = "tool-free-json-cli-v2"
    return {**selection, "runtime_id": runtime.runtime_id}


def review(path: Path, harness: Path, *, configuration: Path | None = None) -> dict:
    """Read-only per-job execution review; never infer a harness or run setup."""
    from apps.coding_agent.harness_workspace_editor import load_harness_descriptor
    from apps.harness.experiment_replay import verify_experiment

    runtime = load_runtime_manifest(path)
    if (
        runtime.model["connector"] not in {"pi-v1", "pi-v2"}
        or not runtime.isolation_enforced
    ):
        raise PiRuntimeError(
            "Delegated Pi jobs require a pi-v1 or pi-v2 reviewed OCI runtime"
        )
    descriptor = load_harness_descriptor(harness)
    if descriptor["runtime_id"] != runtime.runtime_id:
        raise PiRuntimeError(
            f"Selected harness runtime {descriptor['runtime_id']} differs from required {runtime.runtime_id}. "
            "Choose an explicitly compatible verified seal, or separately approve/budget Level-2 setup; no automatic setup."
        )
    if harness.name != "selected-harness.json":
        raise PiRuntimeError("Use the original sealed run's selected-harness.json")
    provenance = verify_experiment(harness.parent)
    final = descriptor["provenance"]
    if (provenance.get("assay") != "coding-agent-v1"
            or final["final_passed_count"] != final["final_task_count"]
            or final["final_safety_failures"] != 0):
        raise PiRuntimeError("Selected harness must pass its verified protected coding assay")
    if configuration is None:
        configured = os.environ.get("METERING_PI_CONFIG_DIR", "")
        configuration = Path(configured)
        interactive = Path(os.environ.get("PI_CODING_AGENT_DIR", str(Path.home() / ".pi/agent")))
        if (not configuration.is_absolute() or not configuration.is_dir()
                or configuration.is_symlink() or configuration.resolve() == interactive.resolve()):
            raise PiRuntimeError(
                "Set METERING_PI_CONFIG_DIR to a separate reviewed worker configuration directory, "
                "not the interactive Pi directory. Provision its provider auth/models explicitly and keep routing stable while jobs run."
            )
        models = configuration / "models.json"
        if models.is_symlink() or not models.is_file() or models.stat().st_size > 2_097_152:
            raise PiRuntimeError("Worker configuration requires a bounded regular reviewed models.json")
        models_bytes = models.read_bytes()
        selection = check(path)
    else:
        configuration = configuration_source(configuration)
        models_bytes = bounded_file(configuration / "models.json")
        bounded_file(configuration / "auth.json", optional=True)
        selection = check(path, configuration=configuration)
    return {
        **selection,
        "review_schema": "agentvolve-execution-review-v1",
        "model": runtime.model,
        "worker_configuration": str(configuration),
        "worker_models_sha256": hashlib.sha256(models_bytes).hexdigest(),
        "harness_candidate_id": descriptor["candidate_id"],
        "harness_descriptor_sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
        "kernel": runtime.document["kernel"],
        "max_model_calls_per_execution": runtime.max_model_calls,
        "model_timeout_seconds": runtime.model_timeout_seconds,
        "level_2_setup": "none; reused verified seal",
    }


def review_configured(path: Path, harness: Path, configuration: Path,
                      runs: Path | None = None) -> dict:
    document = review(path, harness, configuration=configuration)
    if runs is not None:
        document["runs_directory"] = str(private_runs_directory(runs))
    return document


def start_configured(runs: Path, task: Path, manifest: Path, harness: Path,
                     configuration: Path, review_path: Path) -> dict:
    from apps.coding_agent.agentvolve_worker import start_workflow

    try:
        approved = decode_json_object(
            bounded_file(review_path.expanduser().absolute(), limit=MAX_REVIEW_BYTES).decode("utf-8"), PiRuntimeError
        )
    except (ValueError, UnicodeError, RecursionError):
        # No parser echoes of operator-provided keys/values (potential credentials).
        raise PiRuntimeError("Approved execution review must be bounded strict JSON") from None
    if approved.get("worker_configuration") != str(configuration_source(configuration)):
        raise PiRuntimeError("Approved execution review configuration differs from the selected directory")
    reviewed_runs = approved.get("runs_directory")
    if reviewed_runs is not None and reviewed_runs != str(private_runs_directory(runs)):
        raise PiRuntimeError("Approved execution review registry differs from the selected private directory")
    fresh = review_configured(manifest, harness, configuration, runs if reviewed_runs is not None else None)
    if canonical_json(fresh) != canonical_json(approved):
        raise PiRuntimeError("Execution review changed; review and approve again before dispatch")
    local_model(manifest, configuration)  # Read-only; never load or replace a shared model.
    # The worker independently checks the copied bytes and runtime/command binding.
    return start_workflow(runs, task, manifest, harness, execution=approved)


def main(arguments: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    try:
        if len(args) == 3 and args[0] == "ready-configured":
            print(canonical_json(local_model(Path(args[1]), Path(args[2]))))
            return 0
        if len(args) in {4, 5} and args[0] == "discover-configured":
            from connectors.fixed.pi.setup import discover

            print(canonical_json(discover(*(Path(arg) for arg in args[1:]))))
            return 0
        if len(args) in {4, 5} and args[0] == "review-configured":
            print(canonical_json(review_configured(Path(args[1]), Path(args[2]), Path(args[3]),
                                                   None if len(args) == 4 else Path(args[4]))))
            return 0
        if len(args) == 7 and args[0] == "start-configured":
            print(canonical_json(start_configured(*(Path(arg) for arg in args[1:]))))
            return 0
        environment = None
        if len(args) == 3 and args[0] == "review":
            print(canonical_json(review(Path(args[1]), Path(args[2]))))
            return 0
        if len(args) == 2 and args[0] == "check":
            print(canonical_json(check(Path(args[1]))))
            return 0
        if len(args) in {4, 5} and args[0] == "start":
            manifest = Path(args[3])
        elif (len(args) == 2 and args[0] == "resume") or (
            len(args) == 3 and args[0] == "retry" and args[2].strip()
        ):
            from apps.coding_agent.agentvolve_worker import load_workflow_request

            request = load_workflow_request(Path(args[1]))
            manifest = Path(str(request["runtime_manifest"]))
            if "pi_execution" in request:
                environment = child_environment(Path(args[1]), request)
                local_model(manifest, Path(environment["METERING_PI_CONFIG_DIR"]))
        else:
            raise PiRuntimeError(
                "usage: ready-configured RUNTIME.json CONFIG_DIRECTORY | "
                "discover-configured RUNS RUNTIME.json CONFIG_DIRECTORY [HARNESS.json] | "
                "review-configured RUNTIME.json HARNESS.json CONFIG_DIRECTORY [PRIVATE_RUNS_DIRECTORY] | "
                "start-configured RUNS TASK.json RUNTIME.json HARNESS.json CONFIG_DIRECTORY REVIEW.json | "
                "review RUNTIME.json HARNESS.json | check RUNTIME.json | "
                "start RUNS TASK.json RUNTIME.json [HARNESS.json] | resume WORKFLOW | retry WORKFLOW REASON"
            )
        if environment is None:
            selection = check(manifest)
            environment = {
                **os.environ,
                "METERING_PI_COMMAND": canonical_json(selection["command"]),
            }
        # The worker remains the sole owner of launch/retry, budgets, locks and receipts.
        os.execve(
            sys.executable,
            [sys.executable, "-m", "apps.coding_agent.agentvolve_worker", *args],
            environment,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
