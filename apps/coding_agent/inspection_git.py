"""Bounded byte-exact Git reads for operator inspection, never candidate execution."""

from __future__ import annotations

import hashlib
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path

from apps._support.process import kill_process_tree
from apps.coding_agent.operator_view import OperatorViewError


def object_digest(kind: str, data: bytes, oid: str) -> str:
    return hashlib.new(
        "sha1" if len(oid) == 40 else "sha256", f"{kind} {len(data)}\0".encode() + data
    ).hexdigest()


def git_bytes(
    repository: Path,
    arguments: list[str | bytes],
    *,
    limit: int,
    timeout: float = 5,
    input_bytes: bytes | None = None,
) -> bytes:
    if repository.is_symlink() or not repository.is_dir():
        raise OperatorViewError("candidate Git repository is absent or unsafe")
    git = shutil.which("git")
    if git is None:
        raise OperatorViewError("Git is unavailable")
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_ATTR_NOSYSTEM="1",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_ALLOW_PROTOCOL="",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
        LC_ALL="C.UTF-8",
    )
    process = None
    try:
        process = subprocess.Popen(
            [
                git,
                "--git-dir",
                str(repository),
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "color.ui=false",
                *arguments,
            ],
            cwd=repository.parent,
            env=environment,
            stdin=subprocess.PIPE if input_bytes else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        buffers = {"out": bytearray(), "err": bytearray()}
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            pending = memoryview(input_bytes or b"")
            if pending and process.stdin is not None:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "in")
            for name, stream in (("out", process.stdout), ("err", process.stderr)):
                assert stream is not None
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OperatorViewError("Git inspection exceeded its time bound")
                for key, _event in selector.select(remaining):
                    if key.data == "in":
                        try:
                            pending = pending[os.write(key.fd, pending[:65536]) :]
                        except BrokenPipeError:
                            pending = memoryview(b"")
                        except BlockingIOError:
                            continue
                        if not pending:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                        continue
                    buffer = buffers[key.data]
                    bound = limit if key.data == "out" else 65536
                    data = os.read(key.fd, min(65536, bound - len(buffer) + 1))
                    if not data:
                        selector.unregister(key.fileobj)
                    elif len(buffer) + len(data) > bound:
                        raise OperatorViewError(
                            "Git inspection exceeded its byte bound"
                        )
                    else:
                        buffer.extend(data)
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
        if process.returncode:
            # Do not echo arbitrary repository-controlled diagnostics into an HTML response.
            raise OperatorViewError("Git could not read the bound candidate object")
        return bytes(buffers["out"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperatorViewError(f"Git inspection failed: {type(exc).__name__}") from exc
    finally:
        if process is not None:
            kill_process_tree(process)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
