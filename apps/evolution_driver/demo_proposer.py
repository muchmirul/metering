"""Deterministic one-SKILL.md proposer for evolution-driver tests and examples."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.agent_protocol import (  # noqa: E402
    ADAPTER_PROTOCOL_VERSION,
    DEFAULT_ARTIFACT_SCHEMA,
    ProtocolError,
    decode_candidate,
    normalize_json_value,
    require_exact_keys,
    require_nonempty_string,
)
from apps.stdio_connector import canonical_json, decode_json_object  # noqa: E402


class ProposalError(ValueError):
    """Raised when the deterministic proposal request is malformed."""


def propose(request: dict[str, object]) -> dict[str, object]:
    try:
        require_exact_keys(
            request, {"context", "parent", "protocol_version"}, "request"
        )
        if (
            request["protocol_version"] != ADAPTER_PROTOCOL_VERSION
            or type(request["protocol_version"]) is not int
        ):
            raise ProtocolError("unsupported proposal adapter protocol")
        parent = decode_candidate(request["parent"], "parent")
        context = normalize_json_value(request["context"], "context")
        if type(context) is not dict:
            raise ProtocolError("context must be a JSON object")
        require_exact_keys(
            context,
            {"generation", "objective", "previous_generation"},
            "context",
        )
        generation = context["generation"]
        if type(generation) is not int or generation < 1:
            raise ProtocolError("context.generation must be a positive integer")
        objective = context["objective"]
        if type(objective) is not dict:
            raise ProtocolError("context.objective must be a JSON object")
        require_exact_keys(objective, {"required_text"}, "context.objective")
        required_text = require_nonempty_string(
            objective["required_text"], "context.objective.required_text"
        )
    except ProtocolError as exc:
        raise ProposalError(str(exc)) from exc

    artifact = cast(dict[str, object], parent["artifact"])
    if artifact["artifact_schema"] == DEFAULT_ARTIFACT_SCHEMA:
        skill_text = (
            "---\n"
            "name: metered-demo\n"
            "description: Deterministic bounded evolution demonstration.\n"
            "---\n\n"
            "# Metered demo\n\n"
            f"{required_text}\n"
        )
    else:
        files = cast(list[dict[str, object]], artifact["files"])
        if len(files) != 1 or files[0]["path"] != "SKILL.md":
            raise ProposalError("parent must contain exactly one SKILL.md file")
        skill_text = str(files[0]["content"])
        if not skill_text.endswith("\n"):
            skill_text += "\n"
        skill_text += f"\n<!-- metering-generation-{generation} -->\n"
        if required_text not in skill_text:
            skill_text += f"{required_text}\n"

    return {
        "challenger_artifact": {
            "artifact_schema": "agent-skill-v1",
            "files": [
                {
                    "content": skill_text,
                    "executable": False,
                    "path": "SKILL.md",
                }
            ],
        },
        "reason": f"deterministic proposal for generation {generation}",
    }


def main() -> int:
    try:
        request = decode_json_object(sys.stdin.read(), ProposalError)
        response = propose(request)
    except (ProposalError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
