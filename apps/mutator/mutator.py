"""Generate one deterministic one-locus child from an explicit mutation model."""

from __future__ import annotations

import math
import sys
from decimal import Decimal
from pathlib import Path

from metering import ProbabilityError, entropy, self_information

APPS_ROOT = Path(__file__).resolve().parents[1]
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from agent_protocol import (  # noqa: E402
    ADAPTER_PROTOCOL_VERSION,
    AGENT_SCHEMA_VERSION,
    CANDIDATE_SCHEMA,
    DEFAULT_ARTIFACT_SCHEMA,
    ProtocolError,
    candidate_record,
    changed_artifact_paths,
    decode_command,
    normalize_json_value,
    require_exact_keys,
    require_nonempty_string as require_protocol_string,
    require_schema_version,
    require_timeout,
    run_adapter,
)
from stdio_connector import (  # noqa: E402
    canonical_digest,
    canonical_json,
    decode_json_object,
    run_stdio_application,
)

SCHEMA_VERSION = 1
MAX_SAFE_INTEGER = 2**53 - 1
ROOT = Path(__file__).resolve().parents[2]


class RequestError(ValueError):
    """Raised when a mutator request does not match the application contract."""


def _decode_json(source: str) -> dict[str, object]:
    return decode_json_object(source, RequestError, parse_float=Decimal)


def _require_exact_keys(
    value: dict[str, object], expected: set[str], location: str
) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing keys: {', '.join(missing)}")
    if extra:
        details.append(f"extra keys: {', '.join(extra)}")
    if details:
        raise RequestError(f"{location}: {'; '.join(details)}")


def _require_nonempty_string(value: object, location: str) -> str:
    if type(value) is not str or not value:
        raise RequestError(f"{location} must be a non-empty string")
    return value


def _require_schema_version(value: object) -> None:
    if type(value) is not int or value != SCHEMA_VERSION:
        raise RequestError(f"schema_version must be {SCHEMA_VERSION}")


def _require_atom(value: object, location: str) -> object:
    if value is None or type(value) is bool:
        return value
    if type(value) is str:
        if not value:
            raise RequestError(f"{location} string must not be empty")
        return value
    if type(value) is int:
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise RequestError(
                f"{location} integer must be within the exact JSON range "
                f"[-{MAX_SAFE_INTEGER}, {MAX_SAFE_INTEGER}]"
            )
        return value
    if isinstance(value, Decimal):
        raise RequestError(
            f"{location} must be a string, safe integer, boolean, or null; "
            "floating-point genome values are not supported"
        )
    raise RequestError(
        f"{location} must be a string, safe integer, boolean, or null"
    )


def _number_as_float(value: object, location: str) -> tuple[Decimal, float]:
    if type(value) is bool or not isinstance(value, (int, Decimal)):
        raise RequestError(f"{location} must be a finite JSON number")
    exact = Decimal(value) if type(value) is int else value
    try:
        converted = float(exact)
    except (OverflowError, ValueError) as exc:
        raise RequestError(f"{location} is outside the finite double range") from exc
    if not math.isfinite(converted):
        raise RequestError(f"{location} is outside the finite double range")
    return exact, converted


def _probability(value: object, location: str, *, positive: bool) -> float:
    exact, converted = _number_as_float(value, location)
    lower_ok = exact > 0 if positive else exact >= 0
    if not lower_ok or exact > 1:
        relation = "greater than 0 and at most 1" if positive else "between 0 and 1"
        raise RequestError(f"{location} must be {relation}")
    if (converted == 0.0 and exact != 0) or (
        converted == 1.0 and exact != 1
    ):
        raise RequestError(
            f"{location} would change whether its value is zero or one "
            "in double precision"
        )
    return 0.0 if converted == 0.0 else converted


def _draw(value: object) -> float:
    exact, converted = _number_as_float(value, "draw")
    if exact < 0 or exact >= 1:
        raise RequestError("draw must be greater than or equal to 0 and less than 1")
    if converted == 1.0:
        raise RequestError("draw rounds to 1 in double precision")
    return 0.0 if converted == 0.0 else converted


def _atom_key(value: object) -> str:
    return canonical_json(value)


def _decode_catalogue(
    raw_catalogue: object,
) -> tuple[dict[str, object], dict[str, tuple[object, ...]]]:
    if type(raw_catalogue) is not dict:
        raise RequestError("catalogue must be a JSON object")
    _require_exact_keys(raw_catalogue, {"loci"}, "catalogue")
    raw_loci = raw_catalogue["loci"]
    if type(raw_loci) is not list or not raw_loci:
        raise RequestError("catalogue.loci must be a non-empty JSON array")

    decoded: dict[str, tuple[object, ...]] = {}
    for index, raw_locus in enumerate(raw_loci):
        location = f"catalogue.loci[{index}]"
        if type(raw_locus) is not dict:
            raise RequestError(f"{location} must be a JSON object")
        _require_exact_keys(raw_locus, {"locus", "alleles"}, location)
        locus = _require_nonempty_string(raw_locus["locus"], f"{location}.locus")
        if locus in decoded:
            raise RequestError(f"duplicate catalogue locus: {locus}")
        raw_alleles = raw_locus["alleles"]
        if type(raw_alleles) is not list or len(raw_alleles) < 2:
            raise RequestError(f"{location}.alleles must contain at least two values")
        alleles: list[object] = []
        seen: set[str] = set()
        for allele_index, raw_allele in enumerate(raw_alleles):
            allele = _require_atom(
                raw_allele, f"{location}.alleles[{allele_index}]"
            )
            key = _atom_key(allele)
            if key in seen:
                raise RequestError(f"{location}.alleles contains a duplicate value")
            seen.add(key)
            alleles.append(allele)
        decoded[locus] = tuple(sorted(alleles, key=_atom_key))

    normalized_loci = [
        {"alleles": list(decoded[locus]), "locus": locus}
        for locus in sorted(decoded)
    ]
    return {"loci": normalized_loci}, decoded


def _decode_parent(
    raw_parent: object, catalogue: dict[str, tuple[object, ...]]
) -> dict[str, object]:
    if type(raw_parent) is not dict:
        raise RequestError("parent_genome must be a JSON object")
    expected = set(catalogue)
    _require_exact_keys(raw_parent, expected, "parent_genome")

    parent: dict[str, object] = {}
    for locus in sorted(catalogue):
        allele = _require_atom(raw_parent[locus], f"parent_genome.{locus}")
        legal = {_atom_key(value) for value in catalogue[locus]}
        if _atom_key(allele) not in legal:
            raise RequestError(
                f"parent_genome.{locus} is not an allele in the catalogue"
            )
        parent[locus] = allele
    return parent


def _decode_distribution(
    raw_distribution: object,
    catalogue: dict[str, tuple[object, ...]],
    parent: dict[str, object],
) -> list[dict[str, object]]:
    if type(raw_distribution) is not list or not raw_distribution:
        raise RequestError("mutation_distribution must be a non-empty JSON array")

    mutations: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_mutation in enumerate(raw_distribution):
        location = f"mutation_distribution[{index}]"
        if type(raw_mutation) is not dict:
            raise RequestError(f"{location} must be a JSON object")
        _require_exact_keys(
            raw_mutation, {"locus", "allele", "probability"}, location
        )
        locus = _require_nonempty_string(raw_mutation["locus"], f"{location}.locus")
        if locus not in catalogue:
            raise RequestError(f"{location}.locus is not in the catalogue: {locus}")
        allele = _require_atom(raw_mutation["allele"], f"{location}.allele")
        allele_key = _atom_key(allele)
        if allele_key not in {_atom_key(value) for value in catalogue[locus]}:
            raise RequestError(f"{location}.allele is not legal for locus {locus}")
        if allele_key == _atom_key(parent[locus]):
            raise RequestError(f"{location} does not change the parent genome")
        transition = (locus, allele_key)
        if transition in seen:
            raise RequestError(
                "duplicate mutation transition for "
                f"locus {locus} and allele {allele_key}"
            )
        seen.add(transition)
        probability = _probability(
            raw_mutation["probability"], f"{location}.probability", positive=True
        )
        mutations.append(
            {"allele": allele, "locus": locus, "probability": probability}
        )

    mutations.sort(key=lambda item: (str(item["locus"]), _atom_key(item["allele"])))
    return mutations


def _measurement(measure: str, value: float) -> dict[str, object]:
    return {
        "base": 2.0,
        "infinite": math.isinf(value),
        "measure": measure,
        "value": None if math.isinf(value) else value,
    }


def decode_request(source: str) -> tuple[
    dict[str, object],
    dict[str, tuple[object, ...]],
    dict[str, object],
    list[dict[str, object]],
    float,
]:
    request = _decode_json(source)
    _require_exact_keys(
        request,
        {
            "schema_version",
            "catalogue",
            "parent_genome",
            "mutation_distribution",
            "draw",
        },
        "request",
    )
    _require_schema_version(request["schema_version"])
    normalized_catalogue, catalogue = _decode_catalogue(request["catalogue"])
    parent = _decode_parent(request["parent_genome"], catalogue)
    distribution = _decode_distribution(
        request["mutation_distribution"], catalogue, parent
    )
    draw = _draw(request["draw"])
    return normalized_catalogue, catalogue, parent, distribution, draw


def mutate(
    normalized_catalogue: dict[str, object],
    parent: dict[str, object],
    distribution: list[dict[str, object]],
    draw: float,
) -> dict[str, object]:
    probabilities = [float(item["probability"]) for item in distribution]
    distribution_entropy = entropy(probabilities, base=2)

    selected: dict[str, object] | None = None
    cumulative = 0.0
    for mutation in distribution:
        cumulative = math.fsum((cumulative, float(mutation["probability"])))
        if draw < cumulative:
            selected = mutation
            break
    if selected is None:
        raise RequestError(
            "draw is not covered by the supplied probability mass; "
            "the mutator does not normalize or assign missing mass"
        )

    locus = str(selected["locus"])
    before = parent[locus]
    after = selected["allele"]
    child = dict(parent)
    child[locus] = after

    catalogue_id = canonical_digest(
        {
            "catalogue": normalized_catalogue,
            "genome_schema": "flat-json-atoms-v1",
            "schema_version": SCHEMA_VERSION,
        }
    )
    parent_id = canonical_digest(
        {
            "genome": parent,
            "genome_schema": "flat-json-atoms-v1",
            "schema_version": SCHEMA_VERSION,
        }
    )
    child_id = canonical_digest(
        {
            "genome": child,
            "genome_schema": "flat-json-atoms-v1",
            "schema_version": SCHEMA_VERSION,
        }
    )
    mutation_id = canonical_digest(
        {
            "after": after,
            "before": before,
            "catalogue_id": catalogue_id,
            "locus": locus,
            "parent_candidate_id": parent_id,
            "schema_version": SCHEMA_VERSION,
        }
    )
    selected_probability = float(selected["probability"])
    selected_surprisal = self_information(selected_probability, base=2)

    return {
        "catalogue_id": catalogue_id,
        "child": {"candidate_id": child_id, "genome": child},
        "draw": draw,
        "mutation": {
            "after": after,
            "before": before,
            "locus": locus,
            "mutation_id": mutation_id,
            "probability": selected_probability,
            "surprisal": _measurement("self_information", selected_surprisal),
        },
        "mutation_distribution": {
            "entropy": _measurement("entropy", distribution_entropy),
            "support": distribution,
            "support_count": len(distribution),
        },
        "parent": {"candidate_id": parent_id, "genome": parent},
        "schema_version": SCHEMA_VERSION,
    }


def _mutate_skill_artifact(request: dict[str, object]) -> dict[str, object]:
    _require_exact_keys(
        request,
        {
            "schema_version",
            "parent_artifact",
            "challenger_artifact",
            "proposal",
        },
        "request",
    )
    try:
        require_schema_version(request["schema_version"])
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc
    proposal = request["proposal"]
    if type(proposal) is not dict:
        raise RequestError("proposal must be a JSON object")
    _require_exact_keys(proposal, {"producer", "reason"}, "proposal")
    producer = _require_nonempty_string(proposal["producer"], "proposal.producer")
    reason = _require_nonempty_string(proposal["reason"], "proposal.reason")
    try:
        parent = candidate_record(request["parent_artifact"], "parent_artifact")
        challenger = candidate_record(
            request["challenger_artifact"], "challenger_artifact"
        )
        changed_paths = changed_artifact_paths(parent, challenger)
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc
    if not changed_paths:
        raise RequestError("challenger_artifact must differ from parent_artifact")

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


def _require_single_skill_candidate(
    candidate: dict[str, object], location: str, *, allow_default: bool
) -> None:
    artifact = candidate["artifact"]
    assert type(artifact) is dict
    if artifact["artifact_schema"] == DEFAULT_ARTIFACT_SCHEMA:
        if allow_default:
            return
        raise RequestError(f"{location} must be an agent-skill-v1 artifact")
    files = artifact["files"]
    if (
        type(files) is not list
        or len(files) != 1
        or files[0].get("path") != "SKILL.md"
    ):
        raise RequestError(
            f"{location} must contain exactly one SKILL.md file for proposal"
        )


def _propose_skill_artifact(request: dict[str, object]) -> dict[str, object]:
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
        _require_single_skill_candidate(
            parent, "parent_artifact", allow_default=True
        )
        context = normalize_json_value(request["proposal_context"], "proposal_context")
        proposer = request["proposer"]
        if type(proposer) is not dict:
            raise ProtocolError("proposer must be a JSON object")
        require_exact_keys(proposer, {"command", "timeout_seconds"}, "proposer")
        command = decode_command(proposer["command"], "proposer.command")
        timeout = require_timeout(proposer["timeout_seconds"], "proposer.timeout_seconds")
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
        _require_single_skill_candidate(
            challenger,
            "proposal adapter response.challenger_artifact",
            allow_default=False,
        )
        reason = require_protocol_string(
            response["reason"], "proposal adapter response.reason"
        )
    except (ProtocolError, RequestError) as exc:
        if isinstance(exc, RequestError):
            raise
        raise RequestError(str(exc)) from exc

    return _mutate_skill_artifact(
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


def _process(source: str) -> dict[str, object]:
    request = _decode_json(source)
    if request.get("schema_version") == AGENT_SCHEMA_VERSION:
        if "proposer" in request or "proposal_context" in request:
            return _propose_skill_artifact(request)
        return _mutate_skill_artifact(request)
    normalized_catalogue, _, parent, distribution, draw = decode_request(source)
    return mutate(normalized_catalogue, parent, distribution, draw)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        _process,
        arguments,
        error_rules=(
            (RequestError, "invalid_request"),
            (ProbabilityError, "invalid_probability"),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
