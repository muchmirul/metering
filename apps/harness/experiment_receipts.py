"""Read-only binding and closure checks for harness experiment receipts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

from apps._support.wire import canonical_digest, canonical_json, decode_json_object
from apps.coding_agent.evaluator import evaluation_cost
from apps.harness.experiment_config import ExperimentError
from apps.harness.harness_runner import EVIDENCE_KEY
from apps.harness.receipts import aggregate_cost, load_receipt, verify_receipt_binding
from apps.harness.runtime_manifest import RuntimeManifest
from apps.harness.workspace import (
    WorkspaceError,
    changed_paths,
    decode_files,
    files_digest,
    normalize_policy,
    require_allowed_changes,
)
from apps.population.contract import RESOURCE_NAMES, PopulationState
from apps.population_driver.population_driver_state import read_receipt


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


def _verify_coding_kernel_evidence(
    evidence: object,
    *,
    task: dict[str, object],
    submission: dict[str, object],
    runtime: RuntimeManifest,
) -> tuple[bool, bool]:
    if type(evidence) is not dict or set(evidence) != {
        "assay_sha256",
        "cost",
        "isolation_enforced",
        "kernel_observations",
        "returncode",
        "runtime_id",
        "stderr_sha256",
        "stdout_sha256",
        "timed_out",
        "workspace_sha256",
    }:
        raise ExperimentError("coding evaluator evidence is malformed")
    task_input = task.get("input")
    workspace = submission.get("_metering_coding_workspace")
    if (
        type(task_input) is not dict
        or type(task_input.get("assay")) is not dict
        or type(task_input.get("workspace")) is not dict
        or type(workspace) is not dict
    ):
        raise ExperimentError("coding evaluator workspace binding is malformed")
    task_workspace = cast(dict[str, object], task_input["workspace"])
    try:
        policy = normalize_policy(task_workspace["policy"])
        base_files = decode_files(
            task_workspace["files"],
            max_files=int(policy["max_files"]),
            max_bytes=int(policy["max_bytes"]),
        )
        files = decode_files(
            workspace["files"],
            max_files=int(policy["max_files"]),
            max_bytes=int(policy["max_bytes"]),
        )
        paths = changed_paths(base_files, files)
        require_allowed_changes(paths, cast(list[str], policy["allowed_write_paths"]))
    except (KeyError, TypeError, WorkspaceError) as exc:
        raise ExperimentError("coding evaluator workspace does not replay") from exc
    body = {"changed_paths": paths, "files": files}
    if (
        set(workspace) != {"base_sha256", "changed_paths", "files", "sha256"}
        or workspace["base_sha256"] != files_digest(base_files)
        or workspace["changed_paths"] != paths
        or workspace["sha256"] != canonical_digest(body)
        or evidence["workspace_sha256"] != files_digest(files)
        or evidence["assay_sha256"] != canonical_digest(task_input["assay"])
        or evidence["runtime_id"] != runtime.runtime_id
        or evidence["isolation_enforced"] is not runtime.isolation_enforced
    ):
        raise ExperimentError("coding evaluator evidence changed identity")
    returncode = evidence["returncode"]
    if (
        (returncode is not None and type(returncode) is not int)
        or type(evidence["timed_out"]) is not bool
        or type(evidence["stderr_sha256"]) is not str
        or type(evidence["stdout_sha256"]) is not str
        or any(
            len(cast(str, evidence[name])) != 64
            or any(
                character not in "0123456789abcdef"
                for character in cast(str, evidence[name])
            )
            for name in ("stderr_sha256", "stdout_sha256")
        )
    ):
        raise ExperimentError("coding evaluator execution evidence is malformed")
    observations = evidence["kernel_observations"]
    expected_keys = {
        "cpu_microseconds",
        "memory_peak_bytes",
        "processes_peak",
        "source",
        "storage_write_bytes",
        "wall_milliseconds",
    }
    if type(observations) is not list or not observations:
        raise ExperimentError("coding evaluator omitted kernel observations")
    for observation in observations:
        if type(observation) is not dict or set(observation) != expected_keys:
            raise ExperimentError("coding evaluator kernel observation is malformed")
        for name in (
            "cpu_microseconds",
            "memory_peak_bytes",
            "processes_peak",
            "storage_write_bytes",
            "wall_milliseconds",
        ):
            value = observation[name]
            if value is not None and (type(value) is not int or value < 0):
                raise ExperimentError(
                    "coding evaluator kernel observation is malformed"
                )
        if (
            type(observation["wall_milliseconds"]) is not int
            or type(observation["source"]) is not str
            or not observation["source"]
        ):
            raise ExperimentError("coding evaluator kernel observation is malformed")
        if runtime.isolation_enforced:
            required = {
                "cpu": "cpu_microseconds",
                "memory": "memory_peak_bytes",
                "processes": "processes_peak",
                "storage": "storage_write_bytes",
                "wall": "wall_milliseconds",
            }
            if observation["source"] != "cgroup-v2" or any(
                observation[required[name]] is None
                for name in runtime.required_observations
            ):
                raise ExperimentError(
                    "coding evaluator omitted required isolation observations"
                )
    if evidence["cost"] != evaluation_cost(
        cast(list[dict[str, object]], observations), runtime
    ):
        raise ExperimentError("coding evaluator cost does not replay")
    passed = returncode == 0 and evidence["timed_out"] is False
    safety_passed = (
        evidence["isolation_enforced"] is True if runtime.isolation_enforced else True
    )
    return passed, safety_passed


def _verify_coding_observer_trace(
    trace: dict[str, object], runtime: RuntimeManifest
) -> None:
    task = trace.get("task")
    observer = trace.get("observer_evaluation")
    if type(task) is not dict or type(observer) is not dict:
        raise ExperimentError("coding Controller trace omitted evaluator evidence")
    results = observer.get("results")
    if type(results) is not list:
        raise ExperimentError("coding Controller evaluator results are malformed")
    by_candidate = {
        item.get("candidate_id"): item for item in results if type(item) is dict
    }
    for name in ("incumbent_run", "challenger_run"):
        run = trace.get(name)
        if type(run) is not dict or type(run.get("runner")) is not dict:
            raise ExperimentError("coding Controller run is malformed")
        candidate_id = run.get("candidate_id")
        submission = cast(dict[str, object], run["runner"]).get("submission")
        result = by_candidate.get(candidate_id)
        if type(submission) is not dict or type(result) is not dict:
            raise ExperimentError("coding evaluator candidate result is absent")
        passed, safety_passed = _verify_coding_kernel_evidence(
            result.get("evidence"),
            task=task,
            submission=submission,
            runtime=runtime,
        )
        if (
            set(result)
            != {"candidate_id", "evidence", "outcome", "passed", "safety_passed"}
            or result["passed"] is not passed
            or result["safety_passed"] is not safety_passed
            or result["outcome"] != ("pass" if passed else "fail")
        ):
            raise ExperimentError("coding evaluator result does not replay")


def verify_experiment_receipts(
    root: Path,
    runtime: RuntimeManifest,
    state: PopulationState,
    manifests: dict[str, str],
    final_run: dict[str, object],
    *,
    development_tasks: list[dict[str, object]],
    final_tasks: list[dict[str, object]],
    verify_coding_evidence: bool,
) -> tuple[int, int]:
    receipt_root = root / "receipts"
    if not receipt_root.is_dir() or receipt_root.is_symlink():
        raise ExperimentError("harness receipt directory is absent or unsafe")
    development_digests, retry_effects = _verify_development_receipts(
        root,
        receipt_root,
        runtime,
        manifests,
        development_tasks,
        verify_coding_evidence,
    )
    final_digests, bundle_digest = _verify_final_receipts(
        receipt_root,
        runtime,
        state,
        manifests,
        final_run,
        final_tasks,
        verify_coding_evidence,
    )
    return _verify_receipt_closure(
        root,
        receipt_root,
        development_digests + final_digests,
        bundle_digest,
        retry_effects,
    )


def _verify_development_receipts(
    root: Path,
    receipt_root: Path,
    runtime: RuntimeManifest,
    manifests: dict[str, str],
    development_tasks: list[dict[str, object]],
    verify_coding_evidence: bool,
) -> tuple[list[str], dict[str, tuple[str, str]]]:
    """Authenticate Controller traces and derive explicit retry-effect identities."""
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
    expected_retry_effects: dict[str, tuple[str, str]] = {}
    for line in driver_lines[1:]:
        record = decode_json_object(line, ExperimentError)
        attempts = record.get("attempts")
        intent_id = record.get("intent_id")
        if type(attempts) is not list or type(intent_id) is not str:
            raise ExperimentError("Driver round attempts are malformed")
        for index, attempt in enumerate(attempts[:-1]):
            next_attempt = attempts[index + 1]
            if (
                type(attempt) is not dict
                or type(attempt.get("attempt_id")) is not str
                or type(next_attempt) is not dict
                or type(next_attempt.get("reason")) is not str
            ):
                raise ExperimentError("Driver retry attempt is malformed")
            expected_retry_effects[str(attempt["attempt_id"])] = (
                intent_id,
                str(next_attempt["reason"]),
            )
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
            if verify_coding_evidence:
                _verify_coding_observer_trace(trace, runtime)

    return expected_run_digests, expected_retry_effects


def _verify_final_receipts(
    receipt_root: Path,
    runtime: RuntimeManifest,
    state: PopulationState,
    manifests: dict[str, str],
    final_run: dict[str, object],
    final_tasks: list[dict[str, object]],
    verify_coding_evidence: bool,
) -> tuple[list[str], str]:
    """Replay final allocation, outcomes, and costs against the sealed Population."""
    expected_run_digests: list[str] = []
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
    allocation_id = bundle["allocation_record_id"]
    if type(allocation_id) is not str:
        raise ExperimentError("final allocation identity is malformed")
    allocation_record = state.record(allocation_id)
    if allocation_record is None:
        raise ExperimentError("final allocation record is absent")
    allocation_body = cast(dict[str, object], allocation_record["body"])
    allocation_request = cast(dict[str, object], allocation_body["request"])
    archive_record = state.record(str(allocation_request["archive_record_id"]))
    if archive_record is None:
        raise ExperimentError("final allocation archive is absent")
    trailing_allocations = [
        record_id
        for record_id, _ in state.allocations
        if int(cast(dict[str, object], state.record(record_id))["sequence"])
        > int(archive_record["sequence"])
    ]
    if trailing_allocations != [allocation_id]:
        raise ExperimentError("final allocation is not the unique sealed allocation")
    tasks = final_tasks
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
        if verify_coding_evidence:
            passed_result, safety_result = _verify_coding_kernel_evidence(
                case["evidence"],
                task=task,
                submission=cast(dict[str, object], case["submission"]),
                runtime=runtime,
            )
            if (
                case["passed"] is not passed_result
                or case["safety_passed"] is not safety_result
                or case["outcome"] != ("pass" if passed_result else "fail")
            ):
                raise ExperimentError("final coding evaluator result does not replay")
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
    final_cost = aggregate_cost(final_receipts)
    for case in cases:
        case_evidence = cast(dict[str, object], case["evidence"])
        evaluator_cost = case_evidence.get("cost")
        if evaluator_cost is None:
            continue
        if type(evaluator_cost) is not dict or set(evaluator_cost) != set(
            RESOURCE_NAMES
        ):
            raise ExperimentError("final evaluator cost is malformed")
        for name in RESOURCE_NAMES:
            value = evaluator_cost[name]
            if type(value) is not int or value < 0:
                raise ExperimentError("final evaluator cost is malformed")
            final_cost[name] += value
    expected_evidence = {
        "behavior_distribution": [1.0 - passed / len(cases), passed / len(cases)],
        "cost": final_cost,
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

    return expected_run_digests, bundle_digest


def _verify_receipt_closure(
    root: Path,
    receipt_root: Path,
    expected_run_digests: list[str],
    bundle_digest: str,
    expected_retry_effects: dict[str, tuple[str, str]],
) -> tuple[int, int]:
    """Reject unbound effects, missing receipts, and downgraded retry reservations."""
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
    retry_root = root / "state" / "retry-effects"
    retry_receipts: set[str] = set()
    actual_retry_ids: set[str] = set()
    if retry_root.exists():
        if retry_root.is_symlink() or not retry_root.is_dir():
            raise ExperimentError("harness retry-effects directory is unsafe")
        for path in sorted(retry_root.iterdir()):
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ExperimentError("harness retry-effects entry is unsafe")
            source = path.read_text(encoding="ascii")
            document = decode_json_object(source, ExperimentError)
            if source != canonical_json(document) + "\n" or set(document) != {
                "attempt_id",
                "intent_id",
                "receipt_sha256",
                "retry_effects_schema",
            }:
                raise ExperimentError("harness retry-effects receipt is malformed")
            attempt_id = document["attempt_id"]
            digests = document["receipt_sha256"]
            schema = document["retry_effects_schema"]
            expected_identity = expected_retry_effects.get(cast(str, attempt_id))
            if (
                type(schema) is not str
                or schema
                not in {
                    "evolutionary-harness-retry-effects-v1",
                    "evolutionary-harness-retry-effects-v2",
                }
                or type(attempt_id) is not str
                or path.name != f"{attempt_id}.json"
                or expected_identity is None
                or expected_identity[0] != document["intent_id"]
                or type(digests) is not list
                or digests != sorted(set(digests))
                or any(
                    type(digest) is not str
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                    for digest in digests
                )
            ):
                raise ExperimentError("harness retry-effects identity is malformed")
            marker = "\nretry-effects-sha256:"
            if schema == "evolutionary-harness-retry-effects-v2":
                receipt_id = hashlib.sha256(source.encode("ascii")).hexdigest()
                suffix = f"{marker}{receipt_id}"
                if (
                    not expected_identity[1].endswith(suffix)
                    or not expected_identity[1][: -len(suffix)].strip()
                ):
                    raise ExperimentError(
                        "harness retry-effects receipt is not bound to retry"
                    )
            elif marker in expected_identity[1]:
                raise ExperimentError("harness retry-effects schema was downgraded")
            actual_retry_ids.add(attempt_id)
            retry_receipts.update(cast(list[str], digests))
    if actual_retry_ids != set(expected_retry_effects):
        raise ExperimentError("harness retry-effects receipt set is incomplete")
    if not retry_receipts <= actual_run_digests:
        raise ExperimentError("harness retry-effects reference unknown receipts")
    if actual_run_digests != set(expected_run_digests) | retry_receipts:
        raise ExperimentError(
            "harness run receipt set does not match authenticated or retry effects"
        )
    if actual_bundle_digests != {bundle_digest}:
        raise ExperimentError("final assay receipt set does not match Population")
    return len(actual_run_digests), len(actual_bundle_digests)
