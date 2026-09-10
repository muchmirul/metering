"""Bounded binary pipe transport for the POSIX model runtime, without policy."""

from __future__ import annotations

import os
import selectors
import subprocess
import time
from collections.abc import Callable

from apps._support.process import kill_process_tree


class OutputLimitError(RuntimeError):
    """An owned subprocess exceeded an existing per-stream byte limit."""

    def __init__(self, stream: str) -> None:
        super().__init__(f"{stream} exceeded its output byte limit")
        self.stream = stream


def communicate_bounded(
    process: subprocess.Popen[bytes],
    source: bytes | None,
    *,
    timeout_seconds: float,
    max_output_bytes: int,
    stdout_line_filter: Callable[[bytes], bytes | None] | None = None,
) -> tuple[str, str]:
    """Drain both outputs and feed stdin concurrently; never buffer beyond caps.

    The caller creates binary pipes. A deadline covers input, output and exit,
    including inherited pipes held open by descendants. Cleanup also runs on
    cancellation and malformed UTF-8. Owned process groups are reaped on every
    path. Nested provider clients stay in the outer transport's process group.

    By default, each complete stream is capped. A trusted line filter may discard
    stdout protocol framing while it is drained. In that mode each input line and
    the complete retained stdout are capped independently; stderr keeps the normal
    complete-stream cap. The filter cannot make an oversized line acceptable.
    """
    output = {"stdout": bytearray(), "stderr": bytearray()}
    stdout_line = bytearray()
    deadline = time.monotonic() + timeout_seconds

    def retain_stdout_line(line: bytes) -> None:
        if len(line) > max_output_bytes:
            raise OutputLimitError("stdout")
        retained = stdout_line_filter(line) if stdout_line_filter is not None else line
        if retained is None:
            return
        if type(retained) is not bytes:
            raise ValueError("stdout line filter must return bytes or None")
        if len(output["stdout"]) + len(retained) > max_output_bytes:
            raise OutputLimitError("stdout")
        output["stdout"].extend(retained)

    def consume_stdout(data: bytes, *, end: bool = False) -> None:
        stdout_line.extend(data)
        while True:
            newline = stdout_line.find(b"\n")
            if newline < 0:
                break
            line = bytes(stdout_line[: newline + 1])
            del stdout_line[: newline + 1]
            retain_stdout_line(line)
        if len(stdout_line) > max_output_bytes:
            raise OutputLimitError("stdout")
        if end and stdout_line:
            line = bytes(stdout_line)
            stdout_line.clear()
            retain_stdout_line(line)

    try:
        if os.name != "posix":
            raise ValueError("bounded model pipe transport requires POSIX")
        if max_output_bytes < 1 or timeout_seconds <= 0:
            raise ValueError("process byte and time bounds must be positive")
        with selectors.DefaultSelector() as selector:
            for name, stream in (
                ("stdout", process.stdout),
                ("stderr", process.stderr),
            ):
                if stream is None:
                    raise ValueError("bounded transport requires both output pipes")
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            pending = memoryview(source or b"")
            if process.stdin is not None:
                if pending:
                    os.set_blocking(process.stdin.fileno(), False)
                    selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
                else:
                    process.stdin.close()
            elif pending:
                raise ValueError("bounded transport requires a pipe for input")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(process.args, timeout_seconds)
                for key, _ in selector.select(remaining):
                    stream = key.fileobj
                    if key.data == "stdin":
                        try:
                            written = os.write(key.fd, pending[:65536])
                            pending = pending[written:]
                        except BrokenPipeError:
                            pending = memoryview(b"")
                        except BlockingIOError:
                            continue
                        if not pending:
                            selector.unregister(stream)
                            stream.close()
                        continue
                    buffer = output[key.data]
                    read_size = 65536
                    bounded = (
                        stdout_line
                        if key.data == "stdout" and stdout_line_filter is not None
                        else buffer
                    )
                    read_size = min(read_size, max_output_bytes - len(bounded) + 1)
                    try:
                        data = os.read(key.fd, read_size)
                    except BlockingIOError:
                        continue
                    if not data:
                        if key.data == "stdout" and stdout_line_filter is not None:
                            consume_stdout(b"", end=True)
                        selector.unregister(stream)
                        stream.close()
                    elif key.data == "stdout" and stdout_line_filter is not None:
                        consume_stdout(data)
                    elif len(buffer) + len(data) > max_output_bytes:
                        raise OutputLimitError(key.data)
                    else:
                        buffer.extend(data)
        process.wait(timeout=max(0, deadline - time.monotonic()))
        # Preserve the previous UTF-8 text transport's universal-newline behavior.
        decoded = [
            bytes(output[name])
            .decode("utf-8")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            for name in ("stdout", "stderr")
        ]
        return decoded[0], decoded[1]
    finally:
        kill_process_tree(process)
