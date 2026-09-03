"""Shared strict protocol mechanics for concrete fixed skill proposers."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

from apps.agent_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    DEFAULT_ARTIFACT_SCHEMA,
    ProtocolError,
    decode_agent_artifact,
    decode_candidate,
    materialize_skill,
    normalize_json_value,
    require_exact_keys,
    require_nonempty_string,
)
from apps._support.wire import (
    canonical_json,
    decode_json_object,
)

ROOT = Path(__file__).resolve().parents[2]

CommandBuilder = Callable[[Path | None, str], list[str]]


class AdapterError(ValueError):
    """Raised when a proposal request or agent response is invalid."""


def _decode_request(
    request: dict[str, object],
) -> tuple[dict[str, object], object]:
    try:
        require_exact_keys(
            request,
            {"context", "parent", "protocol_version"},
            "request",
        )
        if (
            request["protocol_version"] != ADAPTER_PROTOCOL_VERSION
            or type(request["protocol_version"]) is not int
        ):
            raise ProtocolError("unsupported proposal adapter protocol")
        parent = decode_candidate(request["parent"], "parent")
        context = normalize_json_value(request["context"], "context")
    except ProtocolError as exc:
        raise AdapterError(str(exc)) from exc
    return parent, context


def proposal_prompt(context: object) -> str:
    """Build the exact agent-neutral proposal instruction."""

    contract = {
        "challenger_artifact": {
            "artifact_schema": "agent-skill-v1",
            "files": [
                {
                    "content": "COMPLETE_REPLACEMENT_SKILL_MD",
                    "executable": False,
                    "path": "SKILL.md",
                }
            ],
        },
        "reason": "SHORT_EVIDENCE_BOUND_REASON",
    }
    return (
        "Propose one bounded revision of your current candidate skill using only "
        "the caller-approved context below. Return exactly one JSON object and no "
        "Markdown. Return the complete replacement SKILL.md, not a patch. The "
        "artifact must contain exactly one non-executable file named SKILL.md. "
        "Do not claim that the revision improved; a separate evaluator decides.\n\n"
        f"Required response shape: {canonical_json(contract)}\n"
        f"Caller-approved context: {canonical_json(context)}"
    )


def _run_agent(command: list[str], agent_name: str) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AdapterError(str(exc) or type(exc).__name__) from exc
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or f"{agent_name} exited with {completed.returncode}"
        )
        raise AdapterError(detail)
    if completed.stderr:
        raise AdapterError(f"{agent_name} wrote unexpected standard error")
    return decode_json_object(completed.stdout, AdapterError)


def _validate_response(
    response: dict[str, object], agent_name: str
) -> dict[str, object]:
    location = f"{agent_name} response"
    try:
        require_exact_keys(
            response,
            {"challenger_artifact", "reason"},
            location,
        )
        artifact = decode_agent_artifact(
            response["challenger_artifact"],
            f"{location}.challenger_artifact",
        )
        reason = require_nonempty_string(response["reason"], f"{location}.reason")
    except ProtocolError as exc:
        raise AdapterError(str(exc)) from exc
    files = cast(list[dict[str, object]], artifact.get("files", []))
    if len(files) != 1 or files[0]["path"] != "SKILL.md":
        raise AdapterError(
            f"{location}.challenger_artifact must contain exactly one SKILL.md file"
        )
    if files[0]["executable"] is not False:
        raise AdapterError(f"{location} SKILL.md must not be executable")
    return {"challenger_artifact": artifact, "reason": reason}


def propose(
    parent: dict[str, object],
    context: object,
    *,
    agent_name: str,
    command_builder: CommandBuilder,
    temporary_prefix: str,
) -> dict[str, object]:
    artifact = cast(dict[str, object], parent["artifact"])
    with tempfile.TemporaryDirectory(prefix=temporary_prefix) as temp:
        if artifact["artifact_schema"] == DEFAULT_ARTIFACT_SCHEMA:
            skill_file = None
        else:
            root = Path(temp) / "skill"
            materialize_skill(artifact, root)
            skill_file = root / "SKILL.md"
        response = _run_agent(
            command_builder(skill_file, proposal_prompt(context)),
            agent_name,
        )
    return _validate_response(response, agent_name)


def run_main(
    *,
    agent_name: str,
    command_builder: CommandBuilder,
    temporary_prefix: str,
) -> int:
    try:
        request = decode_json_object(sys.stdin.read(), AdapterError)
        parent, context = _decode_request(request)
        response = propose(
            parent,
            context,
            agent_name=agent_name,
            command_builder=command_builder,
            temporary_prefix=temporary_prefix,
        )
    except (AdapterError, ProtocolError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0
