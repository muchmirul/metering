#!/usr/bin/env python3
"""Persistent JSON-lines kernel server used only inside a reviewed sandbox.

The module is intentionally standalone so the OCI image can copy this one file.
Candidate bootstrap and cells execute in this process, never in the host runner.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import sys
import traceback
from collections.abc import Callable
from typing import Any

SERVER_PROTOCOL = "harness-kernel-wire-v1"
MAX_REQUEST_BYTES = 2_097_152
MAX_CAPTURE_CHARACTERS = 65_536


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
