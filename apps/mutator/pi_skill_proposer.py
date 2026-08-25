"""Tool-free Pi adapter that proposes one complete replacement SKILL.md.

Mutator owns the timeout and supplies only the current parent plus caller-approved
proposal context. The adapter disables tools, discovered resources, context files,
and session persistence. For a skill parent it registers and injects the verified
SKILL.md because tool-free Pi cannot progressively read it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

APPS_ROOT = Path(__file__).resolve().parents[1]
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from agent_protocol import (  # noqa: E402
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
from stdio_connector import canonical_json, decode_json_object  # noqa: E402


class AdapterError(ValueError):
    """Raised when the proposal request or Pi response is invalid."""


def _decode_request(
    request: dict[str, object],
) -> tuple[dict[str, object], object]:
    try:
        require_exact_keys(request, {"context", "parent", "protocol_version"}, "request")
        if request["protocol_version"] != ADAPTER_PROTOCOL_VERSION or type(
            request["protocol_version"]
        ) is not int:
            raise ProtocolError("unsupported proposal adapter protocol")
        parent = decode_candidate(request["parent"], "parent")
        context = normalize_json_value(request["context"], "context")
    except ProtocolError as exc:
        raise AdapterError(str(exc)) from exc
    return parent, context


def _proposal_prompt(context: object) -> str:
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


def _pi_command(skill_file: Path | None, prompt: str) -> list[str]:
    command = [
        os.environ.get("PI_BIN", "pi"),
        "--no-session",
        "--no-skills",
        "--no-extensions",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--no-tools",
    ]
    if skill_file is not None:
        try:
            skill_text = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise AdapterError(f"cannot read parent SKILL.md: {exc}") from exc
        if not skill_text or "\x00" in skill_text:
            raise AdapterError(
                "parent SKILL.md must be non-empty UTF-8 text without NUL"
            )
        instructions = (
            "The following is the complete, caller-selected current skill. Apply "
            "its useful instructions while proposing one replacement.\n\n"
            f"<current_skill path={canonical_json(str(skill_file))}>\n"
            f"{skill_text}\n"
            "</current_skill>"
        )
        command.extend(
            [
                "--skill",
                str(skill_file),
                "--append-system-prompt",
                instructions,
            ]
        )
    command.extend(["-p", prompt])
    return command


def _run_pi(command: list[str]) -> dict[str, object]:
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
        detail = completed.stderr.strip() or f"Pi exited with {completed.returncode}"
        raise AdapterError(detail)
    if completed.stderr:
        raise AdapterError("Pi wrote unexpected standard error")
    return decode_json_object(completed.stdout, AdapterError)


def _validate_response(response: dict[str, object]) -> dict[str, object]:
    try:
        require_exact_keys(
            response,
            {"challenger_artifact", "reason"},
            "Pi response",
        )
        artifact = decode_agent_artifact(
            response["challenger_artifact"],
            "Pi response.challenger_artifact",
        )
        reason = require_nonempty_string(response["reason"], "Pi response.reason")
    except ProtocolError as exc:
        raise AdapterError(str(exc)) from exc
    files = cast(list[dict[str, object]], artifact.get("files", []))
    if len(files) != 1 or files[0]["path"] != "SKILL.md":
        raise AdapterError(
            "Pi response.challenger_artifact must contain exactly one SKILL.md file"
        )
    if files[0]["executable"] is not False:
        raise AdapterError("Pi response SKILL.md must not be executable")
    return {"challenger_artifact": artifact, "reason": reason}


def propose(parent: dict[str, object], context: object) -> dict[str, object]:
    artifact = cast(dict[str, object], parent["artifact"])
    with tempfile.TemporaryDirectory(prefix="metering-pi-proposer-") as temp:
        if artifact["artifact_schema"] == DEFAULT_ARTIFACT_SCHEMA:
            skill_file = None
        else:
            root = Path(temp) / "skill"
            materialize_skill(artifact, root)
            skill_file = root / "SKILL.md"
        response = _run_pi(_pi_command(skill_file, _proposal_prompt(context)))
    return _validate_response(response)


def main() -> int:
    try:
        request = decode_json_object(sys.stdin.read(), AdapterError)
        parent, context = _decode_request(request)
        response = propose(parent, context)
    except (AdapterError, ProtocolError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
