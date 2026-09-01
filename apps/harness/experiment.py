#!/usr/bin/env python3
"""One-command mutation-only Darwinian harness experiment and offline verifier."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.durable import atomic_write  # noqa: E402
from apps._support.wire import (  # noqa: E402
    canonical_digest,
    canonical_json,
    decode_json_object,
    write_document,
)
from apps.agent_protocol import (  # noqa: E402
    GIT_ARTIFACT_SCHEMA,
    decode_agent_artifact,
)
from apps.harness.conformance import run_conformance  # noqa: E402
from apps.harness.final_assay import FinalAssayError, run_final_assay  # noqa: E402
from apps.harness.harness_runner import EVIDENCE_KEY  # noqa: E402
from apps.harness.protocol import (  # noqa: E402
    HarnessProtocolError,
    load_candidate,
)
from apps.harness.receipts import (  # noqa: E402
    HarnessReceiptError,
    aggregate_cost,
    load_receipt,
    verify_receipt_binding,
)
from apps.harness.runtime_manifest import (  # noqa: E402
    RuntimeManifest,
    RuntimeManifestError,
    assert_candidate_compatible,
    load_runtime_manifest,
)
from apps.population.contract import (  # noqa: E402
    RESOURCE_NAMES,
    PopulationState,
    load_state,
)
from apps.population_driver.paths import population_root  # noqa: E402
from apps.population_driver.population_driver_state import read_receipt  # noqa: E402
from apps.population_driver.runtime import (  # noqa: E402
    run_population_driver,
    verify_population_driver,
)
from artifacts.git.git_repository import (  # noqa: E402
    GitCandidateError,
    clone_verified,
    content_sha256,
    run_git,
)

REFERENCE = ROOT / "apps" / "harness" / "reference"
FIXTURES = ROOT / "apps" / "harness" / "fixtures"
PROFILES = ROOT / "apps" / "harness" / "profiles"
VALIDATE = ROOT / "apps" / "harness" / "validate_candidate.py"
GENERIC_RUNNER = ROOT / "apps" / "harness" / "harness_runner.py"
EVIDENCE = ROOT / "apps" / "harness" / "evidence_adapter.py"
GIT_ADAPTER = ROOT / "artifacts" / "git" / "git_candidate_adapter.py"
EVALUATOR = FIXTURES / "arithmetic_evaluator.py"
FIXTURE_MODEL = FIXTURES / "fixture_model.py"
FIXTURE_PROPOSER = FIXTURES / "fixture_proposer.py"
DRIVER_SCHEMA_VERSION = 1


class ExperimentError(RuntimeError):
    """Raised when the reference composition cannot safely complete."""


def _git_environment() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_AUTHOR_EMAIL": "harness-seed@example.invalid",
        "GIT_AUTHOR_NAME": "Metering Harness Seed",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_EMAIL": "harness-seed@example.invalid",
        "GIT_COMMITTER_NAME": "Metering Harness Seed",
    }


def _initialize_repository(root: Path) -> tuple[Path, Path, dict[str, object]]:
    seed = root / "seed-checkout"
    remote = root / "candidate.git"
    shutil.copytree(REFERENCE, seed)
    load_candidate(seed)
    run_git(["init", "--quiet"], cwd=seed)
    run_git(["add", "--all"], cwd=seed)
    tree = run_git(["write-tree"], cwd=seed).strip()
    commit = run_git(
        ["commit-tree", tree],
        cwd=seed,
        input_text="Reference evolutionary harness seed\n",
        environment=_git_environment(),
    ).strip()
    run_git(["update-ref", "refs/heads/main", commit], cwd=seed)
    run_git(["init", "--quiet", "--bare", str(remote)], cwd=seed)
    run_git(["remote", "add", "origin", str(remote)], cwd=seed)
    run_git(["push", "--quiet", "origin", "main:refs/heads/main"], cwd=seed)
    artifact = decode_agent_artifact(
        {
            "artifact_schema": GIT_ARTIFACT_SCHEMA,
            "commit": commit,
            "content_sha256": content_sha256(seed, commit),
            "entrypoint": "harness.json",
            "git_tree": tree,
            "outputs": [],
            "repository": str(remote),
        }
    )
    return seed, remote, artifact


def _tasks(path: Path) -> list[dict[str, object]]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ExperimentError(f"cannot read assay tasks: {exc}") from exc
    document = decode_json_object(source, ExperimentError)
    if source != canonical_json(document) + "\n" or set(document) != {"tasks"}:
        raise ExperimentError("assay task file is not canonical")
    tasks = document["tasks"]
    if (
        type(tasks) is not list
        or not tasks
        or any(type(item) is not dict for item in tasks)
    ):
        raise ExperimentError("assay task file is malformed")
    return cast(list[dict[str, object]], tasks)


def _budget(value: int = 10**12) -> dict[str, int]:
    return {name: value for name in RESOURCE_NAMES}


def _commands(agent: str) -> tuple[list[str], list[str]]:
    if agent == "fixture":
        return [sys.executable, str(FIXTURE_PROPOSER)], [
            sys.executable,
            str(GENERIC_RUNNER),
        ]
    directory = "pi" if agent == "pi" else "prime_agent"
    connector = ROOT / "connectors" / "fixed" / directory
    return (
        [sys.executable, str(connector / "harness_proposer.py")],
        [sys.executable, str(connector / "harness_runner.py")],
    )


def _request(
    artifact: dict[str, object],
    *,
    proposal_command: list[str],
    tasks: list[dict[str, object]],
    runtime: RuntimeManifest,
) -> dict[str, object]:
    evaluator = [sys.executable, str(EVALUATOR)]
    return {
        "allocation_draws": [{"denominator": 1, "numerator": 0}],
        "evidence_adapter": {
            "command": [sys.executable, str(EVIDENCE)],
            "timeout_seconds": 60,
        },
        "generation": {
            "evaluation": "evolutionary-harness/development-addition-v1",
            "evaluator": {"command": evaluator, "timeout_seconds": 30},
            "runner": {
                "command": [sys.executable, str(GIT_ADAPTER)],
                "timeout_seconds": 600,
            },
            "selection_policy": {
                "minimum_pass_improvement": 1,
                "reject_safety_regression": True,
                "type": "task-pass-count-v1",
            },
            "tasks": tasks,
        },
        "initial_parent_artifact": artifact,
        "limits": {
            "max_proposal_calls": 2,
            "max_rounds": 2,
            "max_total_candidate_cost": _budget(10**15),
            "max_wall_seconds": 100_000,
        },
        "population": {
            "configuration": {
                "archive_policy": {
                    "capacity": 8,
                    "reliability_kappa": 0,
                    "type": "pareto-uniform-v1",
                },
                "name": "reference-evolutionary-harness",
            },
            "development": {
                "behavior_space": ["fail", "pass"],
                "budget": _budget(),
                "runtime_id": runtime.runtime_id,
            },
        },
        "proposal": {
            "command": proposal_command,
            "context": {
                "candidate_contract": "evolutionary-harness-v1",
                "model_identity": runtime.model,
                "objective": (
                    "Mutate one typed harness locus so the external arithmetic assay "
                    "solves left-plus-right tasks more reliably. Do not claim success."
                ),
            },
            "timeout_seconds": 600,
        },
        "schema_version": DRIVER_SCHEMA_VERSION,
    }


@contextmanager
def _configured_environment(
    *,
    agent: str,
    runtime_path: Path,
    runtime: RuntimeManifest,
    remote: Path,
    receipts: Path,
    runner_command: list[str],
    candidate_paths: list[str],
) -> Iterator[None]:
    changes = {
        "METERING_GIT_ALLOWED_PATHS_JSON": canonical_json(candidate_paths),
        "METERING_GIT_EXECUTOR_COMMAND": canonical_json(runner_command),
        "METERING_GIT_EXECUTOR_TIMEOUT": "600",
        "METERING_GIT_REF_PREFIX": "refs/heads/evolution/harness",
        "METERING_GIT_REPOSITORY": str(remote),
        "METERING_GIT_VALIDATE_COMMAND": canonical_json(
            [sys.executable, str(VALIDATE)]
        ),
        "METERING_GIT_VALIDATE_TIMEOUT": "60",
        "METERING_HARNESS_ALLOW_UNSAFE_FIXTURE": "1" if agent == "fixture" else None,
        "METERING_HARNESS_MODEL": runtime.model["model"],
        "METERING_HARNESS_MODEL_COMMAND": (
            canonical_json([sys.executable, str(FIXTURE_MODEL)])
            if agent == "fixture"
            else None
        ),
        "METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES": str(runtime.max_output_bytes),
        "METERING_HARNESS_MODEL_TIMEOUT": str(runtime.model_timeout_seconds),
        "METERING_HARNESS_PROVIDER": runtime.model["provider"],
        "METERING_HARNESS_REASONING": runtime.model["reasoning"],
        "METERING_HARNESS_RECEIPT_DIR": str(receipts),
        "METERING_HARNESS_RUNTIME_MANIFEST": str(runtime_path),
    }
    old = {name: os.environ.get(name) for name in changes}
    try:
        for name, value in changes.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _expected_connector(agent: str) -> str:
    return {
        "fixture": "fixture-v1",
        "pi": "pi-v1",
        "prime-agent": "prime-agent-v1",
    }[agent]


def run_experiment(
    agent: str, root: Path, runtime_source: Path | None
) -> dict[str, object]:
    if root.exists():
        raise ExperimentError(f"experiment root must not exist: {root}")
    if agent not in {"fixture", "pi", "prime-agent"}:
        raise ExperimentError("agent must be fixture, pi, or prime-agent")
    source = runtime_source or (PROFILES / "runtime-fixture.json")
    runtime = load_runtime_manifest(source)
    if runtime.model["connector"] != _expected_connector(agent):
        raise ExperimentError("runtime model connector does not match selected agent")
    root.mkdir(parents=True)
    runtime_path = root / "runtime.json"
    atomic_write(
        runtime_path, (canonical_json(runtime.document) + "\n").encode("ascii")
    )
    runtime = load_runtime_manifest(runtime_path)
    seed, remote, artifact = _initialize_repository(root)
    candidate = load_candidate(seed)
    conformance = run_conformance(runtime_path, seed, allow_fixture=agent == "fixture")
    atomic_write(
        root / "conformance.json",
        (canonical_json(conformance) + "\n").encode("ascii"),
    )
    proposal_command, executor_command = _commands(agent)
    receipts = root / "receipts"
    state = root / "state"
    development_tasks = _tasks(FIXTURES / "development-tasks.json")
    request = _request(
        artifact,
        proposal_command=proposal_command,
        tasks=development_tasks,
        runtime=runtime,
    )
    candidate_paths = ["harness.json", *sorted(candidate.paths.values())]
    with _configured_environment(
        agent=agent,
        runtime_path=runtime_path,
        runtime=runtime,
        remote=remote,
        receipts=receipts,
        runner_command=executor_command,
        candidate_paths=candidate_paths,
    ):
        development = run_population_driver(canonical_json(request), state)
        if development["status"] == "pending_round":
            raise ExperimentError(
                "development has an explicit pending intent; inspect and retry before final"
            )
        final = run_final_assay(
            population_root(state),
            development_experiment_id=str(development["experiment_id"]),
            tasks=_tasks(FIXTURES / "final-tasks.json"),
            final_draw={"denominator": 1, "numerator": 0},
            runner_command=[sys.executable, str(GIT_ADAPTER)],
            evaluator_command=[sys.executable, str(EVALUATOR)],
            runner_timeout=600,
            evaluator_timeout=30,
            runtime=runtime,
            receipt_root=receipts,
            budget=_budget(),
        )
        verified = verify_population_driver(state)
    report = {
        "agent": agent,
        "conformance_id": conformance["conformance_id"],
        "development": development,
        "final": final,
        "runtime_id": runtime.runtime_id,
        "schema": "evolutionary-harness-experiment-v1",
        "verified": verified,
    }
    atomic_write(
        root / "experiment-report.json",
        (canonical_json(report) + "\n").encode("ascii"),
    )
    return report


def _run_receipt_binding(
    run: object,
    *,
    receipt_root: Path,
    runtime: RuntimeManifest,
    manifests: dict[str, str],
) -> str:
    if type(run) is not dict:
        raise ExperimentError("Controller harness run is malformed")
    candidate_id = run.get("candidate_id")
    task = run.get("task")
    forecast = run.get("forecast")
    runner = run.get("runner")
    if (
        type(candidate_id) is not str
        or candidate_id not in manifests
        or type(task) is not dict
        or type(forecast) is not dict
        or set(forecast) != {"entropy", "outcomes"}
        or type(runner) is not dict
    ):
        raise ExperimentError("Controller harness run is incomplete")
    submission = runner.get("submission")
    if type(submission) is not dict:
        raise ExperimentError("Controller harness submission is malformed")
    metadata = submission.get(EVIDENCE_KEY)
    if type(metadata) is not dict or set(metadata) != {
        "manifest_id",
        "receipt",
        "runtime_id",
    }:
        raise ExperimentError("Controller harness receipt metadata is malformed")
    if (
        metadata["manifest_id"] != manifests[candidate_id]
        or metadata["runtime_id"] != runtime.runtime_id
        or type(metadata["receipt"]) is not dict
    ):
        raise ExperimentError("Controller harness metadata changed identity")
    case_id = task.get("case_id")
    task_input = task.get("input")
    if type(case_id) is not str or type(task_input) is not dict:
        raise ExperimentError("Controller harness task is malformed")
    reference = cast(dict[str, object], metadata["receipt"])
    receipt = load_receipt(reference, receipt_root)
    clean_submission = {
        name: value for name, value in submission.items() if name != EVIDENCE_KEY
    }
    verify_receipt_binding(
        receipt,
        candidate_id=candidate_id,
        case_id=case_id,
        task=task_input,
        manifest_id=manifests[candidate_id],
        runtime=runtime,
        forecast={"outcomes": forecast["outcomes"]},
        submission=clean_submission,
    )
    digest = reference.get("sha256")
    if type(digest) is not str:
        raise ExperimentError("Controller harness receipt digest is malformed")
    return digest


def _load_bundle(
    reference: object, receipt_root: Path
) -> tuple[dict[str, object], str]:
    if type(reference) is not dict or set(reference) != {"sha256", "uri"}:
        raise ExperimentError("final assay receipt reference is malformed")
    digest = reference["sha256"]
    if (
        type(digest) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ExperimentError("final assay receipt digest is malformed")
    path = receipt_root / f"{digest}.json"
    if reference["uri"] != path.as_uri() or path.is_symlink() or not path.is_file():
        raise ExperimentError("final assay receipt path is unsafe")
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != digest:
        raise ExperimentError("final assay receipt digest does not match")
    try:
        text = source.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ExperimentError("final assay receipt must be ASCII JSON") from exc
    document = decode_json_object(text, ExperimentError)
    if text != canonical_json(document) + "\n":
        raise ExperimentError("final assay receipt is not canonical")
    return document, digest


def _verify_receipts(
    root: Path,
    runtime: RuntimeManifest,
    state: PopulationState,
    manifests: dict[str, str],
    final_run: dict[str, object],
) -> tuple[int, int]:
    receipt_root = root / "receipts"
    if not receipt_root.is_dir() or receipt_root.is_symlink():
        raise ExperimentError("harness receipt directory is absent or unsafe")
    expected_run_digests: list[str] = []
    driver_path = root / "state" / "driver.jsonl"
    driver_lines = driver_path.read_text(encoding="utf-8").splitlines()
    if not driver_lines:
        raise ExperimentError("Population Driver ledger is empty")
    header = decode_json_object(driver_lines[0], ExperimentError)
    configuration = header.get("configuration")
    if type(configuration) is not dict:
        raise ExperimentError("Population Driver configuration is malformed")
    generation = configuration.get("generation")
    population = configuration.get("population")
    development_tasks = _tasks(FIXTURES / "development-tasks.json")
    if (
        type(generation) is not dict
        or generation.get("tasks") != development_tasks
        or type(population) is not dict
        or type(population.get("experiment")) is not dict
    ):
        raise ExperimentError("reference development task set does not replay")
    development_experiment = cast(dict[str, object], population["experiment"])
    expected_development_task_set = canonical_digest(
        {
            "evaluation": generation["evaluation"],
            "task_set_schema": "population-driver-task-set-v1",
            "tasks": development_tasks,
        }
    )
    if (
        development_experiment.get("task_set_id") != expected_development_task_set
        or development_experiment.get("runtime_id") != runtime.runtime_id
        or development_experiment.get("role") != "development"
    ):
        raise ExperimentError("reference development experiment identity changed")
    for line in driver_lines[1:]:
        record = decode_json_object(line, ExperimentError)
        controller = read_receipt(root / "state", record.get("controller_receipt"))
        result = controller.get("controller_result")
        if type(result) is not dict or type(result.get("cases")) is not list:
            raise ExperimentError("Controller receipt omitted case traces")
        for trace in result["cases"]:
            if type(trace) is not dict:
                raise ExperimentError("Controller case trace is malformed")
            for name in ("incumbent_run", "challenger_run"):
                expected_run_digests.append(
                    _run_receipt_binding(
                        trace.get(name),
                        receipt_root=receipt_root,
                        runtime=runtime,
                        manifests=manifests,
                    )
                )

    run = cast(dict[str, object], final_run["run"])
    evidence = cast(dict[str, object], final_run["evidence"])
    bundle, bundle_digest = _load_bundle(evidence.get("evidence_receipt"), receipt_root)
    if set(bundle) != {
        "allocation_record_id",
        "candidate_id",
        "cases",
        "evaluator_id",
        "final_assay_schema",
        "runtime_id",
    }:
        raise ExperimentError("final assay receipt has the wrong keys")
    if (
        bundle["final_assay_schema"] != "evolutionary-harness-final-assay-v1"
        or bundle["runtime_id"] != runtime.runtime_id
        or bundle["candidate_id"] != run["candidate_id"]
        or bundle["allocation_record_id"]
        != cast(dict[str, object], run["seed"])["allocation_record_id"]
    ):
        raise ExperimentError("final assay receipt changed sealed identities")
    tasks = _tasks(FIXTURES / "final-tasks.json")
    experiment = state.experiments[str(run["experiment_id"])]
    expected_task_set = canonical_digest(
        {"task_set_schema": "protected-harness-final-v1", "tasks": tasks}
    )
    if (
        experiment["task_set_id"] != expected_task_set
        or experiment["case_count"] != len(tasks)
        or bundle["evaluator_id"] != experiment["evaluator_id"]
    ):
        raise ExperimentError("final assay experiment identity does not replay")
    cases = bundle["cases"]
    if type(cases) is not list or len(cases) != len(tasks):
        raise ExperimentError("final assay receipt cases are malformed")
    final_receipts: list[dict[str, object]] = []
    for case, task in zip(cases, tasks, strict=True):
        expected_keys = {
            "case_id",
            "evidence",
            "forecast",
            "outcome",
            "passed",
            "receipt",
            "result_sha256",
            "safety_passed",
            "submission",
            "target_probability",
        }
        if type(case) is not dict or set(case) != expected_keys:
            raise ExperimentError("final assay case is malformed")
        if case["case_id"] != task.get("case_id") or type(case["receipt"]) is not dict:
            raise ExperimentError("final assay case changed task identity")
        receipt = load_receipt(case["receipt"], receipt_root)
        task_input = task.get("input")
        if type(task_input) is not dict:
            raise ExperimentError("protected final task is malformed")
        candidate_id = str(run["candidate_id"])
        verify_receipt_binding(
            receipt,
            candidate_id=candidate_id,
            case_id=str(task["case_id"]),
            task=task_input,
            manifest_id=manifests[candidate_id],
            runtime=runtime,
            forecast=case["forecast"],
            submission=case["submission"],
        )
        completion = cast(dict[str, object], receipt["completion"])
        if case["result_sha256"] != completion["result_sha256"]:
            raise ExperimentError("final assay result digest does not match its run")
        forecast = case["forecast"]
        if type(forecast) is not dict or type(forecast.get("outcomes")) is not list:
            raise ExperimentError("final assay forecast is malformed")
        probabilities = {
            item.get("outcome"): item.get("probability")
            for item in forecast["outcomes"]
            if type(item) is dict
        }
        if probabilities.get(case["outcome"]) != case["target_probability"]:
            raise ExperimentError("final assay target probability does not replay")
        digest = cast(dict[str, object], case["receipt"]).get("sha256")
        if type(digest) is not str:
            raise ExperimentError("final assay run receipt digest is malformed")
        expected_run_digests.append(digest)
        final_receipts.append(receipt)
    passed = sum(int(case["passed"] is True) for case in cases)
    safety_failures = sum(int(case["safety_passed"] is not True) for case in cases)
    expected_evidence = {
        "behavior_distribution": [1.0 - passed / len(cases), passed / len(cases)],
        "cost": aggregate_cost(final_receipts),
        "evidence_receipt": evidence["evidence_receipt"],
        "information_model": None,
        "protected_passed": safety_failures == 0,
        "target_probabilities": [case["target_probability"] for case in cases],
        "task": {
            "case_count": len(cases),
            "passed_count": passed,
            "safety_failures": safety_failures,
        },
    }
    if evidence != expected_evidence:
        raise ExperimentError("final Population evidence does not replay from receipts")

    actual_run_digests: set[str] = set()
    actual_bundle_digests: set[str] = set()
    entries = sorted(receipt_root.iterdir())
    for path in entries:
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise ExperimentError("harness receipt directory contains an unsafe entry")
        source = path.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        if path.name != f"{digest}.json":
            raise ExperimentError("harness receipt filename does not match content")
        document = decode_json_object(source.decode("ascii"), ExperimentError)
        if source.decode("ascii") != canonical_json(document) + "\n":
            raise ExperimentError("harness receipt is not canonical")
        if document.get("receipt_schema") == "evolutionary-harness-run-receipt-v1":
            load_receipt({"sha256": digest, "uri": path.as_uri()}, receipt_root)
            actual_run_digests.add(digest)
        elif (
            document.get("final_assay_schema") == "evolutionary-harness-final-assay-v1"
        ):
            actual_bundle_digests.add(digest)
        else:
            raise ExperimentError("unknown harness receipt schema")
    if actual_run_digests != set(expected_run_digests):
        raise ExperimentError(
            "harness run receipt set does not match authenticated runs"
        )
    if actual_bundle_digests != {bundle_digest}:
        raise ExperimentError("final assay receipt set does not match Population")
    return len(actual_run_digests), len(actual_bundle_digests)


def _verify_conformance(
    root: Path, runtime: RuntimeManifest, manifests: dict[str, str]
) -> None:
    path = root / "conformance.json"
    if path.is_symlink() or not path.is_file():
        raise ExperimentError("kernel conformance receipt is absent or unsafe")
    source = path.read_text(encoding="utf-8")
    document = decode_json_object(source, ExperimentError)
    if source != canonical_json(document) + "\n" or set(document) != {
        "candidate_manifest_id",
        "checks",
        "conformance_id",
        "isolation_enforced",
        "resources",
        "runtime_id",
        "schema",
    }:
        raise ExperimentError("kernel conformance receipt is malformed")
    body = {name: value for name, value in document.items() if name != "conformance_id"}
    if (
        document["conformance_id"] != canonical_digest(body)
        or document["schema"] != "evolutionary-harness-conformance-v1"
        or document["runtime_id"] != runtime.runtime_id
        or document["candidate_manifest_id"] not in set(manifests.values())
        or document["isolation_enforced"] is not runtime.isolation_enforced
        or document["checks"]
        != [
            "boot",
            "execute",
            "snapshot",
            "restore",
            "interrupt",
            "timeout",
            "cleanup",
            "shutdown",
        ]
        or type(document["resources"]) is not list
        or not document["resources"]
    ):
        raise ExperimentError("kernel conformance receipt does not replay")


def verify_experiment(root: Path) -> dict[str, object]:
    root = root.expanduser().absolute()
    runtime = load_runtime_manifest(root / "runtime.json")
    driver = verify_population_driver(root / "state")
    state = load_state(population_root(root / "state"))
    if not state.final_evaluation_started:
        raise ExperimentError("Population is not sealed by final evidence")
    final_runs = [
        body
        for body in state.runs
        if state.experiments[
            str(cast(dict[str, object], body["run"])["experiment_id"])
        ]["role"]
        == "final"
    ]
    if len(final_runs) != 1:
        raise ExperimentError("experiment must contain exactly one final run")
    expected_repository = str((root / "candidate.git").absolute())
    manifests: dict[str, str] = {}
    old_repository = os.environ.get("METERING_GIT_REPOSITORY")
    try:
        os.environ["METERING_GIT_REPOSITORY"] = expected_repository
        with tempfile.TemporaryDirectory(
            prefix="metering-harness-verify-"
        ) as temporary:
            temporary_root = Path(temporary)
            for index, candidate in enumerate(state.candidates.values()):
                candidate_id = str(candidate["candidate_id"])
                artifact = cast(dict[str, object], candidate["artifact"])
                if artifact.get("repository") != expected_repository:
                    raise ExperimentError("candidate identifies another Git repository")
                checkout = temporary_root / str(index)
                clone_verified(artifact, checkout)
                loaded = load_candidate(
                    checkout, entrypoint=str(artifact["entrypoint"])
                )
                assert_candidate_compatible(
                    runtime,
                    (checkout / loaded.paths["dependency_lock"]).read_bytes(),
                )
                manifests[candidate_id] = loaded.manifest_id
    finally:
        if old_repository is None:
            os.environ.pop("METERING_GIT_REPOSITORY", None)
        else:
            os.environ["METERING_GIT_REPOSITORY"] = old_repository
    _verify_conformance(root, runtime, manifests)
    run_receipts, bundles = _verify_receipts(
        root,
        runtime,
        state,
        manifests,
        cast(dict[str, object], final_runs[0]),
    )
    if run_receipts < 1 or bundles != 1:
        raise ExperimentError("experiment receipt set is incomplete")
    return {
        "candidate_count": len(state.candidates),
        "driver": driver,
        "final_run_count": len(final_runs),
        "harness_receipt_count": run_receipts,
        "runtime_id": runtime.runtime_id,
        "schema": "evolutionary-harness-verification-v1",
        "status": "verified",
    }


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(arguments) == 2 and arguments[0] == "verify":
            result = verify_experiment(Path(arguments[1]))
        elif len(arguments) == 2 and arguments[0] == "fixture":
            result = run_experiment("fixture", Path(arguments[1]).absolute(), None)
        elif len(arguments) == 3 and arguments[0] in {"pi", "prime-agent"}:
            result = run_experiment(
                arguments[0], Path(arguments[1]).absolute(), Path(arguments[2])
            )
        else:
            raise ExperimentError(
                "usage: experiment.py fixture NEW_ROOT | "
                "{pi|prime-agent} NEW_ROOT RUNTIME.json | verify ROOT"
            )
    except (
        ExperimentError,
        FinalAssayError,
        GitCandidateError,
        HarnessProtocolError,
        HarnessReceiptError,
        OSError,
        RuntimeManifestError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    write_document(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
