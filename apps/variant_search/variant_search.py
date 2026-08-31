"""Deterministic SQLite population registry and selection tool.

This source-only application stores externally produced candidates and evidence.
It does not run agents, estimate probabilities, choose objectives, expose hidden
randomness, or define a universal fitness score.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = ROOT / "apps"
SRC_ROOT = ROOT / "src"
HERE = Path(__file__).resolve().parent
for import_root in (APPS_ROOT, SRC_ROOT, HERE):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from agent_protocol import (  # noqa: E402
    ProtocolError,
    decode_candidate,
    require_exact_keys,
    require_nonempty_string,
    require_sha256,
)
from metering import entropy  # noqa: E402
from stdio_connector import (  # noqa: E402
    decode_json_object,
    error_document,
    write_document,
)

from population_math import (  # noqa: E402
    PopulationMathError,
    declared_score,
    decode_objectives,
    draw_without_replacement,
    finite_number,
    pareto_front,
    replicator_update,
    softmax_distribution,
)
from population_store import PopulationStore, PopulationStoreError  # noqa: E402

SCHEMA_VERSION = 1


class PopulationRequestError(ValueError):
    """Raised when a population-tool request violates its JSON contract."""


def _schema_and_operation(request: dict[str, object]) -> str:
    operation = request.get("operation")
    if type(request.get("schema_version")) is not int or request["schema_version"] != 1:
        raise PopulationRequestError("schema_version must be 1")
    if type(operation) is not str or not operation:
        raise PopulationRequestError("operation must be a non-empty string")
    return operation


def _object(value: object, location: str) -> dict[str, object]:
    if type(value) is not dict:
        raise PopulationRequestError(f"{location} must be a JSON object")
    return cast(dict[str, object], value)


def _string_array(
    value: object, location: str, *, maximum: int | None = None
) -> list[str]:
    if type(value) is not list:
        raise PopulationRequestError(f"{location} must be a JSON string array")
    result: list[str] = []
    for index, item in enumerate(value):
        try:
            result.append(require_nonempty_string(item, f"{location}[{index}]"))
        except ProtocolError as exc:
            raise PopulationRequestError(str(exc)) from exc
    if len(set(result)) != len(result):
        raise PopulationRequestError(f"{location} must contain unique values")
    if maximum is not None and len(result) > maximum:
        raise PopulationRequestError(f"{location} may contain at most {maximum} values")
    return result


def _sha_array(value: object, location: str) -> list[str]:
    values = _string_array(value, location)
    result: list[str] = []
    for index, item in enumerate(values):
        try:
            result.append(require_sha256(item, f"{location}[{index}]"))
        except ProtocolError as exc:
            raise PopulationRequestError(str(exc)) from exc
    return result


def _numeric_map(
    value: object,
    location: str,
    *,
    nonnegative: bool,
    require_nonempty: bool,
) -> dict[str, float]:
    raw = _object(value, location)
    if require_nonempty and not raw:
        raise PopulationRequestError(f"{location} must not be empty")
    result: dict[str, float] = {}
    for key, item in raw.items():
        if not key or "\x00" in key:
            raise PopulationRequestError(f"{location} keys must be non-empty strings")
        converted = finite_number(item, f"{location}.{key}")
        if nonnegative and converted < 0.0:
            raise PopulationRequestError(f"{location}.{key} must be non-negative")
        result[key] = converted
    return result


def _constraints(value: object) -> dict[str, bool]:
    raw = _object(value, "constraints")
    result: dict[str, bool] = {}
    for key, item in raw.items():
        if not key or "\x00" in key:
            raise PopulationRequestError("constraint names must be non-empty strings")
        if type(item) is not bool:
            raise PopulationRequestError(f"constraints.{key} must be a boolean")
        result[key] = item
    return result


def _positive_integer(value: object, location: str) -> int:
    if type(value) is not int or value < 1:
        raise PopulationRequestError(f"{location} must be a positive integer")
    return value


def _generation(value: object) -> int:
    if type(value) is not int or value < 0:
        raise PopulationRequestError("generation must be a non-negative integer")
    return value


def _draws(value: object) -> list[float]:
    if type(value) is not list or len(value) > 2:
        raise PopulationRequestError("parent_draws must contain zero, one, or two draws")
    draws: list[float] = []
    for index, item in enumerate(value):
        draw = finite_number(item, f"parent_draws[{index}]")
        if not 0.0 <= draw < 1.0:
            raise PopulationRequestError(
                f"parent_draws[{index}] must be in [0, 1)"
            )
        draws.append(draw)
    return draws


def _initialize(request: dict[str, object], store: PopulationStore) -> dict[str, object]:
    require_exact_keys(request, {"law", "operation", "schema_version"}, "request")
    law = _object(request["law"], "law")
    law_id, created = store.initialize(law)
    snapshot = store.snapshot()
    return {
        "created": created,
        "law_id": law_id,
        "operation": "initialize",
        "schema_version": SCHEMA_VERSION,
        "state_id": snapshot["state_id"],
    }


def _register_candidate(
    request: dict[str, object], store: PopulationStore
) -> dict[str, object]:
    require_exact_keys(
        request,
        {
            "candidate",
            "generation",
            "manifest",
            "operation",
            "operator",
            "parents",
            "schema_version",
        },
        "request",
    )
    try:
        candidate = decode_candidate(request["candidate"])
        operator = require_nonempty_string(request["operator"], "operator")
    except ProtocolError as exc:
        raise PopulationRequestError(str(exc)) from exc
    parents = _sha_array(request["parents"], "parents")
    if len(parents) > 2:
        raise PopulationRequestError("parents may contain at most two candidate IDs")
    manifest = _object(request["manifest"], "manifest")
    created = store.register_candidate(
        candidate=candidate,
        parents=parents,
        generation=_generation(request["generation"]),
        operator=operator,
        manifest=manifest,
    )
    snapshot = store.snapshot()
    return {
        "candidate_id": candidate["candidate_id"],
        "created": created,
        "operation": "register_candidate",
        "schema_version": SCHEMA_VERSION,
        "state_id": snapshot["state_id"],
    }


def _record_evaluation(
    request: dict[str, object], store: PopulationStore
) -> dict[str, object]:
    require_exact_keys(
        request,
        {
            "candidate_id",
            "constraints",
            "descriptors",
            "environment_id",
            "metrics",
            "operation",
            "resources",
            "schema_version",
        },
        "request",
    )
    try:
        candidate_id = require_sha256(request["candidate_id"], "candidate_id")
        environment_id = require_nonempty_string(
            request["environment_id"], "environment_id"
        )
    except ProtocolError as exc:
        raise PopulationRequestError(str(exc)) from exc
    evidence_id, created = store.record_evaluation(
        candidate_id=candidate_id,
        environment_id=environment_id,
        metrics=_numeric_map(
            request["metrics"], "metrics", nonnegative=False, require_nonempty=True
        ),
        constraints=_constraints(request["constraints"]),
        descriptors=_object(request["descriptors"], "descriptors"),
        resources=_numeric_map(
            request["resources"],
            "resources",
            nonnegative=True,
            require_nonempty=False,
        ),
    )
    snapshot = store.snapshot()
    return {
        "created": created,
        "evidence_id": evidence_id,
        "operation": "record_evaluation",
        "schema_version": SCHEMA_VERSION,
        "state_id": snapshot["state_id"],
    }


def _selection_records(
    store: PopulationStore, evidence_ids: list[str]
) -> tuple[str, list[dict[str, object]]]:
    records = [store.evaluation(evidence_id) for evidence_id in evidence_ids]
    environment_ids = {str(record["environment_id"]) for record in records}
    if len(environment_ids) != 1:
        raise PopulationRequestError(
            "selection evidence must use one identical environment_id"
        )
    candidate_ids = [str(record["candidate_id"]) for record in records]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise PopulationRequestError(
            "selection evidence must contain exactly one report per candidate"
        )
    return next(iter(environment_ids)), records


def _select(request: dict[str, object], store: PopulationStore) -> dict[str, object]:
    require_exact_keys(
        request,
        {
            "beta",
            "evidence_ids",
            "objectives",
            "operation",
            "parent_draws",
            "pool_size",
            "required_constraints",
            "schema_version",
        },
        "request",
    )
    evidence_ids = _sha_array(request["evidence_ids"], "evidence_ids")
    if not evidence_ids:
        raise PopulationRequestError("evidence_ids must not be empty")
    environment_id, records = _selection_records(store, evidence_ids)
    required_constraints = _string_array(
        request["required_constraints"], "required_constraints"
    )
    objectives = decode_objectives(request["objectives"])
    pool_size = _positive_integer(request["pool_size"], "pool_size")
    beta = finite_number(request["beta"], "beta")
    if beta < 0.0:
        raise PopulationRequestError("beta must be non-negative")
    draws = _draws(request["parent_draws"])

    eligible: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for record in records:
        constraints = cast(dict[str, object], record["constraints"])
        missing = [name for name in required_constraints if name not in constraints]
        if missing:
            raise PopulationRequestError(
                "evidence is missing required constraints: " + ", ".join(missing)
            )
        failed = [name for name in required_constraints if constraints[name] is not True]
        if failed:
            rejected.append(
                {
                    "candidate_id": record["candidate_id"],
                    "failed_constraints": failed,
                }
            )
        else:
            eligible.append(record)
    if not eligible:
        raise PopulationRequestError("no candidate satisfies the required constraints")

    metrics_by_id = {
        str(record["candidate_id"]): cast(dict[str, object], record["metrics"])
        for record in eligible
    }
    score_by_id = {
        candidate_id: declared_score(metrics, objectives)
        for candidate_id, metrics in metrics_by_id.items()
    }
    frontier = pareto_front(metrics_by_id, objectives)
    frontier_set = set(frontier)
    ranking = sorted(
        metrics_by_id,
        key=lambda candidate_id: (
            candidate_id not in frontier_set,
            -score_by_id[candidate_id],
            candidate_id,
        ),
    )
    retained = ranking[: min(pool_size, len(ranking))]
    weights = softmax_distribution(
        [score_by_id[candidate_id] for candidate_id in retained], beta
    )
    selected_parents = draw_without_replacement(retained, weights, draws)
    evidence_by_candidate = {
        str(record["candidate_id"]): str(record["evidence_id"])
        for record in eligible
    }
    descriptor_by_candidate = {
        str(record["candidate_id"]): record["descriptors"] for record in eligible
    }
    pool = [
        {
            "candidate_id": candidate_id,
            "descriptors": descriptor_by_candidate[candidate_id],
            "evidence_id": evidence_by_candidate[candidate_id],
            "on_pareto_front": candidate_id in frontier_set,
            "score": score_by_id[candidate_id],
            "weight": weight,
        }
        for candidate_id, weight in zip(retained, weights)
    ]
    reason = {
        "beta": beta,
        "environment_id": environment_id,
        "evidence_ids": evidence_ids,
        "objectives": [
            {
                "direction": objective.direction,
                "metric": objective.metric,
                "weight": objective.weight,
            }
            for objective in objectives
        ],
        "required_constraints": required_constraints,
    }
    store.set_pool(
        [(str(item["candidate_id"]), float(item["weight"])) for item in pool],
        reason=reason,
    )
    snapshot = store.snapshot()
    return {
        "allocation_entropy_bits": entropy(weights),
        "environment_id": environment_id,
        "operation": "select",
        "pareto_front": frontier,
        "parents": selected_parents,
        "pool": pool,
        "rejected": rejected,
        "schema_version": SCHEMA_VERSION,
        "state_id": snapshot["state_id"],
    }


def _reallocate(request: dict[str, object], store: PopulationStore) -> dict[str, object]:
    require_exact_keys(
        request,
        {
            "contribution_factors",
            "operation",
            "parent_draws",
            "schema_version",
        },
        "request",
    )
    current_pool = store.pool()
    if not current_pool:
        raise PopulationRequestError("active pool is empty")
    factors = _numeric_map(
        request["contribution_factors"],
        "contribution_factors",
        nonnegative=True,
        require_nonempty=True,
    )
    candidate_ids = [str(item["candidate_id"]) for item in current_pool]
    if set(factors) != set(candidate_ids):
        raise PopulationRequestError(
            "contribution_factors must contain exactly the active pool candidate IDs"
        )
    weights = replicator_update(
        [item["weight"] for item in current_pool],
        [factors[candidate_id] for candidate_id in candidate_ids],
    )
    draws = _draws(request["parent_draws"])
    parents = draw_without_replacement(candidate_ids, weights, draws)
    store.set_pool(
        list(zip(candidate_ids, weights)),
        reason={"contribution_factors": factors, "operation": "reallocate"},
    )
    snapshot = store.snapshot()
    return {
        "allocation_entropy_bits": entropy(weights),
        "operation": "reallocate",
        "parents": parents,
        "pool": [
            {"candidate_id": candidate_id, "weight": weight}
            for candidate_id, weight in zip(candidate_ids, weights)
        ],
        "schema_version": SCHEMA_VERSION,
        "state_id": snapshot["state_id"],
    }


def process(source: str, database: Path) -> dict[str, object]:
    request = decode_json_object(source, PopulationRequestError)
    operation = _schema_and_operation(request)
    if operation == "initialize":
        require_exact_keys(request, {"law", "operation", "schema_version"}, "request")
        _object(request["law"], "law")
    elif not database.exists():
        raise PopulationStoreError("population database is not initialized")
    database.parent.mkdir(parents=True, exist_ok=True)
    with PopulationStore(database) as store:
        if operation == "initialize":
            return _initialize(request, store)
        if operation == "register_candidate":
            return _register_candidate(request, store)
        if operation == "record_evaluation":
            return _record_evaluation(request, store)
        if operation == "select":
            return _select(request, store)
        if operation == "reallocate":
            return _reallocate(request, store)
        if operation == "snapshot":
            require_exact_keys(
                request, {"operation", "schema_version"}, "request"
            )
            return {
                "operation": "snapshot",
                "schema_version": SCHEMA_VERSION,
                **store.snapshot(),
            }
        if operation == "verify":
            require_exact_keys(
                request, {"operation", "schema_version"}, "request"
            )
            return {
                "operation": "verify",
                "schema_version": SCHEMA_VERSION,
                **store.verify(),
            }
        raise PopulationRequestError(f"unsupported operation: {operation}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="variant-search",
        description="Apply one deterministic population-search operation.",
        allow_abbrev=False,
    )
    parser.add_argument("--database", required=True, type=Path)
    return parser


def main() -> int:
    parser = _parser()
    try:
        arguments = parser.parse_args()
        document = process(sys.stdin.read(), arguments.database)
    except (PopulationRequestError, PopulationMathError, ProtocolError, ValueError) as exc:
        write_document(sys.stderr, error_document("invalid_request", str(exc)))
        return 2
    except (PopulationStoreError, sqlite3.Error, OSError) as exc:
        write_document(sys.stderr, error_document("invalid_population", str(exc)))
        return 2
    write_document(sys.stdout, document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
