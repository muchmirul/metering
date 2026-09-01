"""Bounded canonical-JSON subprocess effects for source-only applications."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Literal, TypeAlias

from .wire import JsonDocument, canonical_json

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
