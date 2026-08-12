from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

from contract import (
    artifact_set_id,
    report_raw_input_sha256,
)


def _run_same_id(api, parent: Path, *, fault_index: int = 2):
    return api.run(
        harness=api.policy("balanced"),
        fault_id=api.fault_ids[fault_index],
        parent_dir=parent,
        budget=16,
        run_id="caller-chosen-repeatable-id",
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _all_artifact_set_ids(run) -> set[str]:
    values = {
        artifact_set_id(run.manifest),
        artifact_set_id(run.reference),
        artifact_set_id(run.report),
    }
    # The run_started event binds the stream; later canonical events inherit
    # the stream identity and need not repeat the nonce in every payload.
    values.add(artifact_set_id(run.events[0]))
    return values


def test_same_caller_run_id_gets_a_fresh_controller_artifact_set_id(api, tmp_path):
    first = _run_same_id(api, tmp_path / "first")
    second = _run_same_id(api, tmp_path / "second")

    assert first.manifest["run_id"] == second.manifest["run_id"]
    assert len(_all_artifact_set_ids(first)) == 1
    assert len(_all_artifact_set_ids(second)) == 1
    assert artifact_set_id(first.manifest) != artifact_set_id(second.manifest)


def test_swapping_any_one_raw_artifact_is_rejected_even_when_run_ids_match(
    api, tmp_path
):
    """run_id is caller metadata; artifact_set_id supplies anti-mixup identity."""
    first = _run_same_id(api, tmp_path / "first", fault_index=4)
    second = _run_same_id(api, tmp_path / "second", fault_index=4)
    assert first.manifest["run_id"] == second.manifest["run_id"]
    assert artifact_set_id(first.manifest) != artifact_set_id(second.manifest)

    originals = {
        name: (first.run_dir / name).read_bytes()
        for name in ("manifest.json", "events.jsonl", "reference.json")
    }
    replacements = {
        name: (second.run_dir / name).read_bytes()
        for name in originals
    }

    for filename in originals:
        (first.run_dir / filename).write_bytes(replacements[filename])
        (first.run_dir / "report.json").unlink(missing_ok=True)
        with pytest.raises(ValueError):
            api.rebuild_report(first.run_dir)
        assert not (first.run_dir / "report.json").exists()
        (first.run_dir / filename).write_bytes(originals[filename])

    # The original set remains replayable after every isolated swap is restored.
    api.rebuild_report(first.run_dir)


def test_report_records_byte_exact_sha256_for_all_three_raw_inputs(api, tmp_path):
    run = _run_same_id(api, tmp_path / "hashes")
    expected = {
        filename: sha256((run.run_dir / filename).read_bytes()).hexdigest()
        for filename in ("manifest.json", "events.jsonl", "reference.json")
    }
    assert report_raw_input_sha256(run.report) == expected


def _different_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, str):
        return value + "-tampered"
    if isinstance(value, int):
        return value + 1
    if value is None:
        return "tampered"
    raise AssertionError(f"no same-shape tamper for {value!r}")


def _scalar_paths(mapping: dict[str, Any], prefix: tuple[str, ...]) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    for key, value in mapping.items():
        path = prefix + (key,)
        if isinstance(value, dict):
            paths.extend(_scalar_paths(value, path))
        elif isinstance(value, (str, int, bool)) or value is None:
            paths.append(path)
    return paths


def _get(document: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = document
    for key in path:
        value = value[key]
    return value


def _set(document: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target: Any = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def test_well_typed_policy_configuration_and_provenance_tampering_is_rejected(
    api, tmp_path
):
    run = _run_same_id(api, tmp_path / "provenance")
    manifest_path = run.run_dir / "manifest.json"
    baseline_bytes = manifest_path.read_bytes()
    baseline = json.loads(baseline_bytes)

    paths: list[tuple[str, ...]] = [
        ("policy", "name"),
        ("policy", "version"),
        ("controller", "action_budget"),
    ]
    for section in (
        ("policy", "configuration"),
        ("policy", "seed_policy"),
        ("execution_boundary",),
        ("reproducibility",),
        ("implementation",),
    ):
        value = _get(baseline, section)
        assert isinstance(value, dict) and value, f"missing required section {section}"
        paths.extend(_scalar_paths(value, section))

    # Versioned world provenance is also part of the declared interpretation.
    if "world_specification" in baseline:
        paths.append(("world_specification", "world_version"))

    for path in paths:
        tampered = deepcopy(baseline)
        _set(tampered, path, _different_scalar(_get(tampered, path)))
        _write_json(manifest_path, tampered)
        (run.run_dir / "report.json").unlink(missing_ok=True)
        with pytest.raises(ValueError):
            api.rebuild_report(run.run_dir)
        assert not (run.run_dir / "report.json").exists(), path
        manifest_path.write_bytes(baseline_bytes)

    api.rebuild_report(run.run_dir)

def test_release_version_is_provenance_not_replay_algorithm(api, tmp_path):
    """GitHub release changes do not invalidate unchanged meter algorithms."""
    run = _run_same_id(api, tmp_path / "release-version")
    manifest_path = run.run_dir / "manifest.json"
    reference_path = run.run_dir / "reference.json"

    manifest = json.loads(manifest_path.read_bytes())
    manifest["implementation"]["package_version"] = "999.0.0"
    _write_json(manifest_path, manifest)

    reference = json.loads(reference_path.read_bytes())
    reference["artifact_hashes"]["manifest_sha256"] = sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(reference_path, reference)

    rebuilt = api.rebuild_report(run.run_dir)
    assert rebuilt["correctness"]["overall_task_success"] is True

