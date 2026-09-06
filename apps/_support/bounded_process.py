"""Bounded binary pipe transport for the POSIX model runtime, without policy."""

from __future__ import annotations

import os
import selectors
import subprocess
import time

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
) -> tuple[str, str]:
    """Drain both outputs and feed stdin concurrently; never buffer beyond caps.

    The caller creates binary pipes. A deadline covers input, output and exit,
    including inherited pipes held open by descendants. Cleanup also runs on
    cancellation and malformed UTF-8. Owned process groups are reaped on every
    path. Nested provider clients stay in the outer transport's process group.
    """
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout_seconds
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
                    try:
                        data = os.read(
                            key.fd, min(65536, max_output_bytes - len(buffer) + 1)
                        )
                    except BlockingIOError:
                        continue
                    if not data:
                        selector.unregister(stream)
                        stream.close()
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
