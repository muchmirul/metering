"""One-shot and JSONL standard-stream execution for source applications."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from typing import TextIO, TypeAlias

from .wire import JsonDocument, error_document, write_document

Processor: TypeAlias = Callable[[str], JsonDocument]
ExceptionType: TypeAlias = type[Exception] | tuple[type[Exception], ...]
ErrorRule: TypeAlias = tuple[ExceptionType, str]
ErrorResult: TypeAlias = tuple[str, str]
UnexpectedError: TypeAlias = Callable[[Exception], ErrorResult]


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
    """Run one application over one-shot JSON or line-aligned JSONL."""

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
