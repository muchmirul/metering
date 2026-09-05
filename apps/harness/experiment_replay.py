"""Offline harness experiment verification; never launches a model or an assay."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import cast

from apps._support.wire import canonical_digest, canonical_json, decode_json_object
from apps.harness.experiment_config import (
    FIXTURES,
    ExperimentError,
    capability_first_draw,
    load_assay_tasks,
)
from apps.harness.experiment_receipts import verify_experiment_receipts
from apps.harness.protocol import load_candidate
from apps.harness.runtime_manifest import (
    RuntimeManifest,
    assert_candidate_compatible,
    load_runtime_manifest,
)
from apps.population.contract import load_state
from apps.population_driver.paths import population_root
from apps.population_driver.runtime import verify_population_driver
from artifacts.git.git_repository import clone_verified


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


def _verification_tasks(
    root: Path,
) -> tuple[
    str,
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object] | None,
]:
    path = root / "assay.json"
    if not path.exists():
        return (
            "arithmetic-v1",
            load_assay_tasks(FIXTURES / "development-tasks.json"),
            load_assay_tasks(FIXTURES / "final-tasks.json"),
            None,
        )
    if path.is_symlink() or not path.is_file():
        raise ExperimentError("coding assay manifest is unsafe")
    source = path.read_text(encoding="ascii")
    document = decode_json_object(source, ExperimentError)
    legacy_keys = {
        "assay_schema",
        "development_tasks",
        "final_tasks",
        "schema_version",
    }
    current_keys = {*legacy_keys, "final_selection"}
    keys = set(document)
    if source != canonical_json(document) + "\n" or (
        keys != legacy_keys and keys != current_keys
    ):
        raise ExperimentError("coding assay manifest is malformed")
    if (
        document["assay_schema"] != "coding-agent-assay-v1"
        or document["schema_version"] != 1
    ):
        raise ExperimentError("coding assay manifest version is unsupported")
    development = document["development_tasks"]
    final = document["final_tasks"]
    if (
        type(development) is not list
        or not development
        or any(type(item) is not dict for item in development)
        or type(final) is not list
        or not final
        or any(type(item) is not dict for item in final)
    ):
        raise ExperimentError("coding assay task sets are malformed")
    selection = document.get("final_selection")
    if selection is not None and selection != {
        "policy": "development-task-rate-reliability-v1",
        "tie_draw": {"denominator": 1, "numerator": 0},
    }:
        raise ExperimentError("coding assay final selection policy is malformed")
    return (
        "coding-agent-v1",
        cast(list[dict[str, object]], development),
        cast(list[dict[str, object]], final),
        cast(dict[str, object] | None, selection),
    )


def verify_experiment(root: Path) -> dict[str, object]:
    root = root.expanduser().absolute()
    assay, development_tasks, final_tasks, final_selection = _verification_tasks(root)
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
    if final_selection is not None:
        tie_draw = cast(dict[str, int], final_selection["tie_draw"])
        expected_candidate, allocation_draw, _finalists, archive_id = (
            capability_first_draw(
                root / "state", str(driver["experiment_id"]), tie_draw
            )
        )
        final_run_record = cast(dict[str, object], final_runs[0]["run"])
        seed = final_run_record["seed"]
        if type(seed) is not dict:
            raise ExperimentError("coding harness final seed is malformed")
        allocation_id = seed.get("allocation_record_id")
        if (
            final_run_record["candidate_id"] != expected_candidate
            or seed.get("draw") != allocation_draw
            or type(allocation_id) is not str
        ):
            raise ExperimentError("coding harness final selection does not replay")
        allocation = cast(dict[str, object], state.record(allocation_id)["body"])
        request = cast(dict[str, object], allocation["request"])
        result = cast(dict[str, object], allocation["result"])
        if (
            request.get("archive_record_id") != archive_id
            or request.get("draw") != allocation_draw
            or result.get("selected_candidate_id") != expected_candidate
        ):
            raise ExperimentError("coding harness allocation does not replay")
    if assay == "coding-agent-v1":
        descriptor_path = root / "selected-harness.json"
        if descriptor_path.is_symlink() or not descriptor_path.is_file():
            raise ExperimentError("selected harness descriptor is absent or unsafe")
        descriptor_source = descriptor_path.read_text(encoding="ascii")
        descriptor = decode_json_object(descriptor_source, ExperimentError)
        common_keys = {
            "artifact",
            "candidate_id",
            "descriptor_schema",
            "manifest_id",
            "runtime_id",
        }
        expected_keys = (
            {*common_keys, "provenance"} if final_selection is not None else common_keys
        )
        if (
            descriptor_source != canonical_json(descriptor) + "\n"
            or set(descriptor) != expected_keys
        ):
            raise ExperimentError("selected harness descriptor is malformed")
        candidate_id = descriptor["candidate_id"]
        final_body = cast(dict[str, object], final_runs[0])
        final_run = cast(dict[str, object], final_body["run"])
        final_evidence = cast(dict[str, object], final_body["evidence"])
        expected_schema = (
            "selected-evolutionary-harness-v2"
            if final_selection is not None
            else "selected-evolutionary-harness-v1"
        )
        expected_provenance = None
        if final_selection is not None:
            assay_document = {
                "assay_schema": "coding-agent-assay-v1",
                "development_tasks": development_tasks,
                "final_selection": final_selection,
                "final_tasks": final_tasks,
                "schema_version": 1,
            }
            reference = cast(dict[str, object], final_evidence["evidence_receipt"])
            expected_provenance = {
                "assay_id": canonical_digest(assay_document),
                "development_experiment_id": driver["experiment_id"],
                "final_allocation_record_id": cast(
                    dict[str, object], final_run["seed"]
                )["allocation_record_id"],
                "final_passed_count": cast(dict[str, object], final_evidence["task"])[
                    "passed_count"
                ],
                "final_receipt_sha256": reference["sha256"],
                "final_run_record_id": state.run_record_ids[str(final_run["run_id"])],
                "final_safety_failures": cast(
                    dict[str, object], final_evidence["task"]
                )["safety_failures"],
                "final_task_count": cast(dict[str, object], final_evidence["task"])[
                    "case_count"
                ],
                "population_head_record_id": state.head_id,
            }
        if (
            descriptor["descriptor_schema"] != expected_schema
            or descriptor["runtime_id"] != runtime.runtime_id
            or type(candidate_id) is not str
            or candidate_id not in state.candidates
            or descriptor["artifact"] != state.candidates[candidate_id]["artifact"]
            or descriptor["manifest_id"] != manifests.get(candidate_id)
            or (
                final_selection is not None
                and descriptor["provenance"] != expected_provenance
            )
        ):
            raise ExperimentError("selected harness descriptor changed identity")
    _verify_conformance(root, runtime, manifests)
    run_receipts, bundles = verify_experiment_receipts(
        root,
        runtime,
        state,
        manifests,
        cast(dict[str, object], final_runs[0]),
        development_tasks=development_tasks,
        final_tasks=final_tasks,
        verify_coding_evidence=final_selection is not None,
    )
    if run_receipts < 1 or bundles != 1:
        raise ExperimentError("experiment receipt set is incomplete")
    return {
        "assay": assay,
        "candidate_count": len(state.candidates),
        "driver": driver,
        "final_run_count": len(final_runs),
        "harness_receipt_count": run_receipts,
        "runtime_id": runtime.runtime_id,
        "schema": "evolutionary-harness-verification-v1",
        "status": "verified",
    }
