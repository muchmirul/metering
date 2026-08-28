"""Schema-v2 agent-artifact mutation and proposer execution."""

from __future__ import annotations

from pathlib import Path

from agent_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    AGENT_SCHEMA_VERSION,
    CANDIDATE_SCHEMA,
    DEFAULT_ARTIFACT_SCHEMA,
    GIT_ARTIFACT_SCHEMA,
    ProtocolError,
    candidate_record,
    changed_artifact_paths,
    decode_command,
    normalize_json_value,
    require_exact_keys,
    require_nonempty_string,
    require_schema_version,
    require_timeout,
    run_adapter,
)
from stdio_connector import canonical_digest

ROOT = Path(__file__).resolve().parents[2]


class AgentMutationError(ValueError):
    """Raised when a schema-v2 mutation request violates its contract."""


def mutate_skill_artifact(request: dict[str, object]) -> dict[str, object]:
    try:
        require_exact_keys(
            request,
            {
                "schema_version",
                "parent_artifact",
                "challenger_artifact",
                "proposal",
            },
            "request",
        )
        require_schema_version(request["schema_version"])
        proposal = request["proposal"]
        if type(proposal) is not dict:
            raise ProtocolError("proposal must be a JSON object")
        require_exact_keys(proposal, {"producer", "reason"}, "proposal")
        producer = require_nonempty_string(proposal["producer"], "proposal.producer")
        reason = require_nonempty_string(proposal["reason"], "proposal.reason")
        parent = candidate_record(request["parent_artifact"], "parent_artifact")
        challenger = candidate_record(
            request["challenger_artifact"], "challenger_artifact"
        )
        changed_paths = changed_artifact_paths(parent, challenger)
    except ProtocolError as exc:
        raise AgentMutationError(str(exc)) from exc
    if not changed_paths:
        raise AgentMutationError("challenger_artifact must differ from parent_artifact")

    proposal_id = canonical_digest(
        {
            "challenger_candidate_id": challenger["candidate_id"],
            "parent_candidate_id": parent["candidate_id"],
            "producer": producer,
            "reason": reason,
            "schema_version": AGENT_SCHEMA_VERSION,
        }
    )
    return {
        "candidate_schema": CANDIDATE_SCHEMA,
        "child": challenger,
        "mutation": {
            "changed_paths": changed_paths,
            "producer": producer,
            "proposal_id": proposal_id,
            "reason": reason,
        },
        "parent": parent,
        "schema_version": AGENT_SCHEMA_VERSION,
    }


def _require_proposable_candidate(
    candidate: dict[str, object], location: str, *, allow_default: bool
) -> None:
    artifact = candidate["artifact"]
    assert type(artifact) is dict
    artifact_schema = artifact["artifact_schema"]
    if artifact_schema == DEFAULT_ARTIFACT_SCHEMA:
        if allow_default:
            return
        raise AgentMutationError(
            f"{location} must be an agent-skill-v1 or git-candidate-v1 artifact"
        )
    if artifact_schema == GIT_ARTIFACT_SCHEMA:
        return
    files = artifact["files"]
    if type(files) is not list or len(files) != 1 or files[0].get("path") != "SKILL.md":
        raise AgentMutationError(
            f"{location} must contain exactly one SKILL.md file for proposal"
        )


def propose_skill_artifact(request: dict[str, object]) -> dict[str, object]:
    try:
        require_exact_keys(
            request,
            {
                "schema_version",
                "parent_artifact",
                "proposal_context",
                "proposer",
            },
            "request",
        )
        require_schema_version(request["schema_version"])
        parent = candidate_record(request["parent_artifact"], "parent_artifact")
        _require_proposable_candidate(parent, "parent_artifact", allow_default=True)
        context = normalize_json_value(request["proposal_context"], "proposal_context")
        proposer = request["proposer"]
        if type(proposer) is not dict:
            raise ProtocolError("proposer must be a JSON object")
        require_exact_keys(proposer, {"command", "timeout_seconds"}, "proposer")
        command = decode_command(proposer["command"], "proposer.command")
        timeout = require_timeout(
            proposer["timeout_seconds"], "proposer.timeout_seconds"
        )
        response = run_adapter(
            "proposal adapter",
            command,
            {
                "context": context,
                "parent": parent,
                "protocol_version": ADAPTER_PROTOCOL_VERSION,
            },
            timeout_seconds=timeout,
            cwd=ROOT,
        )
        require_exact_keys(
            response,
            {"challenger_artifact", "reason"},
            "proposal adapter response",
        )
        challenger = candidate_record(
            response["challenger_artifact"],
            "proposal adapter response.challenger_artifact",
        )
        _require_proposable_candidate(
            challenger,
            "proposal adapter response.challenger_artifact",
            allow_default=False,
        )
        reason = require_nonempty_string(
            response["reason"], "proposal adapter response.reason"
        )
    except ProtocolError as exc:
        raise AgentMutationError(str(exc)) from exc

    return mutate_skill_artifact(
        {
            "challenger_artifact": challenger["artifact"],
            "parent_artifact": parent["artifact"],
            "proposal": {
                "producer": canonical_digest({"command": command}),
                "reason": reason,
            },
            "schema_version": AGENT_SCHEMA_VERSION,
        }
    )
