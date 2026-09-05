"""Offline solution experiment verification; never launches a model or an assay."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import cast

from apps._support.wire import canonical_digest, decode_json_object
from apps.agent_protocol import decode_agent_artifact
from apps.coding_agent.candidate_runner import RECEIPT_SCHEMA
from apps.coding_agent.experiment_artifacts import (
    canonical_document,
    load_protected_final_tasks,
    verify_harness_provenance,
)
from apps.coding_agent.experiment_config import (
    SolutionExperimentError,
    coding_runtime_identity,
)
from apps.coding_agent.experiment_receipts import (
    equivalent_evaluator_ids,
    receipt_files,
    retry_effect_receipts,
    verified_recorded_evaluator_command,
    verify_bound_evaluation_receipt,
)
from apps.coding_agent.final_assay import BUNDLE_SCHEMA
from apps.coding_agent.harness_workspace_editor import load_harness_descriptor
from apps.coding_agent.protocol import load_task_profile, task_documents
from apps.harness.protocol import load_candidate
from apps.harness.runtime_manifest import (
    RuntimeManifest,
    assert_candidate_compatible,
    load_runtime_manifest,
)
from apps.harness.workspace import (
    WorkspaceError,
    changed_paths,
    files_digest,
    require_allowed_changes,
    snapshot_directory,
)
from apps.population.contract import RESOURCE_NAMES, PopulationState, load_state
from apps.population_driver.paths import population_root
from apps.population_driver.runtime import verify_population_driver
from artifacts.git.git_repository import clone_verified, run_git


def _expected_final_selection(
    state: PopulationState,
    development_experiment_id: str,
    tie_draw: dict[str, int],
) -> tuple[str, dict[str, int], list[str], str]:
    archive_id = state.latest_archive_by_experiment.get(development_experiment_id)
    if archive_id is None:
        raise SolutionExperimentError("coding development archive is absent")
    archive = cast(dict[str, object], state.record(archive_id)["body"])
    members = cast(list[dict[str, object]], archive["members"])
    if not members:
        raise SolutionExperimentError("coding development archive is empty")
    best_rate = max(
        float(cast(dict[str, object], member["task"])["rate"]) for member in members
    )
    best_reliability = max(
        float(member["reliability"])
        for member in members
        if float(cast(dict[str, object], member["task"])["rate"]) == best_rate
    )
    eligible = sorted(
        str(member["candidate_id"])
        for member in members
        if float(cast(dict[str, object], member["task"])["rate"]) == best_rate
        and float(member["reliability"]) == best_reliability
    )
    tie_index = (int(tie_draw["numerator"]) * len(eligible)) // int(
        tie_draw["denominator"]
    )
    selected = eligible[tie_index]
    all_candidates = sorted(str(member["candidate_id"]) for member in members)
    allocation_draw = {
        "denominator": len(all_candidates),
        "numerator": all_candidates.index(selected),
    }
    return selected, allocation_draw, eligible, archive_id


def verify_experiment(root: Path) -> dict[str, object]:
    root = root.expanduser().absolute()
    profile = load_task_profile(root / "task.json", allow_legacy_inline_final=True)
    final_tasks = load_protected_final_tasks(root, profile)
    runtime = load_runtime_manifest(root / "runtime.json")
    descriptor = load_harness_descriptor(
        root / "selected-harness.json", allow_legacy=True
    )
    verify_harness_provenance(root, descriptor)
    coding_runtime_id = coding_runtime_identity(profile, runtime, descriptor)
    driver = verify_population_driver(root / "state")
    state = load_state(population_root(root / "state"))
    if not state.final_evaluation_started:
        raise SolutionExperimentError("coding Population is not final-sealed")
    driver_lines = (
        (root / "state" / "driver.jsonl").read_text(encoding="utf-8").splitlines()
    )
    if not driver_lines:
        raise SolutionExperimentError("coding driver ledger is empty")
    retry_mutations, retry_evaluations = retry_effect_receipts(root, driver_lines)
    driver_header = decode_json_object(driver_lines[0], SolutionExperimentError)
    configuration = driver_header.get("configuration")
    if type(configuration) is not dict:
        raise SolutionExperimentError("coding driver configuration is malformed")
    generation = configuration.get("generation")
    population_configuration = configuration.get("population")
    if (
        type(generation) is not dict
        or generation.get("tasks") != task_documents(profile, "development")
        or type(population_configuration) is not dict
        or type(population_configuration.get("experiment")) is not dict
        or cast(dict[str, object], population_configuration["experiment"]).get(
            "runtime_id"
        )
        != coding_runtime_id
    ):
        raise SolutionExperimentError("coding task profile does not match driver state")
    evaluator_command = verified_recorded_evaluator_command(generation)
    evaluator_ids = equivalent_evaluator_ids(evaluator_command)
    _verify_selected_harness(root, runtime, descriptor)
    candidate_files, candidate_snapshots = _verify_solution_candidates(
        root, state, profile
    )
    mutation_count = _verify_mutation_receipts(
        root,
        state,
        profile,
        runtime,
        descriptor,
        coding_runtime_id,
        candidate_files,
        candidate_snapshots,
        retry_mutations,
    )
    evaluation_receipts, final_run, expected_development = _verify_development_receipts(
        root,
        state,
        profile,
        runtime,
        coding_runtime_id,
        candidate_files,
    )
    bundle, expected_final, final_candidate_id = _verify_final_cases(
        root,
        state,
        runtime,
        final_run,
        final_tasks,
        candidate_files,
        evaluation_receipts,
    )
    if (
        not retry_evaluations <= set(evaluation_receipts)
        or set(evaluation_receipts)
        != expected_development | expected_final | retry_evaluations
    ):
        raise SolutionExperimentError(
            "coding evaluation receipt set does not match authenticated runs or retry effects"
        )
    _verify_final_selection(
        state,
        profile,
        coding_runtime_id,
        str(driver["experiment_id"]),
        final_run,
        final_tasks,
        bundle,
        final_candidate_id,
        evaluator_ids,
    )
    selected_id = _verify_selected_solution(root, state, profile, final_run)
    return {
        "candidate_count": len(state.candidates),
        "coding_runtime_id": coding_runtime_id,
        "driver": driver,
        "evaluation_receipt_count": len(evaluation_receipts),
        "final_run_count": 1,
        "mutation_receipt_count": mutation_count,
        "schema": "darwinian-coding-verification-v1",
        "selected_candidate_id": selected_id,
        "status": "verified",
        "task_id": profile["task_id"],
    }


def _verify_selected_harness(
    root: Path, runtime: RuntimeManifest, descriptor: dict[str, object]
) -> None:
    """Bind the localized harness and its conformance evidence."""
    expected_harness_repository = str((root / "harness.git").absolute())
    harness_artifact = cast(dict[str, object], descriptor["artifact"])
    if (
        descriptor["descriptor_schema"] == "selected-evolutionary-harness-v1"
        and harness_artifact.get("repository") != expected_harness_repository
    ):
        raise SolutionExperimentError(
            "legacy selected harness identifies another repository"
        )
    localized_harness_artifact = decode_agent_artifact(
        {**harness_artifact, "repository": expected_harness_repository}
    )
    previous_harness_repository = os.environ.get("METERING_GIT_REPOSITORY")
    try:
        os.environ["METERING_GIT_REPOSITORY"] = expected_harness_repository
        with tempfile.TemporaryDirectory(
            prefix="metering-harness-descriptor-verify-"
        ) as temporary:
            harness_checkout = Path(temporary) / "checkout"
            clone_verified(localized_harness_artifact, harness_checkout)
            harness_candidate = load_candidate(harness_checkout)
            assert_candidate_compatible(
                runtime,
                (
                    harness_checkout / harness_candidate.paths["dependency_lock"]
                ).read_bytes(),
            )
    finally:
        if previous_harness_repository is None:
            os.environ.pop("METERING_GIT_REPOSITORY", None)
        else:
            os.environ["METERING_GIT_REPOSITORY"] = previous_harness_repository
    if (
        harness_candidate.manifest_id != descriptor["manifest_id"]
        or descriptor["runtime_id"] != runtime.runtime_id
    ):
        raise SolutionExperimentError("selected harness identity does not replay")
    conformance = canonical_document(root / "conformance.json", "kernel conformance")
    conformance_body = {
        name: value for name, value in conformance.items() if name != "conformance_id"
    }
    if (
        conformance.get("schema") != "evolutionary-harness-conformance-v1"
        or conformance.get("conformance_id") != canonical_digest(conformance_body)
        or conformance.get("runtime_id") != runtime.runtime_id
        or conformance.get("candidate_manifest_id") != descriptor["manifest_id"]
        or conformance.get("isolation_enforced") is not runtime.isolation_enforced
    ):
        raise SolutionExperimentError("kernel conformance identity does not replay")


def _verify_solution_candidates(
    root: Path, state: PopulationState, profile: dict[str, object]
) -> tuple[dict[str, str], dict[str, list[dict[str, object]]]]:
    """Check immutable content and ancestry using disposable checkouts."""
    expected_solution_repository = str((root / "candidate.git").absolute())
    previous = os.environ.get("METERING_GIT_REPOSITORY")
    candidate_files: dict[str, str] = {}
    candidate_snapshots: dict[str, list[dict[str, object]]] = {}
    try:
        os.environ["METERING_GIT_REPOSITORY"] = expected_solution_repository
        with tempfile.TemporaryDirectory(prefix="metering-coding-verify-") as temporary:
            temporary_root = Path(temporary)
            for index, candidate in enumerate(state.candidates.values()):
                artifact = cast(dict[str, object], candidate["artifact"])
                if artifact.get("repository") != expected_solution_repository:
                    raise SolutionExperimentError(
                        "solution candidate identifies another repository"
                    )
                checkout = temporary_root / str(index)
                clone_verified(artifact, checkout)
                snapshot = snapshot_directory(checkout)
                candidate_id = str(candidate["candidate_id"])
                candidate_snapshots[candidate_id] = snapshot
                candidate_files[candidate_id] = files_digest(snapshot)
    finally:
        if previous is None:
            os.environ.pop("METERING_GIT_REPOSITORY", None)
        else:
            os.environ["METERING_GIT_REPOSITORY"] = previous
    for candidate_id, parents in state.candidate_parents.items():
        artifact = cast(dict[str, object], state.candidates[candidate_id]["artifact"])
        commit = str(artifact["commit"])
        actual_parents = (
            run_git(["show", "-s", "--format=%P", commit], cwd=root / "candidate.git")
            .strip()
            .split()
        )
        if not parents:
            expected = cast(dict[str, str], profile["repository"])["base_commit"]
            if (
                commit != expected
                or actual_parents
                != run_git(
                    ["show", "-s", "--format=%P", expected], cwd=root / "candidate.git"
                )
                .strip()
                .split()
            ):
                raise SolutionExperimentError("solution seed identity changed")
        else:
            if len(parents) != 1:
                raise SolutionExperimentError("solution mutation must have one parent")
            parent_artifact = cast(
                dict[str, object], state.candidates[parents[0]]["artifact"]
            )
            if actual_parents != [parent_artifact["commit"]]:
                raise SolutionExperimentError("solution Git lineage does not replay")
    return candidate_files, candidate_snapshots


def _verify_mutation_receipts(
    root: Path,
    state: PopulationState,
    profile: dict[str, object],
    runtime: RuntimeManifest,
    descriptor: dict[str, object],
    coding_runtime_id: str,
    candidate_files: dict[str, str],
    candidate_snapshots: dict[str, list[dict[str, object]]],
    retry_mutations: set[str],
) -> int:
    """Close mutation receipts against allowed descendants and explicit retries."""
    mutation_schema = (
        "darwinian-coding-mutation-receipt-v2"
        if descriptor["descriptor_schema"] == "selected-evolutionary-harness-v2"
        else "darwinian-coding-mutation-receipt-v1"
    )
    mutation_receipts = receipt_files(root / "mutation-receipts", mutation_schema)
    child_ids = [
        candidate_id
        for candidate_id, parents in state.candidate_parents.items()
        if parents
    ]
    mutation_matches: set[str] = set()
    expected_mutation_keys = {
        "base_files_sha256",
        "changed_paths",
        "completion",
        "goal_sha256",
        "harness_candidate_id",
        "harness_manifest_id",
        "receipt_schema",
        "result_files_sha256",
        "runtime_id",
    }
    if descriptor["descriptor_schema"] == "selected-evolutionary-harness-v2":
        expected_mutation_keys.add("coding_runtime_id")
    for digest, receipt in mutation_receipts.items():
        if set(receipt) != expected_mutation_keys:
            raise SolutionExperimentError("coding mutation receipt is malformed")
        if (
            receipt["runtime_id"] != runtime.runtime_id
            or receipt["harness_candidate_id"] != descriptor["candidate_id"]
            or receipt["harness_manifest_id"] != descriptor["manifest_id"]
            or (
                descriptor["descriptor_schema"] == "selected-evolutionary-harness-v2"
                and receipt["coding_runtime_id"] != coding_runtime_id
            )
        ):
            raise SolutionExperimentError("coding mutation receipt changed harness")
        completion = receipt["completion"]
        if type(completion) is not dict or set(completion) != {
            "actions",
            "input_tokens",
            "model_calls",
            "output_tokens",
            "population_cost",
            "transcript_sha256",
        }:
            raise SolutionExperimentError("coding mutation completion is malformed")
        for name in ("actions", "input_tokens", "model_calls", "output_tokens"):
            if type(completion[name]) is not int or int(completion[name]) < 0:
                raise SolutionExperimentError(
                    "coding mutation completion count is malformed"
                )
        if int(completion["model_calls"]) > runtime.max_model_calls:
            raise SolutionExperimentError("coding mutation exceeded model call limit")
        population_cost = completion["population_cost"]
        if type(population_cost) is not dict or set(population_cost) != set(
            RESOURCE_NAMES
        ):
            raise SolutionExperimentError("coding mutation cost is malformed")
        if any(
            type(value) is not int or value < 0 for value in population_cost.values()
        ):
            raise SolutionExperimentError("coding mutation cost is malformed")
        if (
            type(completion["transcript_sha256"]) is not str
            or len(str(completion["transcript_sha256"])) != 64
        ):
            raise SolutionExperimentError("coding mutation transcript is malformed")
        mutation_matches.add(digest)
    matched_mutations: set[str] = set()
    for child_id in child_ids:
        parent_id = state.candidate_parents[child_id][0]
        actual_changes = changed_paths(
            candidate_snapshots[parent_id], candidate_snapshots[child_id]
        )
        try:
            require_allowed_changes(
                actual_changes, cast(list[str], profile["allowed_paths"])
            )
        except WorkspaceError as exc:
            raise SolutionExperimentError(str(exc)) from exc
        matches = [
            (digest, receipt)
            for digest, receipt in mutation_receipts.items()
            if receipt.get("base_files_sha256") == candidate_files[parent_id]
            and receipt.get("result_files_sha256") == candidate_files[child_id]
            and receipt.get("changed_paths") == actual_changes
            and receipt.get("runtime_id") == runtime.runtime_id
            and receipt.get("harness_candidate_id") == descriptor["candidate_id"]
            and (
                descriptor["descriptor_schema"] == "selected-evolutionary-harness-v1"
                or receipt.get("coding_runtime_id") == coding_runtime_id
            )
        ]
        authoritative = [item for item in matches if item[0] not in retry_mutations]
        if len(authoritative) == 1:
            matched = authoritative[0]
        elif not authoritative and matches:
            matched = sorted(matches, key=lambda item: item[0])[0]
        else:
            raise SolutionExperimentError(
                "solution child does not have one bound mutation receipt"
            )
        matched_mutations.add(matched[0])
    if (
        not retry_mutations <= mutation_matches
        or not (mutation_matches - matched_mutations) <= retry_mutations
    ):
        raise SolutionExperimentError(
            "coding mutation receipt set does not match solution lineage or retry effects"
        )
    return len(mutation_receipts)


def _verify_development_receipts(
    root: Path,
    state: PopulationState,
    profile: dict[str, object],
    runtime: RuntimeManifest,
    coding_runtime_id: str,
    candidate_files: dict[str, str],
) -> tuple[dict[str, dict[str, object]], dict[str, object], set[str]]:
    """Replay development outcomes and evaluation-only costs, not mutation costs."""
    evaluation_receipts = receipt_files(root / "evaluation-receipts", RECEIPT_SCHEMA)
    development_tasks = task_documents(profile, "development")
    development_task_ids = {canonical_digest(task): task for task in development_tasks}
    expected_development: set[str] = set()
    final_runs: list[dict[str, object]] = []
    for run in state.runs:
        run_record = cast(dict[str, object], run["run"])
        experiment = state.experiments[str(run_record["experiment_id"])]
        if experiment["runtime_id"] != coding_runtime_id:
            raise SolutionExperimentError("Population run changed coding runtime")
        if experiment["role"] == "development":
            seed = run_record["seed"]
            if type(seed) is not dict or type(seed.get("receipt_sha256")) is not list:
                raise SolutionExperimentError(
                    "development run omitted receipt identities"
                )
            digests = cast(list[str], seed["receipt_sha256"])
            candidate_id = str(run_record["candidate_id"])
            observed_tasks: set[str] = set()
            actual_passed = 0
            actual_safety_failures = 0
            actual_cost = {name: 0 for name in RESOURCE_NAMES}
            for digest in digests:
                receipt = evaluation_receipts.get(digest)
                if receipt is None:
                    raise SolutionExperimentError(
                        "development coding receipt is absent"
                    )
                task_id = str(receipt.get("task_id"))
                task = development_task_ids.get(task_id)
                if task is None or task_id in observed_tasks:
                    raise SolutionExperimentError(
                        "development coding receipt changed task coverage"
                    )
                artifact = cast(
                    dict[str, object], state.candidates[candidate_id]["artifact"]
                )
                execution = verify_bound_evaluation_receipt(
                    receipt,
                    candidate_id=candidate_id,
                    candidate_content_sha256=artifact["content_sha256"],
                    workspace_sha256=candidate_files[candidate_id],
                    task=task,
                    runtime=runtime,
                )
                actual_passed += int(
                    execution["returncode"] == 0 and execution["timed_out"] is False
                )
                actual_safety_failures += int(
                    runtime.isolation_enforced
                    and receipt["isolation_enforced"] is not True
                )
                receipt_cost = cast(dict[str, int], receipt["cost"])
                for name in RESOURCE_NAMES:
                    actual_cost[name] += receipt_cost[name]
                observed_tasks.add(task_id)
            if observed_tasks != set(development_task_ids):
                raise SolutionExperimentError(
                    "development coding receipt set is incomplete"
                )
            run_evidence = cast(dict[str, object], run["evidence"])
            task_evidence = cast(dict[str, object], run_evidence["task"])
            if (
                task_evidence.get("case_count") != len(development_tasks)
                or task_evidence.get("passed_count") != actual_passed
                or task_evidence.get("safety_failures") != actual_safety_failures
                or run_evidence.get("protected_passed")
                is not (actual_safety_failures == 0)
                or run_evidence.get("cost") != actual_cost
                or run_evidence.get("behavior_distribution")
                != [
                    1.0 - actual_passed / len(development_tasks),
                    actual_passed / len(development_tasks),
                ]
            ):
                raise SolutionExperimentError(
                    "development Population evidence does not match execution receipts"
                )
            expected_development.update(digests)
        else:
            final_runs.append(run)
    if len(final_runs) != 1:
        raise SolutionExperimentError("coding experiment must have one final run")
    return evaluation_receipts, final_runs[0], expected_development


def _verify_final_cases(
    root: Path,
    state: PopulationState,
    runtime: RuntimeManifest,
    final_run: dict[str, object],
    final_tasks: list[dict[str, object]],
    candidate_files: dict[str, str],
    evaluation_receipts: dict[str, dict[str, object]],
) -> tuple[dict[str, object], set[str], str]:
    """Replay the protected cases and their independently recorded execution costs."""
    final_tasks_by_case = {str(task["case_id"]): task for task in final_tasks}
    final_bundles = receipt_files(
        root / "final-receipts", BUNDLE_SCHEMA, schema_key="final_assay_schema"
    )
    if len(final_bundles) != 1:
        raise SolutionExperimentError("coding experiment must have one final bundle")
    bundle_digest, bundle = next(iter(final_bundles.items()))
    final_evidence = cast(dict[str, object], final_run["evidence"])
    reference = final_evidence["evidence_receipt"]
    if type(reference) is not dict or reference.get("sha256") != bundle_digest:
        raise SolutionExperimentError("final Population run changed bundle identity")
    cases = bundle.get("cases")
    if type(cases) is not list:
        raise SolutionExperimentError("final coding bundle cases are malformed")
    expected_final: set[str] = set()
    final_candidate_id = str(cast(dict[str, object], final_run["run"])["candidate_id"])
    observed_final_cases: set[str] = set()
    final_passed = 0
    final_safety_failures = 0
    final_cost = {name: 0 for name in RESOURCE_NAMES}
    for raw_case in cases:
        if type(raw_case) is not dict or set(raw_case) != {
            "case_id",
            "evidence",
            "forecast",
            "outcome",
            "passed",
            "receipt",
            "receipt_sha256",
            "result_sha256",
            "safety_passed",
            "target_probability",
        }:
            raise SolutionExperimentError("final coding case is malformed")
        case_id = raw_case.get("case_id")
        digest = raw_case.get("receipt_sha256")
        if (
            type(case_id) is not str
            or case_id in observed_final_cases
            or type(digest) is not str
            or digest not in evaluation_receipts
            or case_id not in final_tasks_by_case
        ):
            raise SolutionExperimentError("final coding case identity is malformed")
        receipt = evaluation_receipts[digest]
        artifact = cast(
            dict[str, object], state.candidates[final_candidate_id]["artifact"]
        )
        execution = verify_bound_evaluation_receipt(
            receipt,
            candidate_id=final_candidate_id,
            candidate_content_sha256=artifact["content_sha256"],
            workspace_sha256=candidate_files[final_candidate_id],
            task=final_tasks_by_case[case_id],
            runtime=runtime,
        )
        passed = execution["returncode"] == 0 and execution["timed_out"] is False
        safety_passed = (
            receipt["isolation_enforced"] is True
            if runtime.isolation_enforced
            else True
        )
        reference = {
            "sha256": digest,
            "uri": (root / "evaluation-receipts" / f"{digest}.json").as_uri(),
        }
        forecast = {
            "outcomes": [
                {"outcome": "fail", "probability": 0.5},
                {"outcome": "pass", "probability": 0.5},
            ]
        }
        submission = {
            "_metering_coding_candidate": {
                "receipt": reference,
                "runtime_id": runtime.runtime_id,
            },
            "execution": {
                "returncode": execution["returncode"],
                "stderr_sha256": hashlib.sha256(
                    str(execution["stderr"]).encode("utf-8")
                ).hexdigest(),
                "stdout_sha256": hashlib.sha256(
                    str(execution["stdout"]).encode("utf-8")
                ).hexdigest(),
                "timed_out": execution["timed_out"],
            },
        }
        expected_case = {
            "case_id": case_id,
            "evidence": {"receipt_sha256": digest},
            "forecast": forecast,
            "outcome": "pass" if passed else "fail",
            "passed": passed,
            "receipt": reference,
            "receipt_sha256": digest,
            "result_sha256": canonical_digest(
                {"forecast": forecast, "submission": submission}
            ),
            "safety_passed": safety_passed,
            "target_probability": 0.5,
        }
        if raw_case != expected_case:
            raise SolutionExperimentError("final coding case does not replay")
        final_passed += int(passed)
        final_safety_failures += int(not safety_passed)
        cost = cast(dict[str, int], receipt["cost"])
        for name in RESOURCE_NAMES:
            final_cost[name] += cost[name]
        expected_final.add(digest)
        observed_final_cases.add(case_id)
    if observed_final_cases != set(final_tasks_by_case):
        raise SolutionExperimentError("final coding task set is incomplete")
    final_task_evidence = cast(dict[str, object], final_evidence["task"])
    if (
        final_task_evidence
        != {
            "case_count": len(final_tasks),
            "passed_count": final_passed,
            "safety_failures": final_safety_failures,
        }
        or final_evidence.get("cost") != final_cost
        or final_evidence.get("protected_passed") is not (final_safety_failures == 0)
        or final_evidence.get("behavior_distribution")
        != [
            1.0 - final_passed / len(final_tasks),
            final_passed / len(final_tasks),
        ]
    ):
        raise SolutionExperimentError(
            "final Population evidence does not match execution receipts"
        )
    return bundle, expected_final, final_candidate_id


def _verify_final_selection(
    state: PopulationState,
    profile: dict[str, object],
    coding_runtime_id: str,
    development_experiment_id: str,
    final_run: dict[str, object],
    final_tasks: list[dict[str, object]],
    bundle: dict[str, object],
    final_candidate_id: str,
    evaluator_ids: set[str],
) -> None:
    """Independently reconstruct the declared final allocation and permanent seal."""
    expected_candidate, allocation_draw, finalists, archive_id = (
        _expected_final_selection(
            state,
            development_experiment_id,
            cast(dict[str, int], profile["final_draw"]),
        )
    )
    final_run_record = cast(dict[str, object], final_run["run"])
    final_seed = final_run_record["seed"]
    expected_seed = {
        "allocation_record_id": bundle.get("allocation_record_id"),
        "allocation_draw": allocation_draw,
        "selection_policy": "development-task-rate-reliability-v1",
        "tie_draw": profile["final_draw"],
    }
    expected_selection = {
        "allocation_draw": allocation_draw,
        "eligible_candidate_ids": finalists,
        "policy": "development-task-rate-reliability-v1",
        "tie_draw": profile["final_draw"],
    }
    if (
        final_candidate_id != expected_candidate
        or final_seed != expected_seed
        or bundle.get("candidate_id") != expected_candidate
        or bundle.get("runtime_id") != coding_runtime_id
        or bundle.get("evaluator_id") not in evaluator_ids
        or bundle.get("selection") != expected_selection
    ):
        raise SolutionExperimentError("coding final selection policy does not replay")
    allocation_id = expected_seed["allocation_record_id"]
    if type(allocation_id) is not str:
        raise SolutionExperimentError("coding final allocation identity is malformed")
    allocation_record = state.record(allocation_id)
    if allocation_record is None:
        raise SolutionExperimentError("coding final allocation record is absent")
    allocation_body = cast(dict[str, object], allocation_record["body"])
    allocation_request = cast(dict[str, object], allocation_body["request"])
    allocation_result = cast(dict[str, object], allocation_body["result"])
    if (
        allocation_request.get("archive_record_id") != archive_id
        or allocation_request.get("draw") != allocation_draw
        or allocation_result.get("selected_candidate_id") != expected_candidate
    ):
        raise SolutionExperimentError("coding final allocation record does not replay")
    archive_record = state.record(archive_id)
    assert archive_record is not None
    trailing_allocations = [
        record_id
        for record_id, _ in state.allocations
        if int(cast(dict[str, object], state.record(record_id))["sequence"])
        > int(archive_record["sequence"])
    ]
    if trailing_allocations != [allocation_id]:
        raise SolutionExperimentError(
            "coding final allocation is not the unique sealed allocation"
        )
    final_experiment = state.experiments[str(final_run_record["experiment_id"])]
    if (
        final_experiment["task_set_id"]
        != canonical_digest(
            {
                "task_set_schema": "protected-darwinian-coding-final-v1",
                "tasks": final_tasks,
            }
        )
        or final_experiment["case_count"] != len(final_tasks)
        or final_experiment["runtime_id"] != coding_runtime_id
    ):
        raise SolutionExperimentError("coding final experiment identity changed")


def _verify_selected_solution(
    root: Path,
    state: PopulationState,
    profile: dict[str, object],
    final_run: dict[str, object],
) -> str:
    """Check the derived operator descriptor and patch without publishing either."""
    selected = canonical_document(root / "selected-solution.json", "selected solution")
    selected_id = selected.get("candidate_id")
    final_candidate = cast(dict[str, object], final_run["run"])["candidate_id"]
    if (
        selected.get("descriptor_schema") != "selected-solution-commit-v1"
        or selected_id != final_candidate
        or selected.get("artifact") != state.candidates[str(selected_id)]["artifact"]
        or selected.get("task_id") != profile["task_id"]
        or selected.get("base_commit")
        != cast(dict[str, str], profile["repository"])["base_commit"]
    ):
        raise SolutionExperimentError("selected solution descriptor changed identity")
    patch = (root / "selected.patch").read_bytes()
    expected_patch = run_git(
        [
            "diff",
            "--binary",
            str(selected["base_commit"]),
            str(cast(dict[str, object], selected["artifact"])["commit"]),
        ],
        cwd=root / "candidate.git",
    ).encode("utf-8")
    if patch != expected_patch or hashlib.sha256(patch).hexdigest() != selected.get(
        "patch_sha256"
    ):
        raise SolutionExperimentError("selected solution patch does not replay")
    return cast(str, selected_id)
