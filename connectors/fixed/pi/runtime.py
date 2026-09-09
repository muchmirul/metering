"""Upgrade-safe Pi operator transport, outside immutable experiment mechanics.

Resolve a manifest's exact Pi release offline. Never reinterpret a runtime ID,
install packages implicitly, or grant retry authority. The unchanged worker and
connectors still enforce their canonical requests and exact version checks.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from apps._support.bounded_process import OutputLimitError, communicate_bounded
from apps._support.wire import canonical_json
from apps.harness.runtime_manifest import load_runtime_manifest
from connectors.fixed.command import command_prefix

REQUIRED_FLAGS = frozenset(
    {
        "--provider",
        "--model",
        "--thinking",
        "--no-session",
        "--no-skills",
        "--no-extensions",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--no-tools",
        "--mode",
        "--system-prompt",
        "--print",
    }
)
VERSION = re.compile(
    r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?\Z"
)


class PiRuntimeError(ValueError):
    """An exact, CLI-compatible implementation cannot be selected safely."""


def _probe(command: list[str], option: str) -> str:
    try:
        with subprocess.Popen(
            [*command, option],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ) as process:
            stdout, stderr = communicate_bounded(
                process, None, timeout_seconds=10, max_output_bytes=131072
            )
            if process.returncode or stderr:
                raise PiRuntimeError(f"Pi {option} failed; no experiment was started")
            return stdout.strip()
    except (OSError, UnicodeError, subprocess.TimeoutExpired, OutputLimitError) as exc:
        raise PiRuntimeError(f"Pi {option} probe failed: {type(exc).__name__}") from exc


def _absolute(command: list[str]) -> list[str]:
    executable = shutil.which(command[0])
    if executable is None:
        raise PiRuntimeError("Pi executable is unavailable")
    return [str(Path(executable).absolute().resolve()), *command[1:]]


def resolve(expected: str) -> dict:
    """Accept any release with the required CLI contract, but only at its exact pin."""
    if not VERSION.fullmatch(expected):
        raise PiRuntimeError(
            "Pi runtime must pin an exact release, not 'latest' or a version range"
        )
    command = command_prefix("METERING_PI_COMMAND", "PI_BIN", "pi")
    explicit = "METERING_PI_COMMAND" in os.environ or "PI_BIN" in os.environ
    observed = "unavailable"
    try:
        command = _absolute(command)
        observed = _probe(command, "--version")
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
        actual = _probe(command, "--version")
        if actual != expected:
            raise PiRuntimeError(
                f"Cached Pi reports {actual}; expected exactly {expected}"
            )
        source = "version-cache"
    flags = set(re.findall(r"--[a-z][a-z-]*", _probe(command, "--help")))
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


def check(path: Path) -> dict:
    runtime = load_runtime_manifest(path)
    if runtime.model["connector"] != "pi-v1":
        raise PiRuntimeError("Pi runtime resolution requires a pi-v1 manifest")
    return {
        **resolve(runtime.model["implementation_version"]),
        "runtime_id": runtime.runtime_id,
    }


def review(path: Path, harness: Path) -> dict:
    """Read-only per-job execution review; never infer a harness or run setup."""
    from apps.coding_agent.harness_workspace_editor import load_harness_descriptor
    from apps.harness.experiment_replay import verify_experiment

    runtime = load_runtime_manifest(path)
    if runtime.model["connector"] != "pi-v1" or not runtime.isolation_enforced:
        raise PiRuntimeError("Delegated Pi jobs require a pi-v1 reviewed OCI runtime")
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
    selection = check(path)
    return {
        **selection,
        "review_schema": "agentvolve-execution-review-v1",
        "model": runtime.model,
        "worker_configuration": str(configuration),
        "worker_models_sha256": hashlib.sha256(models.read_bytes()).hexdigest(),
        "harness_candidate_id": descriptor["candidate_id"],
        "harness_descriptor_sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
        "kernel": runtime.document["kernel"],
        "max_model_calls_per_execution": runtime.max_model_calls,
        "model_timeout_seconds": runtime.model_timeout_seconds,
        "level_2_setup": "none; reused verified seal",
    }


def main(arguments: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    try:
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
        else:
            raise PiRuntimeError(
                "usage: review RUNTIME.json HARNESS.json | check RUNTIME.json | start RUNS TASK.json RUNTIME.json [HARNESS.json] | resume WORKFLOW | retry WORKFLOW REASON"
            )
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
