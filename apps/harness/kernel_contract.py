"""Fixed supervisor for persistent candidate-owned IPython state in isolation."""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from apps._support.wire import canonical_json
from apps.harness.resources import ResourceObservation, ResourceObserver, cgroup_for_pid
from apps.harness.runtime_manifest import RuntimeManifest
from apps.harness.workspace import (
    WorkspaceError,
    decode_export,
    decode_files,
    normalize_policy,
)

KERNEL_PROTOCOL = "harness-kernel-wire-v1"
MAX_KERNEL_RESPONSE_BYTES = 16_777_216
ROOT = Path(__file__).resolve().parents[2]


class KernelContractError(RuntimeError):
    """Raised when an isolated kernel violates its fixed wire contract."""


@dataclass(frozen=True)
class KernelExecution:
    status: str
    result_repr: str | None
    stdout: str
    stderr: str
    error: str | None

    def document(self) -> dict[str, object]:
        return {
            "error": self.error,
            "result_repr": self.result_repr,
            "status": self.status,
            "stderr": self.stderr,
            "stdout": self.stdout,
        }


class _WireProcess:
    def __init__(self, command: list[str], *, name: str | None, oci: bool) -> None:
        self.command = command
        self.name = name
        self.oci = oci
        try:
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                start_new_session=os.name == "posix",
                env=_process_environment(),
            )
        except OSError as exc:
            raise KernelContractError(f"cannot start isolated kernel: {exc}") from exc
        self.lines: queue.Queue[str | KernelContractError | None] = queue.Queue()
        self.stderr: list[str] = []
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        stream = self.process.stdout.buffer
        try:
            while True:
                raw = stream.readline(MAX_KERNEL_RESPONSE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_KERNEL_RESPONSE_BYTES or not raw.endswith(b"\n"):
                    self.lines.put(
                        KernelContractError("kernel response exceeds the wire limit")
                    )
                    self.process.kill()
                    break
                try:
                    line = raw.decode("utf-8")
                except UnicodeDecodeError:
                    self.lines.put(KernelContractError("kernel response is not UTF-8"))
                    self.process.kill()
                    break
                self.lines.put(line)
        finally:
            self.lines.put(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        total = 0
        for chunk in iter(lambda: self.process.stderr.read(4096), ""):
            if total < 65_536:
                kept = chunk[: 65_536 - total]
                self.stderr.append(kept)
                total += len(kept)

    def write(self, document: dict[str, object]) -> None:
        if self.process.poll() is not None or self.process.stdin is None:
            raise KernelContractError(
                self.failure_detail("kernel exited before request")
            )
        try:
            self.process.stdin.write(canonical_json(document) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise KernelContractError(
                self.failure_detail("kernel wire is closed")
            ) from exc

    def receive(self, timeout_seconds: float) -> str:
        try:
            line = self.lines.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise TimeoutError from exc
        if line is None:
            raise KernelContractError(
                self.failure_detail("kernel exited without a response")
            )
        if isinstance(line, KernelContractError):
            raise line
        return line

    def failure_detail(self, fallback: str) -> str:
        detail = "".join(self.stderr).strip()
        return detail or fallback

    def wait(self, timeout: float) -> None:
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.kill()

    def interrupt(self) -> None:
        if self.process.poll() is not None:
            return
        if self.oci:
            self._docker_control(["kill", "--signal", "SIGINT", cast(str, self.name)])
        elif os.name == "posix":
            try:
                os.killpg(self.process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        else:
            self.process.send_signal(signal.SIGINT)

    def kill(self) -> None:
        if self.process.poll() is None:
            if self.oci:
                self._docker_control(["kill", cast(str, self.name)], check=False)
            elif os.name == "posix":
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                self.process.kill()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def remove_container(self) -> None:
        if self.oci and self.name is not None:
            self._docker_control(["rm", "--force", self.name], check=False)

    @staticmethod
    def _docker_control(arguments: list[str], *, check: bool = True) -> None:
        binary = os.environ.get("METERING_DOCKER_BIN", "docker")
        try:
            completed = subprocess.run(
                [binary, *arguments],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
                env=_process_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            if check:
                raise KernelContractError(
                    f"Docker control operation failed: {exc}"
                ) from exc
            return
        if check and completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise KernelContractError(detail or "Docker control operation failed")


def _process_environment() -> dict[str, str]:
    allowed = {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "SYSTEMROOT",
        "TMPDIR",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def _expand_command(runtime: RuntimeManifest) -> list[str]:
    replacements = {"{python}": sys.executable, "{root}": str(ROOT)}
    result: list[str] = []
    for argument in runtime.command:
        expanded = argument
        for token, value in replacements.items():
            expanded = expanded.replace(token, value)
        result.append(expanded)
    return result


def _docker_command(runtime: RuntimeManifest, name: str) -> list[str]:
    assert runtime.image is not None
    limits = runtime.limits
    binary = os.environ.get("METERING_DOCKER_BIN", "docker")
    cpus = f"{limits.cpu_millis / 1000:.3f}"
    return [
        binary,
        "run",
        "--pull",
        "never",
        "--name",
        name,
        "--interactive",
        "--network",
        "none",
        "--ipc",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(limits.pids),
        "--ulimit",
        "core=0:0",
        "--ulimit",
        "nofile=256:256",
        "--memory",
        str(limits.memory_bytes),
        "--memory-swap",
        str(limits.memory_bytes),
        "--cpus",
        cpus,
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={limits.tmpfs_bytes}",
        "--user",
        "65532:65532",
        "--env",
        "HOME=/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTHONUNBUFFERED=1",
        runtime.image,
        *_expand_command(runtime),
    ]


def _docker_pid(name: str) -> int | None:
    binary = os.environ.get("METERING_DOCKER_BIN", "docker")
    try:
        completed = subprocess.run(
            [binary, "inspect", "--format", "{{.State.Pid}}", name],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
            env=_process_environment(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        pid = int(completed.stdout.strip())
    except ValueError:
        return None
    return pid if pid > 0 else None


def _observer_target(wire: _WireProcess) -> tuple[str, Path] | None:
    if wire.oci:
        assert wire.name is not None
        pid = _docker_pid(wire.name)
        if pid is None:
            return None
        cgroup = cgroup_for_pid(pid)
        return None if cgroup is None else ("cgroup-v2", cgroup)
    if wire.process.poll() is not None:
        return None
    return "procfs", Path(str(wire.process.pid))


class KernelSession:
    """Own one or more restarted kernels and preserve bounded snapshots."""

    def __init__(
        self,
        runtime: RuntimeManifest,
        bootstrap: str,
        snapshot_policy: dict[str, object],
        *,
        allow_fixture: bool = False,
    ) -> None:
        if runtime.kind == "process-fixture-v1" and not allow_fixture:
            raise KernelContractError(
                "process-fixture-v1 is unsafe and only permitted by deterministic tests"
            )
        self.runtime = runtime
        self.bootstrap = bootstrap
        self.snapshot_policy = snapshot_policy
        self._next_id = 1
        self._wire: _WireProcess | None = None
        self._observer: ResourceObserver | None = None
        self._observations: list[ResourceObservation] = []
        self._latest_snapshot: dict[str, object] | None = None
        self._workspace_policy: dict[str, object] | None = None
        self._latest_workspace_files: list[dict[str, object]] | None = None
        self._closed = False
        self._start()

    def _start(self) -> None:
        name: str | None = None
        if self.runtime.kind == "oci-v1":
            if self.runtime.image is not None and self.runtime.image.endswith(
                "sha256:" + "0" * 64
            ):
                raise KernelContractError(
                    "OCI runtime image digest is a non-runnable placeholder"
                )
            name = f"metering-harness-{uuid.uuid4().hex}"
            command = _docker_command(self.runtime, name)
            oci = True
        else:
            command = _expand_command(self.runtime)
            oci = False
        wire = _WireProcess(command, name=name, oci=oci)
        self._wire = wire
        self._observer = ResourceObserver(lambda: _observer_target(wire))
        try:
            result = self._request(
                {
                    "bootstrap": self.bootstrap,
                    "operation": "boot",
                    "snapshot_policy": self.snapshot_policy,
                },
                timeout_ms=self.runtime.limits.wall_milliseconds,
            )
            if type(result) is not dict or set(result) != {
                "engine",
                "stderr",
                "stdout",
            }:
                raise KernelContractError("kernel boot response is malformed")
            if result["stderr"] or result["stdout"]:
                raise KernelContractError("candidate bootstrap must not write output")
            if (
                self._latest_snapshot is not None
                and self.snapshot_policy.get("restore_after_restart") is True
            ):
                self._request(
                    {"operation": "restore", "snapshot": self._latest_snapshot},
                    timeout_ms=self.runtime.limits.wall_milliseconds,
                )
            if (
                self._workspace_policy is not None
                and self._latest_workspace_files is not None
            ):
                self._initialize_workspace_request(
                    self._latest_workspace_files, self._workspace_policy
                )
        except BaseException:
            self._stop_wire()
            raise

    def _request(self, body: dict[str, object], *, timeout_ms: int) -> object:
        wire = self._wire
        if wire is None:
            raise KernelContractError("kernel is not running")
        request_id = self._next_id
        self._next_id += 1
        request = {"id": request_id, **body}
        wire.write(request)
        source = wire.receive(timeout_ms / 1000)
        try:
            response = json.loads(source)
        except json.JSONDecodeError as exc:
            raise KernelContractError("kernel returned invalid JSON") from exc
        if type(response) is not dict or set(response) not in (
            {"id", "ok", "protocol", "result"},
            {"error", "id", "ok", "protocol"},
        ):
            raise KernelContractError("kernel response has the wrong keys")
        if (
            response.get("id") != request_id
            or response.get("protocol") != KERNEL_PROTOCOL
        ):
            raise KernelContractError("kernel response identity is invalid")
        if response.get("ok") is True:
            return response["result"]
        error = response.get("error")
        if type(error) is not dict or set(error) != {"code", "message"}:
            raise KernelContractError("kernel error response is malformed")
        if type(error["code"]) is not str or type(error["message"]) is not str:
            raise KernelContractError("kernel error response is malformed")
        raise _KernelResponseError(error["code"], error["message"])

    def execute(
        self,
        code: str,
        *,
        timeout_ms: int,
        interrupt: bool = False,
        interrupt_grace_ms: int = 500,
    ) -> KernelExecution:
        if self._closed:
            raise KernelContractError("kernel session is closed")
        wire = cast(_WireProcess, self._wire)
        request_id = self._next_id
        self._next_id += 1
        wire.write({"code": code, "id": request_id, "operation": "execute"})
        effective_timeout_ms = min(timeout_ms, self.runtime.limits.wall_milliseconds)
        effective_grace_ms = min(
            interrupt_grace_ms, self.runtime.limits.wall_milliseconds
        )
        try:
            source = wire.receive(effective_timeout_ms / 1000)
        except TimeoutError:
            if interrupt:
                wire.interrupt()
                try:
                    source = wire.receive(effective_grace_ms / 1000)
                except (TimeoutError, KernelContractError):
                    self._restart()
                    return KernelExecution(
                        "interrupted", None, "", "", "interrupt grace expired"
                    )
                execution = self._decode_execution_response(source, request_id)
                self._restart()
                return KernelExecution(
                    "interrupted",
                    None,
                    execution.stdout,
                    execution.stderr,
                    execution.error,
                )
            self._restart()
            return KernelExecution(
                "timeout", None, "", "", "execution deadline expired"
            )
        return self._decode_execution_response(source, request_id)

    def _decode_execution_response(
        self, source: str, request_id: int
    ) -> KernelExecution:
        try:
            response = json.loads(source)
        except json.JSONDecodeError as exc:
            raise KernelContractError("kernel returned invalid execution JSON") from exc
        if type(response) is not dict or response.get("id") != request_id:
            raise KernelContractError("kernel execution response identity is invalid")
        if (
            response.get("protocol") != KERNEL_PROTOCOL
            or type(response.get("ok")) is not bool
        ):
            raise KernelContractError("kernel execution response is malformed")
        if response["ok"] is False:
            if set(response) != {"error", "id", "ok", "protocol"}:
                raise KernelContractError(
                    "kernel execution error response has the wrong keys"
                )
            error = response.get("error")
            if type(error) is not dict or set(error) != {"code", "message"}:
                raise KernelContractError("kernel execution error is malformed")
            if type(error["code"]) is not str or type(error["message"]) is not str:
                raise KernelContractError("kernel execution error is malformed")
            status = "interrupted" if error["code"] == "interrupted" else "error"
            return KernelExecution(status, None, "", "", error["message"])
        if set(response) != {"id", "ok", "protocol", "result"}:
            raise KernelContractError("kernel execution response has the wrong keys")
        result = response["result"]
        if type(result) is not dict or set(result) != {
            "result_repr",
            "stderr",
            "stdout",
        }:
            raise KernelContractError("kernel execution result is malformed")
        if result["result_repr"] is not None and type(result["result_repr"]) is not str:
            raise KernelContractError("kernel result_repr is malformed")
        if type(result["stdout"]) is not str or type(result["stderr"]) is not str:
            raise KernelContractError("kernel output is malformed")
        return KernelExecution(
            "ok",
            cast(str | None, result["result_repr"]),
            str(result["stdout"]),
            str(result["stderr"]),
            None,
        )

    def _initialize_workspace_request(
        self,
        files: list[dict[str, object]],
        policy: dict[str, object],
    ) -> dict[str, object]:
        result = self._request(
            {"files": files, "operation": "workspace_init", "policy": policy},
            timeout_ms=self.runtime.limits.wall_milliseconds,
        )
        if type(result) is not dict or set(result) != {
            "file_count",
            "sha256",
            "total_bytes",
        }:
            raise KernelContractError("kernel workspace initialization is malformed")
        if (
            type(result["file_count"]) is not int
            or result["file_count"] != len(files)
            or type(result["total_bytes"]) is not int
            or result["total_bytes"] < 0
            or type(result["sha256"]) is not str
            or len(result["sha256"]) != 64
        ):
            raise KernelContractError("kernel workspace initialization is inconsistent")
        return result

    def initialize_workspace(self, files: object, policy: object) -> dict[str, object]:
        if self._closed:
            raise KernelContractError("kernel session is closed")
        try:
            normalized_policy = normalize_policy(policy)
            normalized_files = decode_files(
                files,
                max_files=int(normalized_policy["max_files"]),
                max_bytes=int(normalized_policy["max_bytes"]),
            )
        except WorkspaceError as exc:
            raise KernelContractError(str(exc)) from exc
        result = self._initialize_workspace_request(normalized_files, normalized_policy)
        self._workspace_policy = normalized_policy
        self._latest_workspace_files = normalized_files
        return result

    def export_workspace(self) -> dict[str, object]:
        if self._workspace_policy is None:
            raise KernelContractError("kernel workspace is not initialized")
        result = self._request(
            {"operation": "workspace_export"},
            timeout_ms=self.runtime.limits.wall_milliseconds,
        )
        try:
            normalized = decode_export(result, self._workspace_policy)
        except WorkspaceError as exc:
            raise KernelContractError(str(exc)) from exc
        self._latest_workspace_files = cast(
            list[dict[str, object]], normalized["files"]
        )
        return normalized

    def run_workspace_command(
        self, argv: list[str], *, timeout_ms: int
    ) -> dict[str, object]:
        if self._workspace_policy is None:
            raise KernelContractError("kernel workspace is not initialized")
        maximum = int(self._workspace_policy["command_timeout_ms"])
        if (
            not argv
            or any(type(item) is not str or not item or "\x00" in item for item in argv)
            or type(timeout_ms) is not int
            or not 1 <= timeout_ms <= maximum
        ):
            raise KernelContractError("kernel workspace command is malformed")
        result = self._request(
            {"argv": argv, "operation": "workspace_run", "timeout_ms": timeout_ms},
            timeout_ms=min(timeout_ms + 5_000, self.runtime.limits.wall_milliseconds),
        )
        if type(result) is not dict or set(result) != {
            "returncode",
            "stderr",
            "stdout",
            "timed_out",
        }:
            raise KernelContractError("kernel workspace command response is malformed")
        if (
            (result["returncode"] is not None and type(result["returncode"]) is not int)
            or type(result["stderr"]) is not str
            or type(result["stdout"]) is not str
            or type(result["timed_out"]) is not bool
        ):
            raise KernelContractError("kernel workspace command response is malformed")
        return result

    def snapshot(self) -> dict[str, object]:
        result = self._request(
            {"operation": "snapshot"},
            timeout_ms=self.runtime.limits.wall_milliseconds,
        )
        if type(result) is not dict or set(result) != {"sha256", "values"}:
            raise KernelContractError("kernel snapshot response is malformed")
        self._latest_snapshot = result
        return result

    def restore(self, snapshot: dict[str, object]) -> None:
        self._request(
            {"operation": "restore", "snapshot": snapshot},
            timeout_ms=self.runtime.limits.wall_milliseconds,
        )
        self._latest_snapshot = snapshot

    def cleanup(self) -> None:
        self._request(
            {"operation": "cleanup"},
            timeout_ms=self.runtime.limits.wall_milliseconds,
        )
        self._latest_snapshot = None
        self._workspace_policy = None
        self._latest_workspace_files = None

    def ping(self) -> dict[str, object]:
        result = self._request(
            {"operation": "ping"}, timeout_ms=self.runtime.limits.wall_milliseconds
        )
        if type(result) is not dict or set(result) != {"engine"}:
            raise KernelContractError("kernel ping response is malformed")
        return result

    def _restart(self) -> None:
        self._stop_wire()
        self._start()

    def _stop_wire(self) -> None:
        wire = self._wire
        observer = self._observer
        self._wire = None
        self._observer = None
        if wire is not None:
            wire.kill()
        if observer is not None:
            self._observations.append(observer.stop())
        if wire is not None:
            wire.remove_container()

    def close(self) -> list[ResourceObservation]:
        if self._closed:
            return list(self._observations)
        wire = self._wire
        shutdown_error: KernelContractError | None = None
        if wire is not None:
            try:
                self._request(
                    {"operation": "shutdown"},
                    timeout_ms=self.runtime.limits.wall_milliseconds,
                )
                wire.wait(2)
                if wire.process.returncode != 0:
                    raise KernelContractError("kernel shutdown returned nonzero status")
            except (KernelContractError, TimeoutError, _KernelResponseError) as exc:
                shutdown_error = KernelContractError(
                    f"kernel did not complete a clean shutdown: {exc}"
                )
                wire.kill()
        observer = self._observer
        self._wire = None
        self._observer = None
        if observer is not None:
            self._observations.append(observer.stop())
        if wire is not None:
            wire.remove_container()
        self._closed = True
        self._verify_observations()
        if shutdown_error is not None:
            raise shutdown_error
        return list(self._observations)

    def _verify_observations(self) -> None:
        available = {"wall"}
        for item in self._observations:
            if item.cpu_microseconds is not None:
                available.add("cpu")
            if item.memory_peak_bytes is not None:
                available.add("memory")
            if item.processes_peak is not None:
                available.add("processes")
            if item.storage_write_bytes is not None:
                available.add("storage")
        missing = sorted(set(self.runtime.required_observations) - available)
        if missing:
            raise KernelContractError(
                "required external resource observations are unavailable: "
                + ", ".join(missing)
            )

    def __enter__(self) -> KernelSession:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class _KernelResponseError(KernelContractError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
