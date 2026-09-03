"""Strict schemas and identities for the source-only Population Archive."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import cast

from metering import (
    ProbabilityError,
    entropy,
    mutual_information,
    self_information,
)

from apps.agent_protocol import (
    SKILL_ARTIFACT_SCHEMA,
    ProtocolError,
    candidate_record,
    decode_candidate,
    finite_number,
    normalize_json_value,
    probability,
    require_bool,
    require_exact_keys,
    require_nonempty_string,
    require_sha256,
)
from apps._support.wire import (
    canonical_digest,
    canonical_json,
)

POPULATION_SCHEMA_VERSION = 1
EXPERIMENT_SCHEMA = "population-experiment-v1"
RUN_SCHEMA = "population-run-v1"
ARCHIVE_POLICY = "pareto-uniform-v1"
ALLOCATION_POLICY = "uniform-v1"
LEDGER_NAME = "population.jsonl"
INDEX_NAME = "population.sqlite"
RESOURCE_NAMES = (
    "actions",
    "energy_millijoules",
    "gpu_milliseconds",
    "memory_bytes",
    "storage_bytes",
    "tokens",
    "wall_milliseconds",
)
MAX_ARCHIVE_CAPACITY = 10_000
MAX_PROTOCOL_INTEGER = 9_007_199_254_740_991


class RequestError(ValueError):
    """Raised when a population command request is malformed."""


class PopulationError(RuntimeError):
    """Raised when canonical state or a population transition is invalid."""


@dataclass
class PopulationState:
    configuration: dict[str, object]
    records: list[dict[str, object]]
    records_by_id: dict[str, dict[str, object]] = field(default_factory=dict)
    candidates: dict[str, dict[str, object]] = field(default_factory=dict)
    candidate_record_ids: dict[str, str] = field(default_factory=dict)
    candidate_parents: dict[str, list[str]] = field(default_factory=dict)
    experiments: dict[str, dict[str, object]] = field(default_factory=dict)
    experiment_record_ids: dict[str, str] = field(default_factory=dict)
    runs: list[dict[str, object]] = field(default_factory=list)
    run_record_ids: dict[str, str] = field(default_factory=dict)
    run_keys: set[tuple[str, str, str]] = field(default_factory=set)
    archives: dict[str, dict[str, object]] = field(default_factory=dict)
    archive_sequences: dict[str, int] = field(default_factory=dict)
    latest_archive_by_experiment: dict[str, str] = field(default_factory=dict)
    allocations: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    final_evaluation_started: bool = False
    last_run_sequence_by_experiment: dict[str, int] = field(default_factory=dict)

    @property
    def head_id(self) -> str:
        return str(self.records[-1]["record_id"])

    def record(self, record_id: str) -> dict[str, object] | None:
        """Return one verified canonical record by content identity."""

        return self.records_by_id.get(record_id)


def state_paths(root: Path) -> tuple[Path, Path]:
    return root / LEDGER_NAME, root / INDEX_NAME


def _nonnegative_integer(value: object, location: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_PROTOCOL_INTEGER:
        raise ProtocolError(
            f"{location} must be a non-negative integer no greater than "
            f"{MAX_PROTOCOL_INTEGER}"
        )
    return value


def _positive_integer(value: object, location: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_PROTOCOL_INTEGER:
        raise ProtocolError(
            f"{location} must be a positive integer no greater than "
            f"{MAX_PROTOCOL_INTEGER}"
        )
    return value


def _schema(value: object, location: str = "schema_version") -> None:
    if type(value) is not int or value != POPULATION_SCHEMA_VERSION:
        raise ProtocolError(f"{location} must be {POPULATION_SCHEMA_VERSION}")


def _normalized_path(value: object, location: str) -> str:
    path = require_nonempty_string(value, location)
    candidate = PurePosixPath(path)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != path
        or "\\" in path
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ProtocolError(f"{location} must be a normalized relative POSIX path")
    return path


def _configuration(value: object, location: str = "configuration") -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(value, {"archive_policy", "name"}, location)
    policy = value["archive_policy"]
    policy_location = f"{location}.archive_policy"
    if type(policy) is not dict:
        raise ProtocolError(f"{policy_location} must be a JSON object")
    require_exact_keys(
        policy,
        {"capacity", "reliability_kappa", "type"},
        policy_location,
    )
    if policy["type"] != ARCHIVE_POLICY:
        raise ProtocolError(f"{policy_location}.type must be {ARCHIVE_POLICY}")
    capacity = _positive_integer(policy["capacity"], f"{policy_location}.capacity")
    if capacity > MAX_ARCHIVE_CAPACITY:
        raise ProtocolError(
            f"{policy_location}.capacity must not exceed {MAX_ARCHIVE_CAPACITY}"
        )
    kappa = finite_number(
        policy["reliability_kappa"], f"{policy_location}.reliability_kappa"
    )
    if not 0.0 <= kappa <= 1_000_000.0:
        raise ProtocolError(
            f"{policy_location}.reliability_kappa must be between 0 and 1000000"
        )
    return {
        "archive_policy": {
            "capacity": capacity,
            "reliability_kappa": kappa,
            "type": ARCHIVE_POLICY,
        },
        "name": require_nonempty_string(value["name"], f"{location}.name"),
    }


def decode_initialize_request(value: dict[str, object]) -> dict[str, object]:
    try:
        require_exact_keys(value, {"configuration", "schema_version"}, "request")
        _schema(value["schema_version"])
        return _configuration(value["configuration"])
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc


def _variation(
    value: object,
    parents: list[str],
    location: str = "variation",
) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    variation_type = value.get("type")
    if variation_type == "seed-v1":
        require_exact_keys(value, {"choice", "policy_id", "type"}, location)
        if parents:
            raise ProtocolError("seed-v1 candidates must not declare parents")
        if value["policy_id"] is not None:
            raise ProtocolError(f"{location}.policy_id must be null for seed-v1")
        return {
            "choice": normalize_json_value(value["choice"], f"{location}.choice"),
            "policy_id": None,
            "type": "seed-v1",
        }
    if variation_type == "mutation-v1":
        require_exact_keys(value, {"choice", "policy_id", "type"}, location)
        if len(parents) != 1:
            raise ProtocolError(
                "mutation-v1 candidates must declare exactly one parent"
            )
        return {
            "choice": normalize_json_value(value["choice"], f"{location}.choice"),
            "policy_id": require_sha256(value["policy_id"], f"{location}.policy_id"),
            "type": "mutation-v1",
        }
    if variation_type == "typed-recombination-v1":
        require_exact_keys(value, {"loci", "policy_id", "type"}, location)
        if len(parents) != 2:
            raise ProtocolError(
                "typed-recombination-v1 candidates must declare exactly two parents"
            )
        raw_loci = value["loci"]
        if type(raw_loci) is not list or not raw_loci:
            raise ProtocolError(f"{location}.loci must be a non-empty JSON array")
        loci: list[dict[str, str]] = []
        seen: set[str] = set()
        for index, raw_locus in enumerate(raw_loci):
            locus_location = f"{location}.loci[{index}]"
            if type(raw_locus) is not dict:
                raise ProtocolError(f"{locus_location} must be a JSON object")
            require_exact_keys(
                raw_locus, {"parent_candidate_id", "path"}, locus_location
            )
            path = _normalized_path(raw_locus["path"], f"{locus_location}.path")
            if path in seen:
                raise ProtocolError(f"{location}.loci contains duplicate path: {path}")
            seen.add(path)
            parent_id = require_sha256(
                raw_locus["parent_candidate_id"],
                f"{locus_location}.parent_candidate_id",
            )
            if parent_id not in parents:
                raise ProtocolError(
                    f"{locus_location}.parent_candidate_id is not a declared parent"
                )
            loci.append({"parent_candidate_id": parent_id, "path": path})
        loci.sort(key=lambda item: item["path"])
        return {
            "loci": loci,
            "policy_id": require_sha256(value["policy_id"], f"{location}.policy_id"),
            "type": "typed-recombination-v1",
        }
    raise ProtocolError(
        f"{location}.type must be seed-v1, mutation-v1, or typed-recombination-v1"
    )


def _parent_ids(value: object, location: str = "parents") -> list[str]:
    if type(value) is not list:
        raise ProtocolError(f"{location} must be a JSON array")
    parents: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        parent = require_sha256(item, f"{location}[{index}]")
        if parent in seen:
            raise ProtocolError(f"{location} contains duplicate candidate: {parent}")
        seen.add(parent)
        parents.append(parent)
    return parents


def _skill_file_map(candidate: dict[str, object]) -> dict[str, dict[str, object]]:
    artifact = cast(dict[str, object], candidate["artifact"])
    if artifact.get("artifact_schema") != SKILL_ARTIFACT_SCHEMA:
        raise ProtocolError(
            "typed recombination supports only agent-skill-v1 artifacts"
        )
    files = cast(list[dict[str, object]], artifact["files"])
    return {str(item["path"]): item for item in files}


def _verify_recombination(
    candidate: dict[str, object],
    parents: list[str],
    variation: dict[str, object],
    state: PopulationState,
) -> None:
    parent_files: dict[str, dict[str, dict[str, object]]] = {}
    for parent_id in parents:
        if parent_id not in state.candidates:
            raise PopulationError(f"unknown recombination parent: {parent_id}")
        try:
            parent_files[parent_id] = _skill_file_map(state.candidates[parent_id])
        except ProtocolError as exc:
            raise PopulationError(str(exc)) from exc

    expected_paths = set().union(*(set(files) for files in parent_files.values()))
    loci = cast(list[dict[str, str]], variation["loci"])
    if {item["path"] for item in loci} != expected_paths:
        raise PopulationError(
            "typed recombination must choose exactly one parent for every artifact path"
        )

    child_files: list[dict[str, object]] = []
    meaningful_contributors: set[str] = set()
    for locus in loci:
        source_id = locus["parent_candidate_id"]
        path = locus["path"]
        source_file = parent_files[source_id].get(path)
        if source_file is None:
            raise PopulationError(
                f"recombination parent {source_id} does not contain locus {path}"
            )
        child_files.append(dict(source_file))
        other_ids = [parent for parent in parents if parent != source_id]
        if any(parent_files[other].get(path) != source_file for other in other_ids):
            meaningful_contributors.add(source_id)

    if meaningful_contributors != set(parents):
        raise PopulationError(
            "typed recombination must inherit at least one differing locus from each parent"
        )
    expected = candidate_record(
        {"artifact_schema": SKILL_ARTIFACT_SCHEMA, "files": child_files},
        "recombined artifact",
    )
    if canonical_json(candidate) != canonical_json(expected):
        raise PopulationError("recombined candidate does not match its locus receipt")


def _candidate_body(value: object, state: PopulationState) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError("candidate record body must be a JSON object")
    require_exact_keys(value, {"candidate", "parents", "variation"}, "candidate body")
    candidate = decode_candidate(value["candidate"], "candidate body.candidate")
    parents = _parent_ids(value["parents"], "candidate body.parents")
    for parent in parents:
        if parent not in state.candidates:
            raise PopulationError(f"unknown candidate parent: {parent}")
    variation = _variation(value["variation"], parents, "candidate body.variation")
    if variation["type"] == "typed-recombination-v1":
        _verify_recombination(candidate, parents, variation, state)
    return {"candidate": candidate, "parents": parents, "variation": variation}


def decode_candidate_request(
    value: dict[str, object], state: PopulationState
) -> dict[str, object]:
    try:
        require_exact_keys(
            value,
            {"artifact", "parents", "schema_version", "variation"},
            "request",
        )
        _schema(value["schema_version"])
        parents = _parent_ids(value["parents"])
        body = {
            "candidate": candidate_record(value["artifact"], "request.artifact"),
            "parents": parents,
            "variation": _variation(value["variation"], parents),
        }
        return _candidate_body(body, state)
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc


def _resources(value: object, location: str, *, positive: bool) -> dict[str, int]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(value, set(RESOURCE_NAMES), location)
    decode = _positive_integer if positive else _nonnegative_integer
    return {name: decode(value[name], f"{location}.{name}") for name in RESOURCE_NAMES}


def _experiment_spec(value: object, location: str = "experiment") -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(
        value,
        {
            "behavior_space",
            "budget",
            "case_count",
            "evaluator_id",
            "information_objective",
            "role",
            "runtime_id",
            "task_set_id",
        },
        location,
    )
    role = value["role"]
    if role not in {"development", "final"}:
        raise ProtocolError(f"{location}.role must be development or final")
    raw_space = value["behavior_space"]
    if type(raw_space) is not list or not raw_space:
        raise ProtocolError(f"{location}.behavior_space must be a non-empty JSON array")
    behavior_space: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_space):
        label = require_nonempty_string(item, f"{location}.behavior_space[{index}]")
        if label in seen:
            raise ProtocolError(
                f"{location}.behavior_space contains duplicate label: {label}"
            )
        seen.add(label)
        behavior_space.append(label)
    return {
        "behavior_space": behavior_space,
        "budget": _resources(value["budget"], f"{location}.budget", positive=True),
        "case_count": _positive_integer(value["case_count"], f"{location}.case_count"),
        "evaluator_id": require_sha256(
            value["evaluator_id"], f"{location}.evaluator_id"
        ),
        "information_objective": require_bool(
            value["information_objective"], f"{location}.information_objective"
        ),
        "role": role,
        "runtime_id": require_sha256(value["runtime_id"], f"{location}.runtime_id"),
        "task_set_id": require_sha256(value["task_set_id"], f"{location}.task_set_id"),
    }


def _experiment_body(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError("experiment record body must be a JSON object")
    require_exact_keys(value, {"experiment", "experiment_id"}, "experiment body")
    experiment = _experiment_spec(value["experiment"], "experiment body.experiment")
    experiment_id = canonical_digest(
        {"experiment": experiment, "experiment_schema": EXPERIMENT_SCHEMA}
    )
    supplied = require_sha256(value["experiment_id"], "experiment body.experiment_id")
    if supplied != experiment_id:
        raise ProtocolError("experiment body.experiment_id does not match its content")
    return {"experiment": experiment, "experiment_id": experiment_id}


def decode_experiment_request(value: dict[str, object]) -> dict[str, object]:
    try:
        require_exact_keys(value, {"experiment", "schema_version"}, "request")
        _schema(value["schema_version"])
        experiment = _experiment_spec(value["experiment"], "request.experiment")
        return _experiment_body(
            {
                "experiment": experiment,
                "experiment_id": canonical_digest(
                    {"experiment": experiment, "experiment_schema": EXPERIMENT_SCHEMA}
                ),
            }
        )
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc


def _distribution(
    value: object, location: str, *, length: int | None = None
) -> list[float]:
    if type(value) is not list or not value:
        raise ProtocolError(f"{location} must be a non-empty probability array")
    probabilities = [
        probability(item, f"{location}[{index}]") for index, item in enumerate(value)
    ]
    if length is not None and len(probabilities) != length:
        raise ProtocolError(f"{location} must contain exactly {length} probabilities")
    try:
        entropy(probabilities)
    except ProbabilityError as exc:
        raise ProtocolError(f"{location}: {exc}") from exc
    return probabilities


def _information_model(
    value: object, location: str
) -> tuple[dict[str, object] | None, float | None]:
    if value is None:
        return None, None
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be null or a JSON object")
    require_exact_keys(value, {"outcomes", "prior"}, location)
    prior = _distribution(value["prior"], f"{location}.prior")
    raw_outcomes = value["outcomes"]
    if type(raw_outcomes) is not list or not raw_outcomes:
        raise ProtocolError(f"{location}.outcomes must be a non-empty JSON array")
    outcomes: list[dict[str, object]] = []
    outcome_probabilities: list[float] = []
    joint: list[list[float]] = []
    for index, raw_outcome in enumerate(raw_outcomes):
        outcome_location = f"{location}.outcomes[{index}]"
        if type(raw_outcome) is not dict:
            raise ProtocolError(f"{outcome_location} must be a JSON object")
        require_exact_keys(raw_outcome, {"posterior", "probability"}, outcome_location)
        outcome_probability = probability(
            raw_outcome["probability"], f"{outcome_location}.probability"
        )
        posterior = _distribution(
            raw_outcome["posterior"],
            f"{outcome_location}.posterior",
            length=len(prior),
        )
        outcome_probabilities.append(outcome_probability)
        outcomes.append({"posterior": posterior, "probability": outcome_probability})
        joint.append([outcome_probability * item for item in posterior])
    try:
        entropy(outcome_probabilities)
    except ProbabilityError as exc:
        raise ProtocolError(f"{location}.outcomes probabilities: {exc}") from exc
    for hypothesis, expected in enumerate(prior):
        marginal = math.fsum(row[hypothesis] for row in joint)
        if not math.isclose(marginal, expected, rel_tol=0.0, abs_tol=1e-12):
            raise ProtocolError(
                f"{location} expected posteriors do not recover prior coordinate {hypothesis}"
            )
    try:
        information = mutual_information(joint)
    except ProbabilityError as exc:
        raise ProtocolError(f"{location}: {exc}") from exc
    return {"outcomes": outcomes, "prior": prior}, information


def _finite_or_infinite(value: float) -> dict[str, object]:
    return {
        "infinite": math.isinf(value),
        "value": None if math.isinf(value) else value,
    }


def _run_evidence(
    value: object,
    experiment: dict[str, object],
    location: str = "evidence",
) -> tuple[dict[str, object], dict[str, object]]:
    if type(value) is not dict:
        raise ProtocolError(f"{location} must be a JSON object")
    require_exact_keys(
        value,
        {
            "behavior_distribution",
            "cost",
            "evidence_receipt",
            "information_model",
            "protected_passed",
            "target_probabilities",
            "task",
        },
        location,
    )
    task = value["task"]
    if type(task) is not dict:
        raise ProtocolError(f"{location}.task must be a JSON object")
    require_exact_keys(
        task,
        {"case_count", "passed_count", "safety_failures"},
        f"{location}.task",
    )
    case_count = _positive_integer(task["case_count"], f"{location}.task.case_count")
    if case_count != experiment["case_count"]:
        raise ProtocolError(f"{location}.task.case_count does not match the experiment")
    passed_count = _nonnegative_integer(
        task["passed_count"], f"{location}.task.passed_count"
    )
    if passed_count > case_count:
        raise ProtocolError(f"{location}.task.passed_count must not exceed case_count")
    safety_failures = _nonnegative_integer(
        task["safety_failures"], f"{location}.task.safety_failures"
    )
    if safety_failures > case_count:
        raise ProtocolError(
            f"{location}.task.safety_failures must not exceed case_count"
        )

    raw_targets = value["target_probabilities"]
    if type(raw_targets) is not list or len(raw_targets) != case_count:
        raise ProtocolError(
            f"{location}.target_probabilities must contain one value per task case"
        )
    targets = [
        probability(item, f"{location}.target_probabilities[{index}]")
        for index, item in enumerate(raw_targets)
    ]
    surprisals = [self_information(item) for item in targets]
    mean_surprisal = (
        math.inf
        if any(math.isinf(item) for item in surprisals)
        else math.fsum(surprisals) / case_count
    )

    receipt = value["evidence_receipt"]
    if type(receipt) is not dict:
        raise ProtocolError(f"{location}.evidence_receipt must be a JSON object")
    require_exact_keys(receipt, {"sha256", "uri"}, f"{location}.evidence_receipt")
    evidence_receipt = {
        "sha256": require_sha256(
            receipt["sha256"], f"{location}.evidence_receipt.sha256"
        ),
        "uri": require_nonempty_string(
            receipt["uri"], f"{location}.evidence_receipt.uri"
        ),
    }

    behavior_space = cast(list[str], experiment["behavior_space"])
    behavior = _distribution(
        value["behavior_distribution"],
        f"{location}.behavior_distribution",
        length=len(behavior_space),
    )
    information_model, information = _information_model(
        value["information_model"], f"{location}.information_model"
    )
    if experiment["information_objective"] is True and information is None:
        raise ProtocolError(
            f"{location}.information_model is required by the experiment"
        )
    cost = _resources(value["cost"], f"{location}.cost", positive=False)
    budget = cast(dict[str, int], experiment["budget"])
    budget_passed = all(cost[name] <= budget[name] for name in RESOURCE_NAMES)
    protected_passed = require_bool(
        value["protected_passed"], f"{location}.protected_passed"
    )
    survival_passed = protected_passed and safety_failures == 0 and budget_passed
    normalized = {
        "behavior_distribution": behavior,
        "cost": cost,
        "evidence_receipt": evidence_receipt,
        "information_model": information_model,
        "protected_passed": protected_passed,
        "target_probabilities": targets,
        "task": {
            "case_count": case_count,
            "passed_count": passed_count,
            "safety_failures": safety_failures,
        },
    }
    measurements = {
        "budget_passed": budget_passed,
        "information_value_bits": information,
        "mean_target_surprisal_bits": _finite_or_infinite(mean_surprisal),
        "survival_passed": survival_passed,
        "task_rate": passed_count / case_count,
    }
    return normalized, measurements


def _run_body(value: object, state: PopulationState) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolError("run record body must be a JSON object")
    require_exact_keys(value, {"evidence", "measurements", "run"}, "run body")
    run = value["run"]
    if type(run) is not dict:
        raise ProtocolError("run body.run must be a JSON object")
    require_exact_keys(
        run,
        {
            "candidate_id",
            "experiment_id",
            "replicate_id",
            "run_id",
            "seed",
        },
        "run body.run",
    )
    candidate_id = require_sha256(run["candidate_id"], "run body.run.candidate_id")
    experiment_id = require_sha256(run["experiment_id"], "run body.run.experiment_id")
    if candidate_id not in state.candidates:
        raise PopulationError(f"unknown run candidate: {candidate_id}")
    if experiment_id not in state.experiments:
        raise PopulationError(f"unknown run experiment: {experiment_id}")
    replicate_id = require_nonempty_string(
        run["replicate_id"], "run body.run.replicate_id"
    )
    seed = normalize_json_value(run["seed"], "run body.run.seed")
    expected_id = canonical_digest(
        {
            "candidate_id": candidate_id,
            "experiment_id": experiment_id,
            "replicate_id": replicate_id,
            "run_schema": RUN_SCHEMA,
        }
    )
    supplied_id = require_sha256(run["run_id"], "run body.run.run_id")
    if supplied_id != expected_id:
        raise ProtocolError("run body.run.run_id does not match its identity")
    evidence, measurements = _run_evidence(
        value["evidence"], state.experiments[experiment_id], "run body.evidence"
    )
    normalized_measurements = normalize_json_value(
        value["measurements"], "run body.measurements"
    )
    if canonical_json(normalized_measurements) != canonical_json(measurements):
        raise ProtocolError("run body.measurements do not match named evidence")
    return {
        "evidence": evidence,
        "measurements": measurements,
        "run": {
            "candidate_id": candidate_id,
            "experiment_id": experiment_id,
            "replicate_id": replicate_id,
            "run_id": expected_id,
            "seed": seed,
        },
    }


def decode_run_request(
    value: dict[str, object], state: PopulationState
) -> dict[str, object]:
    try:
        require_exact_keys(
            value,
            {
                "candidate_id",
                "evidence",
                "experiment_id",
                "replicate_id",
                "schema_version",
                "seed",
            },
            "request",
        )
        _schema(value["schema_version"])
        candidate_id = require_sha256(value["candidate_id"], "request.candidate_id")
        experiment_id = require_sha256(value["experiment_id"], "request.experiment_id")
        replicate_id = require_nonempty_string(
            value["replicate_id"], "request.replicate_id"
        )
        seed = normalize_json_value(value["seed"], "request.seed")
        if experiment_id not in state.experiments:
            raise PopulationError(f"unknown run experiment: {experiment_id}")
        evidence, measurements = _run_evidence(
            value["evidence"], state.experiments[experiment_id], "request.evidence"
        )
        body = {
            "evidence": evidence,
            "measurements": measurements,
            "run": {
                "candidate_id": candidate_id,
                "experiment_id": experiment_id,
                "replicate_id": replicate_id,
                "run_id": canonical_digest(
                    {
                        "candidate_id": candidate_id,
                        "experiment_id": experiment_id,
                        "replicate_id": replicate_id,
                        "run_schema": RUN_SCHEMA,
                    }
                ),
                "seed": seed,
            },
        }
        return _run_body(body, state)
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc


def decode_recombination_request(
    value: dict[str, object], state: PopulationState
) -> dict[str, object]:
    try:
        require_exact_keys(
            value,
            {"loci", "parents", "policy_id", "schema_version"},
            "request",
        )
        _schema(value["schema_version"])
        parents = _parent_ids(value["parents"], "request.parents")
        variation = _variation(
            {
                "loci": value["loci"],
                "policy_id": value["policy_id"],
                "type": "typed-recombination-v1",
            },
            parents,
            "request",
        )
        parent_files = {
            parent: _skill_file_map(state.candidates[parent])
            for parent in parents
            if parent in state.candidates
        }
        if len(parent_files) != len(parents):
            missing = next(
                parent for parent in parents if parent not in state.candidates
            )
            raise PopulationError(f"unknown recombination parent: {missing}")
        child_files = [
            dict(parent_files[item["parent_candidate_id"]][item["path"]])
            for item in cast(list[dict[str, str]], variation["loci"])
            if item["path"] in parent_files[item["parent_candidate_id"]]
        ]
        if len(child_files) != len(cast(list[object], variation["loci"])):
            raise PopulationError(
                "a selected recombination parent does not contain its locus"
            )
        body = {
            "candidate": candidate_record(
                {"artifact_schema": SKILL_ARTIFACT_SCHEMA, "files": child_files},
                "recombined artifact",
            ),
            "parents": parents,
            "variation": variation,
        }
        return _candidate_body(body, state)
    except KeyError as exc:
        raise PopulationError(f"missing recombination locus: {exc.args[0]}") from exc
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc


# Public owner-contract names used by Population replay and outer sequencers.
# The schema remains local to Population; callers do not import private helpers.
normalize_candidate_body = _candidate_body
normalize_configuration = _configuration
normalize_distribution = _distribution
normalize_experiment_body = _experiment_body
normalize_resources = _resources
normalize_run_body = _run_body
require_population_schema = _schema
finite_or_infinite = _finite_or_infinite
nonnegative_integer = _nonnegative_integer
positive_integer = _positive_integer
