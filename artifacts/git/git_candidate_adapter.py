"""Resolve git-candidate-v1 and delegate it to one fixed executor command.

The resolver never executes candidate source itself. The configured executor
owns container/VM isolation and verification of external output digests.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.agent_protocol import (  # noqa: E402
    GIT_ADAPTER_PROTOCOL_VERSION,
    GIT_ARTIFACT_SCHEMA,
    ProtocolError,
    decode_candidate,
    decode_task,
    require_exact_keys,
    run_adapter,
)
from apps._support.wire import (  # noqa: E402
    canonical_json,
    decode_json_object,
)

from artifacts.git.git_repository import (  # noqa: E402
    GitCandidateError,
    clone_verified,
)


class AdapterError(RuntimeError):
    """Raised when a Git candidate cannot be resolved or executed."""


def _command() -> list[str]:
    source = os.environ.get("METERING_GIT_EXECUTOR_COMMAND")
    if not source:
        raise AdapterError("METERING_GIT_EXECUTOR_COMMAND must contain JSON")
    try:
        value = json.loads(source)
    except json.JSONDecodeError as exc:
        raise AdapterError(
            f"METERING_GIT_EXECUTOR_COMMAND is invalid JSON: {exc}"
        ) from exc
    if (
        type(value) is not list
        or not value
        or any(type(item) is not str or not item or "\x00" in item for item in value)
    ):
        raise AdapterError(
            "METERING_GIT_EXECUTOR_COMMAND must be a non-empty string array"
        )
    return value


def _timeout() -> int:
    source = os.environ.get("METERING_GIT_EXECUTOR_TIMEOUT", "300")
    try:
        value = int(source)
    except ValueError as exc:
        raise AdapterError("METERING_GIT_EXECUTOR_TIMEOUT must be an integer") from exc
    if not 1 <= value <= 3600:
        raise AdapterError("METERING_GIT_EXECUTOR_TIMEOUT must be from 1 through 3600")
    return value


def _decode_request(
    source: str,
) -> tuple[dict[str, object], dict[str, object]]:
    request = decode_json_object(source, AdapterError)
    try:
        require_exact_keys(
            request, {"candidate", "protocol_version", "task"}, "request"
        )
        if (
            type(request["protocol_version"]) is not int
            or request["protocol_version"] != GIT_ADAPTER_PROTOCOL_VERSION
        ):
            raise ProtocolError("unsupported Git candidate adapter protocol")
        candidate = decode_candidate(request["candidate"], "candidate")
        artifact = cast(dict[str, object], candidate["artifact"])
        if artifact["artifact_schema"] != GIT_ARTIFACT_SCHEMA:
            raise ProtocolError("candidate must contain a git-candidate-v1 artifact")
        task = decode_task(request["task"], "task")
    except ProtocolError as exc:
        raise AdapterError(str(exc)) from exc
    return candidate, task


def execute(source: str) -> dict[str, object]:
    candidate, task = _decode_request(source)
    artifact = cast(dict[str, object], candidate["artifact"])
    with tempfile.TemporaryDirectory(prefix="metering-git-candidate-") as temporary:
        checkout = Path(temporary) / "checkout"
        try:
            artifact = clone_verified(artifact, checkout)
            response = run_adapter(
                "Git candidate executor",
                _command(),
                {
                    "candidate": {
                        "artifact": artifact,
                        "candidate_id": candidate["candidate_id"],
                        "checkout_path": str(checkout),
                    },
                    "protocol_version": 1,
                    "task": task,
                },
                timeout_seconds=_timeout(),
                cwd=ROOT,
            )
            require_exact_keys(
                response, {"forecast", "submission"}, "executor response"
            )
        except (GitCandidateError, ProtocolError) as exc:
            raise AdapterError(str(exc)) from exc
    return response


def main() -> int:
    try:
        response = execute(sys.stdin.read())
    except (
        AdapterError,
        GitCandidateError,
        ProtocolError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
