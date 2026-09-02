#!/usr/bin/env python3
"""Persistent JSON-lines kernel server used only inside a reviewed sandbox.

The module is intentionally standalone so the OCI image can copy this one file.
Candidate bootstrap and cells execute in this process, never in the host runner.
"""

from __future__ import annotations

import argparse
import ast
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import traceback
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

SERVER_PROTOCOL = "harness-kernel-wire-v1"
MAX_REQUEST_BYTES = 16_777_216
MAX_CAPTURE_CHARACTERS = 65_536
MAX_WORKSPACE_BYTES = 8_388_608
MAX_WORKSPACE_FILES = 2_000
WORKSPACE_ROOT = Path(f"/tmp/metering-workspace-{os.getpid()}")


def _canonical(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _error(request_id: object, code: str, message: str) -> dict[str, object]:
    return {
        "error": {"code": code, "message": message[:4096]},
        "id": request_id,
        "ok": False,
        "protocol": SERVER_PROTOCOL,
    }


def _success(request_id: object, result: object) -> dict[str, object]:
    return {
        "id": request_id,
        "ok": True,
        "protocol": SERVER_PROTOCOL,
        "result": result,
    }


def _json_safe(value: object) -> object:
    source = _canonical(value)
    return json.loads(source)


def _bounded_text(value: str) -> str:
    if len(value) <= MAX_CAPTURE_CHARACTERS:
        return value
    digest = hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()
    marker = f"...[truncated;sha256:{digest}]"
    return value[: MAX_CAPTURE_CHARACTERS - len(marker)] + marker


class FixtureEngine:
    """Small deterministic exec engine used by CI, not live acceptance."""

    name = "python-fixture-v1"

    def __init__(self) -> None:
        self.namespace: dict[str, Any] = {"__name__": "__harness_kernel__"}

    def reset(self) -> None:
        self.namespace = {"__name__": "__harness_kernel__"}

    def execute(self, code: str) -> object:
        tree = ast.parse(code, mode="exec")
        result: object = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            prefix = ast.Module(body=tree.body[:-1], type_ignores=[])
            if prefix.body:
                exec(compile(prefix, "<harness-cell>", "exec"), self.namespace)
            expression = ast.Expression(tree.body[-1].value)
            result = eval(compile(expression, "<harness-cell>", "eval"), self.namespace)
        else:
            exec(compile(tree, "<harness-cell>", "exec"), self.namespace)
        return result


class IPythonEngine:
    name = "ipython-v1"

    def __init__(self) -> None:
        try:
            from IPython.core.interactiveshell import InteractiveShell
        except ImportError as exc:
            raise RuntimeError(
                "the immutable runtime does not contain IPython"
            ) from exc
        self.shell = InteractiveShell.instance()
        self.reset()

    @property
    def namespace(self) -> dict[str, Any]:
        return self.shell.user_ns

    def reset(self) -> None:
        self.shell.reset(new_session=False)

    def execute(self, code: str) -> object:
        result = self.shell.run_cell(code, store_history=False, silent=False)
        error = result.error_before_exec or result.error_in_exec
        if error is not None:
            raise error
        return result.result


class KernelServer:
    def __init__(self, engine: FixtureEngine | IPythonEngine) -> None:
        self.engine = engine
        self.booted = False
        self.bootstrap = ""
        self.snapshot_policy: dict[str, object] = {}
        self.workspace_policy: dict[str, object] | None = None
        self.workspace_baseline: dict[str, tuple[str, bool]] = {}

    def _capture(self, operation: Callable[[], object]) -> tuple[object, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = operation()
        return (
            result,
            _bounded_text(stdout.getvalue()),
            _bounded_text(stderr.getvalue()),
        )

    def _boot(self, request: dict[str, object]) -> dict[str, object]:
        if set(request) != {"bootstrap", "id", "operation", "snapshot_policy"}:
            raise ValueError("boot request has the wrong keys")
        bootstrap = request["bootstrap"]
        policy = request["snapshot_policy"]
        if type(bootstrap) is not str or type(policy) is not dict:
            raise ValueError("boot bootstrap or snapshot_policy is malformed")
        if set(policy) != {
            "allowed_names",
            "max_bytes",
            "mode",
            "restore_after_restart",
            "schema_version",
        }:
            raise ValueError("boot snapshot_policy has the wrong keys")
        self.engine.reset()
        self.bootstrap = bootstrap
        self.snapshot_policy = policy
        _, stdout, stderr = self._capture(lambda: self.engine.execute(bootstrap))
        self.booted = True
        return {
            "engine": self.engine.name,
            "stderr": stderr,
            "stdout": stdout,
        }

    def _execute(self, request: dict[str, object]) -> dict[str, object]:
        if set(request) != {"code", "id", "operation"}:
            raise ValueError("execute request has the wrong keys")
        code = request["code"]
        if type(code) is not str or not code or "\x00" in code:
            raise ValueError("execute code must be non-empty text without NUL")
        result, stdout, stderr = self._capture(lambda: self.engine.execute(code))
        return {
            "result_repr": None if result is None else _bounded_text(repr(result)),
            "stderr": stderr,
            "stdout": stdout,
        }

    @staticmethod
    def _workspace_path(value: object, location: str) -> str:
        if type(value) is not str or not value or "\x00" in value or "\\" in value:
            raise ValueError(f"{location} must be a normalized relative POSIX path")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or path.as_posix() != value
            or any(part in {"", ".", "..", ".git"} for part in path.parts)
        ):
            raise ValueError(f"{location} must be a normalized relative POSIX path")
        return value

    def _decode_workspace_files(
        self, value: object, *, location: str
    ) -> list[dict[str, object]]:
        if type(value) is not list or not value or len(value) > MAX_WORKSPACE_FILES:
            raise ValueError(
                f"{location} must contain from 1 through {MAX_WORKSPACE_FILES} files"
            )
        files: list[dict[str, object]] = []
        seen: set[str] = set()
        total = 0
        for index, raw in enumerate(value):
            item_location = f"{location}[{index}]"
            if type(raw) is not dict or set(raw) != {
                "content_base64",
                "executable",
                "path",
            }:
                raise ValueError(f"{item_location} is malformed")
            path = self._workspace_path(raw["path"], f"{item_location}.path")
            if path in seen:
                raise ValueError(f"{location} contains duplicate path: {path}")
            content = raw["content_base64"]
            executable = raw["executable"]
            if type(content) is not str or type(executable) is not bool:
                raise ValueError(f"{item_location} content or mode is malformed")
            try:
                decoded = base64.b64decode(content, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{item_location}.content_base64 is invalid") from exc
            if base64.b64encode(decoded).decode("ascii") != content:
                raise ValueError(f"{item_location}.content_base64 is not canonical")
            total += len(decoded)
            if total > MAX_WORKSPACE_BYTES:
                raise ValueError("workspace exceeds the global byte limit")
            seen.add(path)
            files.append(
                {
                    "content": decoded,
                    "content_base64": content,
                    "executable": executable,
                    "path": path,
                }
            )
        if [str(item["path"]) for item in files] != sorted(seen):
            raise ValueError(f"{location} must be sorted by path")
        return files

    @staticmethod
    def _allowed(path: str, prefixes: list[str]) -> bool:
        return any(
            path == prefix or path.startswith(prefix.rstrip("/") + "/")
            for prefix in prefixes
        )

    def _decode_workspace_policy(self, value: object) -> dict[str, object]:
        if type(value) is not dict or set(value) != {
            "allowed_write_paths",
            "command_timeout_ms",
            "max_bytes",
            "max_files",
            "max_output_characters",
        }:
            raise ValueError("workspace policy is malformed")
        paths = value["allowed_write_paths"]
        if type(paths) is not list or not paths or len(paths) > MAX_WORKSPACE_FILES:
            raise ValueError("workspace allowed_write_paths must be non-empty")
        normalized_paths: list[str] = []
        for index, raw in enumerate(paths):
            path = self._workspace_path(
                raw, f"workspace policy.allowed_write_paths[{index}]"
            )
            if path in normalized_paths:
                raise ValueError("workspace allowed_write_paths contains a duplicate")
            normalized_paths.append(path)
        if normalized_paths != sorted(normalized_paths):
            raise ValueError("workspace allowed_write_paths must be sorted")
        maximum_files = value["max_files"]
        maximum_bytes = value["max_bytes"]
        timeout = value["command_timeout_ms"]
        maximum_output = value["max_output_characters"]
        if (
            type(maximum_files) is not int
            or not 1 <= maximum_files <= MAX_WORKSPACE_FILES
        ):
            raise ValueError("workspace max_files is outside the supported range")
        if (
            type(maximum_bytes) is not int
            or not 1 <= maximum_bytes <= MAX_WORKSPACE_BYTES
        ):
            raise ValueError("workspace max_bytes is outside the supported range")
        if type(timeout) is not int or not 10 <= timeout <= 3_600_000:
            raise ValueError(
                "workspace command_timeout_ms is outside the supported range"
            )
        if (
            type(maximum_output) is not int
            or not 128 <= maximum_output <= MAX_CAPTURE_CHARACTERS
        ):
            raise ValueError(
                "workspace max_output_characters is outside the supported range"
            )
        return {
            "allowed_write_paths": normalized_paths,
            "command_timeout_ms": timeout,
            "max_bytes": maximum_bytes,
            "max_files": maximum_files,
            "max_output_characters": maximum_output,
        }

    def _remove_workspace(self) -> None:
        if WORKSPACE_ROOT.exists():
            if WORKSPACE_ROOT.is_symlink() or not WORKSPACE_ROOT.is_dir():
                raise ValueError("workspace root is unsafe")
            shutil.rmtree(WORKSPACE_ROOT)

    def _install_workspace_helpers(self) -> None:
        namespace = self.engine.namespace

        def resolve(relative: object) -> Path:
            path = self._workspace_path(relative, "workspace path")
            target = WORKSPACE_ROOT.joinpath(*PurePosixPath(path).parts)
            if target.is_symlink():
                raise ValueError(f"workspace path may not be a symlink: {path}")
            return target

        def list_files() -> list[str]:
            return [str(item["path"]) for item in self._workspace_files()]

        def read_file(relative: object) -> str:
            path = resolve(relative)
            if not path.is_file():
                raise ValueError(f"workspace file does not exist: {relative}")
            return path.read_text(encoding="utf-8")

        def write_file(relative: object, content: object) -> None:
            path_text = self._workspace_path(relative, "workspace path")
            policy = self.workspace_policy
            if policy is None or not self._allowed(
                path_text,
                policy["allowed_write_paths"],  # type: ignore[arg-type]
            ):
                raise ValueError(f"workspace path is not writable: {path_text}")
            if type(content) is not str or "\x00" in content:
                raise ValueError("workspace text must not contain NUL")
            path = resolve(path_text)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="")

        def delete_file(relative: object) -> None:
            path_text = self._workspace_path(relative, "workspace path")
            policy = self.workspace_policy
            if policy is None or not self._allowed(
                path_text,
                policy["allowed_write_paths"],  # type: ignore[arg-type]
            ):
                raise ValueError(f"workspace path is not writable: {path_text}")
            path = resolve(path_text)
            if path.is_dir():
                raise ValueError("delete_file accepts only regular files")
            path.unlink(missing_ok=True)

        def search_files(
            pattern: object, relative: object = ""
        ) -> list[dict[str, object]]:
            if type(pattern) is not str or not pattern or "\x00" in pattern:
                raise ValueError("search pattern must be non-empty text")
            try:
                expression = re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid search pattern: {exc}") from exc
            prefix = (
                "" if relative == "" else self._workspace_path(relative, "search path")
            )
            results: list[dict[str, object]] = []
            for item in self._workspace_files():
                path_text = str(item["path"])
                if prefix and not (
                    path_text == prefix
                    or path_text.startswith(prefix.rstrip("/") + "/")
                ):
                    continue
                try:
                    text = base64.b64decode(
                        str(item["content_base64"]), validate=True
                    ).decode("utf-8")
                except UnicodeDecodeError:
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if expression.search(line):
                        results.append(
                            {
                                "line": line[:1000],
                                "line_number": line_number,
                                "path": path_text,
                            }
                        )
                        if len(results) >= 200:
                            return results
            return results

        namespace.update(
            {
                "delete_file": delete_file,
                "list_files": list_files,
                "read_file": read_file,
                "run_command": self._run_workspace_command,
                "search_files": search_files,
                "workspace_root": str(WORKSPACE_ROOT),
                "write_file": write_file,
            }
        )

    def _workspace_init(self, request: dict[str, object]) -> dict[str, object]:
        if set(request) != {"files", "id", "operation", "policy"}:
            raise ValueError("workspace_init request has the wrong keys")
        files = self._decode_workspace_files(
            request["files"], location="workspace files"
        )
        policy = self._decode_workspace_policy(request["policy"])
        if len(files) > int(policy["max_files"]):
            raise ValueError("workspace exceeds policy max_files")
        total = sum(len(item["content"]) for item in files)  # type: ignore[arg-type]
        if total > int(policy["max_bytes"]):
            raise ValueError("workspace exceeds policy max_bytes")
        self._remove_workspace()
        WORKSPACE_ROOT.mkdir(mode=0o700, parents=True)
        baseline: dict[str, tuple[str, bool]] = {}
        for item in files:
            path_text = str(item["path"])
            destination = WORKSPACE_ROOT.joinpath(*PurePosixPath(path_text).parts)
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            content = item["content"]
            assert type(content) is bytes
            destination.write_bytes(content)
            executable = bool(item["executable"])
            destination.chmod(0o700 if executable else 0o600)
            baseline[path_text] = (hashlib.sha256(content).hexdigest(), executable)
        self.workspace_policy = policy
        self.workspace_baseline = baseline
        os.chdir(WORKSPACE_ROOT)
        self._install_workspace_helpers()
        exported = self._workspace_export_document()
        return {
            "file_count": len(files),
            "sha256": exported["sha256"],
            "total_bytes": total,
        }

    def _workspace_files(self) -> list[dict[str, object]]:
        if (
            self.workspace_policy is None
            or not WORKSPACE_ROOT.is_dir()
            or WORKSPACE_ROOT.is_symlink()
        ):
            raise ValueError("workspace is not initialized")
        files: list[dict[str, object]] = []
        total = 0
        for path in sorted(WORKSPACE_ROOT.rglob("*")):
            relative = path.relative_to(WORKSPACE_ROOT).as_posix()
            self._workspace_path(relative, "workspace entry")
            if path.is_symlink():
                raise ValueError(f"workspace contains a symlink: {relative}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError(f"workspace contains a non-regular entry: {relative}")
            content = path.read_bytes()
            total += len(content)
            if len(files) >= int(self.workspace_policy["max_files"]):
                raise ValueError("workspace exceeds policy max_files")
            if total > int(self.workspace_policy["max_bytes"]):
                raise ValueError("workspace exceeds policy max_bytes")
            files.append(
                {
                    "content_base64": base64.b64encode(content).decode("ascii"),
                    "executable": bool(path.stat().st_mode & 0o111),
                    "path": relative,
                }
            )
        if not files:
            raise ValueError("workspace must contain at least one file")
        return files

    def _workspace_export_document(self) -> dict[str, object]:
        files = self._workspace_files()
        current = {
            str(item["path"]): (
                hashlib.sha256(
                    base64.b64decode(str(item["content_base64"]), validate=True)
                ).hexdigest(),
                bool(item["executable"]),
            )
            for item in files
        }
        changed = sorted(
            path
            for path in set(self.workspace_baseline) | set(current)
            if self.workspace_baseline.get(path) != current.get(path)
        )
        policy = self.workspace_policy
        assert policy is not None
        for path in changed:
            if not self._allowed(path, policy["allowed_write_paths"]):  # type: ignore[arg-type]
                raise ValueError(f"workspace changed disallowed path: {path}")
        body = {"changed_paths": changed, "files": files}
        return {**body, "sha256": _digest(body)}

    def _workspace_export(self, request: dict[str, object]) -> dict[str, object]:
        if set(request) != {"id", "operation"}:
            raise ValueError("workspace_export request has the wrong keys")
        return self._workspace_export_document()

    def _run_workspace_command(
        self, argv: object, timeout_ms: object | None = None
    ) -> dict[str, object]:
        if self.workspace_policy is None:
            raise ValueError("workspace is not initialized")
        if (
            type(argv) is not list
            or not argv
            or any(type(item) is not str or not item or "\x00" in item for item in argv)
        ):
            raise ValueError("workspace command must be a non-empty string array")
        maximum_timeout = int(self.workspace_policy["command_timeout_ms"])
        effective_timeout = maximum_timeout if timeout_ms is None else timeout_ms
        if (
            type(effective_timeout) is not int
            or not 1 <= effective_timeout <= maximum_timeout
        ):
            raise ValueError("workspace command timeout exceeds policy")
        try:
            process = subprocess.Popen(
                argv,
                cwd=WORKSPACE_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
        except OSError as exc:
            return {
                "returncode": None,
                "stderr": _bounded_text(str(exc)),
                "stdout": "",
                "timed_out": False,
            }
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=effective_timeout / 1000)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        maximum_output = int(self.workspace_policy["max_output_characters"])

        def bounded(value: str) -> str:
            if len(value) <= maximum_output:
                return value
            digest = hashlib.sha256(
                value.encode("utf-8", errors="surrogatepass")
            ).hexdigest()
            marker = f"...[truncated;sha256:{digest}]"
            return value[: maximum_output - len(marker)] + marker

        return {
            "returncode": process.returncode,
            "stderr": bounded(stderr),
            "stdout": bounded(stdout),
            "timed_out": timed_out,
        }

    def _workspace_run(self, request: dict[str, object]) -> dict[str, object]:
        if set(request) != {"argv", "id", "operation", "timeout_ms"}:
            raise ValueError("workspace_run request has the wrong keys")
        return self._run_workspace_command(request["argv"], request["timeout_ms"])

    def _snapshot(self, request: dict[str, object]) -> dict[str, object]:
        if set(request) != {"id", "operation"}:
            raise ValueError("snapshot request has the wrong keys")
        names = self.snapshot_policy.get("allowed_names")
        maximum = self.snapshot_policy.get("max_bytes")
        if type(names) is not list or type(maximum) is not int:
            raise ValueError("snapshot policy is malformed")
        values: dict[str, object] = {}
        for name in names:
            if type(name) is not str:
                raise ValueError("snapshot policy name is malformed")
            if name in self.engine.namespace:
                try:
                    values[name] = _json_safe(self.engine.namespace[name])
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"snapshot name is not canonical JSON: {name}"
                    ) from exc
        snapshot = {"values": values}
        source = _canonical(snapshot).encode("ascii")
        if len(source) > maximum:
            raise ValueError("snapshot exceeds candidate policy max_bytes")
        return {"sha256": hashlib.sha256(source).hexdigest(), "values": values}

    def _restore(self, request: dict[str, object]) -> dict[str, object]:
        if set(request) != {"id", "operation", "snapshot"}:
            raise ValueError("restore request has the wrong keys")
        snapshot = request["snapshot"]
        if type(snapshot) is not dict or set(snapshot) != {"sha256", "values"}:
            raise ValueError("restore snapshot is malformed")
        values = snapshot["values"]
        if type(values) is not dict:
            raise ValueError("restore snapshot values are malformed")
        expected = _digest({"values": values})
        if snapshot["sha256"] != expected:
            raise ValueError("restore snapshot digest does not match")
        allowed = self.snapshot_policy.get("allowed_names")
        if type(allowed) is not list or any(name not in allowed for name in values):
            raise ValueError("restore snapshot contains a disallowed name")
        normalized = _json_safe(values)
        assert type(normalized) is dict
        self.engine.namespace.update(normalized)
        return {"sha256": expected}

    def _cleanup(self, request: dict[str, object]) -> dict[str, object]:
        if set(request) != {"id", "operation"}:
            raise ValueError("cleanup request has the wrong keys")
        os.chdir("/tmp")
        self._remove_workspace()
        self.workspace_policy = None
        self.workspace_baseline = {}
        self.engine.reset()
        self._capture(lambda: self.engine.execute(self.bootstrap))
        return {"clean": True}

    def dispatch(self, request: dict[str, object]) -> tuple[dict[str, object], bool]:
        request_id = request.get("id")
        if type(request_id) is not int or request_id < 1:
            return _error(
                request_id, "invalid_request", "id must be a positive integer"
            ), False
        operation = request.get("operation")
        if operation == "boot":
            try:
                return _success(request_id, self._boot(request)), False
            except KeyboardInterrupt:
                return _error(
                    request_id, "interrupted", "kernel boot was interrupted"
                ), False
            except BaseException as exc:
                return _error(request_id, "boot_failed", _exception_message(exc)), False
        if not self.booted:
            return _error(
                request_id, "not_booted", "kernel must be booted first"
            ), False
        try:
            if operation == "execute":
                result = self._execute(request)
            elif operation == "workspace_init":
                result = self._workspace_init(request)
            elif operation == "workspace_export":
                result = self._workspace_export(request)
            elif operation == "workspace_run":
                result = self._workspace_run(request)
            elif operation == "snapshot":
                result = self._snapshot(request)
            elif operation == "restore":
                result = self._restore(request)
            elif operation == "cleanup":
                result = self._cleanup(request)
            elif operation == "ping":
                if set(request) != {"id", "operation"}:
                    raise ValueError("ping request has the wrong keys")
                result = {"engine": self.engine.name}
            elif operation == "shutdown":
                if set(request) != {"id", "operation"}:
                    raise ValueError("shutdown request has the wrong keys")
                os.chdir("/tmp")
                self._remove_workspace()
                return _success(request_id, {"shutdown": True}), True
            else:
                return _error(
                    request_id, "invalid_request", "unsupported operation"
                ), False
            return _success(request_id, result), False
        except KeyboardInterrupt:
            return _error(
                request_id, "interrupted", "kernel execution was interrupted"
            ), False
        except BaseException as exc:
            return _error(request_id, "execution_error", _exception_message(exc)), False


def _exception_message(exc: BaseException) -> str:
    text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return text or type(exc).__name__


def _engine(name: str) -> FixtureEngine | IPythonEngine:
    if name == "fixture":
        return FixtureEngine()
    return IPythonEngine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("fixture", "ipython"), required=True)
    arguments = parser.parse_args(argv)
    try:
        server = KernelServer(_engine(arguments.engine))
    except BaseException as exc:
        print(
            _canonical(_error(None, "startup_failed", _exception_message(exc))),
            flush=True,
        )
        return 2
    for raw_line in sys.stdin.buffer:
        if len(raw_line) > MAX_REQUEST_BYTES:
            response = _error(None, "invalid_request", "request exceeds wire limit")
            print(_canonical(response), flush=True)
            continue
        try:
            source = raw_line.decode("utf-8")
            request = json.loads(source)
            if type(request) is not dict:
                raise ValueError("request must be a JSON object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            print(_canonical(_error(None, "invalid_request", str(exc))), flush=True)
            continue
        response, shutdown = server.dispatch(request)
        try:
            print(_canonical(response), flush=True)
        except (TypeError, ValueError):
            print(
                _canonical(
                    _error(
                        request.get("id"), "serialization_error", "result is not JSON"
                    )
                ),
                flush=True,
            )
        if shutdown:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
