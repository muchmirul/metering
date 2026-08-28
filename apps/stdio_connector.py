"""Shared canonical-JSON standard-stream transport for source applications.

This module owns transport mechanics only. Applications still own request
validation, domain policy, and the mapping from their exceptions to protocol
error codes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, TextIO, TypeAlias

JsonDocument: TypeAlias = dict[str, object]
Processor: TypeAlias = Callable[[str], JsonDocument]
NumberParser: TypeAlias = Callable[[str], object]
ExceptionType: TypeAlias = type[Exception] | tuple[type[Exception], ...]
ErrorRule: TypeAlias = tuple[ExceptionType, str]
ErrorResult: TypeAlias = tuple[str, str]
UnexpectedError: TypeAlias = Callable[[Exception], ErrorResult]
ProcessErrorKind: TypeAlias = Literal["timeout", "start", "exit", "stderr"]


class JsonProcessError(RuntimeError):
    """Describe a one-shot JSON subprocess transport failure."""

    def __init__(
        self,
        kind: ProcessErrorKind,
        *,
        detail: str = "",
        returncode: int | None = None,
        stderr: str = "",
    ) -> None:
        super().__init__(kind)
        self.kind = kind
        self.detail = detail
        self.returncode = returncode
        self.stderr = stderr


def canonical_json(value: object) -> str:
    """Return the applications' canonical ASCII JSON representation."""

    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_digest(value: object) -> str:
    """Return the SHA-256 digest of canonical ASCII JSON."""

    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def strict_json_float(token: str) -> float:
    """Convert one JSON decimal token without changing zero/one membership."""

    try:
        exact = Decimal(token)
        converted = float(token)
    except (InvalidOperation, OverflowError, ValueError) as error:
        raise ValueError("JSON number exceeds supported numeric limits") from error
    if not math.isfinite(converted):
        raise ValueError("JSON number is outside the finite double-precision range")
    if (converted == 0.0 and exact != 0) or (
        converted == 1.0 and exact != 1
    ):
        raise ValueError(
            "JSON number would change whether its value is zero or one "
            "in double precision"
        )
    return 0.0 if converted == 0.0 else converted


def decode_json_object(
    source: str,
    error_type: type[Exception],
    *,
    parse_float: NumberParser = strict_json_float,
    parse_int: NumberParser = int,
) -> JsonDocument:
    """Decode one strict JSON object using an application's numeric policy."""

    if not source.strip():
        raise error_type("stdin must contain one JSON object")

    def unique_object(pairs: list[tuple[str, object]]) -> JsonDocument:
        result: JsonDocument = {}
        for key, value in pairs:
            if key in result:
                raise error_type(f"duplicate key: {key}")
            result[key] = value
        return result

    def reject_non_finite(token: str) -> object:
        raise error_type(f"non-finite number is not valid JSON: {token}")

    try:
        document = json.loads(
            source,
            object_pairs_hook=unique_object,
            parse_constant=reject_non_finite,
            parse_float=parse_float,
            parse_int=parse_int,
        )
    except error_type:
        raise
    except json.JSONDecodeError as error:
        raise error_type(f"invalid JSON: {error.msg}") from error
    except (ArithmeticError, RecursionError, ValueError) as error:
        raise error_type(f"invalid JSON: {error}") from error
    if type(document) is not dict:
        raise error_type("request must be one JSON object")
    return document


def kill_process_tree(process: subprocess.Popen[str]) -> None:
    """Kill a connected process and its descendants, then reap the child."""

    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            if process.poll() is None:
                process.kill()
    elif process.poll() is None:
        process.kill()
    process.wait()
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            with suppress(OSError):
                stream.close()


def run_json_process(
    command: Sequence[str],
    request: JsonDocument,
    *,
    cwd: Path,
    timeout_seconds: int,
) -> str:
    """Call one canonical-JSON subprocess and return its standard output."""

    try:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name == "posix",
        )
    except OSError as error:
        raise JsonProcessError("start", detail=str(error)) from error

    try:
        stdout, stderr = process.communicate(
            canonical_json(request) + "\n",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        kill_process_tree(process)
        raise JsonProcessError("timeout") from error
    except BaseException:
        kill_process_tree(process)
        raise

    if process.returncode != 0:
        raise JsonProcessError(
            "exit",
            returncode=process.returncode,
            stderr=stderr,
        )
    if stderr:
        raise JsonProcessError("stderr", stderr=stderr)
    return stdout


def error_document(code: str, message: str) -> JsonDocument:
    return {"error": {"code": code, "message": message}}


def write_document(stream: TextIO, document: JsonDocument) -> None:
    stream.write(canonical_json(document) + "\n")
    stream.flush()


def _mapped_error(
    error: Exception,
    rules: Sequence[ErrorRule],
    unexpected: UnexpectedError | None,
) -> ErrorResult | None:
    for exception_type, code in rules:
        if isinstance(error, exception_type):
            return code, str(error)
    if unexpected is not None:
        return unexpected(error)
    return None


def _process_document(
    source: str,
    processor: Processor,
    error_rules: Sequence[ErrorRule],
    unexpected: UnexpectedError | None,
) -> tuple[JsonDocument, bool]:
    try:
        return processor(source), False
    except Exception as error:
        mapped = _mapped_error(error, error_rules, unexpected)
        if mapped is None:
            raise
        return error_document(*mapped), True


def _read_all(stream: TextIO) -> str:
    binary_stream = getattr(stream, "buffer", None)
    if binary_stream is None:
        return stream.read()
    return binary_stream.read().decode("utf-8")


def _run_jsonl(
    processor: Processor,
    error_rules: Sequence[ErrorRule],
    unexpected: UnexpectedError | None,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    error_stream: TextIO,
    stream_error_code: str,
) -> int:
    binary_input = getattr(input_stream, "buffer", None)
    while True:
        try:
            if binary_input is None:
                source = input_stream.readline()
                if source == "":
                    return 0
            else:
                raw = binary_input.readline()
                if raw == b"":
                    return 0
                try:
                    source = raw.decode("utf-8")
                except UnicodeDecodeError:
                    write_document(
                        output_stream,
                        error_document(
                            "invalid_request",
                            "request line must be valid UTF-8 JSON",
                        ),
                    )
                    continue
        except OSError as error:
            write_document(
                error_stream,
                error_document(
                    stream_error_code,
                    f"cannot read standard input: {error}",
                ),
            )
            return 2

        response, _ = _process_document(source, processor, error_rules, unexpected)
        write_document(output_stream, response)


def run_stdio_application(
    processor: Processor,
    argv: Sequence[str],
    *,
    error_rules: Sequence[ErrorRule],
    unexpected: UnexpectedError | None = None,
    stream_error_code: str = "invalid_request",
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    error_stream: TextIO | None = None,
) -> int:
    """Run one application over one-shot JSON or line-aligned JSONL.

    One-shot failures are emitted on standard error with exit status 2. JSONL
    request failures are emitted as aligned response documents and processing
    continues. An unreadable JSONL stream is fatal.
    """

    input_stream = sys.stdin if input_stream is None else input_stream
    output_stream = sys.stdout if output_stream is None else output_stream
    error_stream = sys.stderr if error_stream is None else error_stream

    if list(argv) == ["--jsonl"]:
        return _run_jsonl(
            processor,
            error_rules,
            unexpected,
            input_stream=input_stream,
            output_stream=output_stream,
            error_stream=error_stream,
            stream_error_code=stream_error_code,
        )
    if argv:
        write_document(
            error_stream,
            error_document(
                "invalid_request",
                "command-line arguments are not supported",
            ),
        )
        return 2

    try:
        source = _read_all(input_stream)
    except UnicodeDecodeError:
        write_document(
            error_stream,
            error_document(
                "invalid_request",
                "standard input must be valid UTF-8 JSON",
            ),
        )
        return 2
    except Exception as error:
        mapped = _mapped_error(error, error_rules, unexpected)
        if mapped is None:
            raise
        write_document(error_stream, error_document(*mapped))
        return 2

    response, failed = _process_document(source, processor, error_rules, unexpected)
    if failed:
        write_document(error_stream, response)
        return 2
    write_document(output_stream, response)
    return 0
