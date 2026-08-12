from __future__ import annotations

import json
from pathlib import Path

import pytest

from contract import (
    ContractError,
    canonical_events,
    event_payload,
    event_step,
    get_path,
    recursive_keys,
    recursive_values_for_keys,
    report_resources,
    termination_reason,
    verification_fact,
)


def _balanced_run(api, tmp_path, run_id="trace-run"):
    return api.run(
        harness=api.policy("balanced"),
        fault_id=api.fault_ids[3],
        parent_dir=tmp_path,
        budget=16,
        run_id=run_id,
    )


def _reference_hidden_state(reference):
    return get_path(
        reference,
        "hidden_fault",
        "fault_id",
        "hidden_state",
        "reference.hidden_fault",
        "reference.fault_id",
        "generated_instance.hidden_fault_id",
        "instance.hidden_fault",
    )


def test_run_directory_contains_exact_required_artifact_names(api, tmp_path):
    artifacts = _balanced_run(api, tmp_path, "artifact-layout")
    names = {path.name for path in artifacts.run_dir.iterdir() if path.is_file()}
    assert {"manifest.json", "events.jsonl", "reference.json", "report.json"} <= names

    # JSONL is genuinely one independently parseable object per nonblank line.
    lines = (artifacts.run_dir / "events.jsonl").read_text().splitlines()
    assert lines and all(line.strip() for line in lines)
    assert [json.loads(line) for line in lines] == artifacts.events


def test_every_event_has_version_identity_payload_resources_and_monotonic_step(api, tmp_path):
    artifacts = _balanced_run(api, tmp_path, "event-schema")
    steps = []
    schema_versions = set()
    run_ids = set()
    world_versions = set()
    instance_versions = set()

    for event in artifacts.events:
        schema_versions.add(str(get_path(event, "schema_version")))
        run_ids.add(str(get_path(event, "run_id", "run_identifier")))
        world_versions.add(str(get_path(event, "world_version", "world.version")))
        instance_versions.add(
            str(get_path(event, "instance_version", "instance.version"))
        )
        steps.append(event_step(event))
        assert isinstance(event_payload(event), dict)
        resources = get_path(event, "raw_resources", "resources", "raw_resource_counts")
        assert isinstance(resources, dict)

    assert len(schema_versions) == 1 and next(iter(schema_versions))
    assert len(run_ids) == 1
    assert len(world_versions) == 1 and next(iter(world_versions))
    assert len(instance_versions) == 1 and next(iter(instance_versions))
    assert steps == list(range(steps[0], steps[0] + len(steps)))


def test_generated_instance_not_seed_alone_is_stored_in_manifest(api, tmp_path):
    artifacts = _balanced_run(api, tmp_path, "stored-instance")
    instance = get_path(
        artifacts.manifest,
        "instance",
        "generated_instance",
        "configuration.instance",
    )
    assert isinstance(instance, dict), "manifest must embed the actual generated instance"
    keys = recursive_keys(instance)
    assert keys & {
        "tests",
        "test_ids",
        "catalogue",
        "diagnostic_tests",
        "diagnostic_test_ids",
    }, "a seed without the concrete public diagnostic catalogue is not an instance record"


def test_private_reference_is_separate_from_manifest_and_event_stream(api, tmp_path):
    fault = api.fault_ids[6]
    artifacts = api.run(
        harness=api.policy("balanced"),
        fault_id=fault,
        parent_dir=tmp_path,
        budget=16,
        run_id="private-reference",
    )
    assert str(_reference_hidden_state(artifacts.reference)) == fault

    forbidden = {"hidden_fault", "hidden_state", "ground_truth", "reference_state"}
    assert recursive_keys(artifacts.manifest).isdisjoint(forbidden)
    assert all(recursive_keys(event).isdisjoint(forbidden) for event in artifacts.events)


def test_report_can_be_deleted_and_rebuilt_exactly(api, tmp_path):
    artifacts = _balanced_run(api, tmp_path, "delete-and-replay")
    expected = artifacts.report
    raw_hashes = artifacts.raw_hashes()
    report_path = artifacts.run_dir / "report.json"
    report_path.unlink()
    assert not report_path.exists()

    api.rebuild_report(artifacts.run_dir)
    assert report_path.is_file()
    rebuilt = json.loads(report_path.read_text())
    assert rebuilt == expected
    assert artifacts.raw_hashes() == raw_hashes


def test_rebuild_ignores_a_stale_or_tampered_report(api, tmp_path):
    artifacts = _balanced_run(api, tmp_path, "replace-report")
    expected = artifacts.report
    (artifacts.run_dir / "report.json").write_text(
        json.dumps({"success": "trust me", "made_up_points": -999})
    )

    api.rebuild_report(artifacts.run_dir)
    rebuilt = json.loads((artifacts.run_dir / "report.json").read_text())
    assert rebuilt == expected
    assert "made_up_points" not in rebuilt


def test_meter_replay_is_pure_idempotent_and_does_not_touch_raw_artifacts(api, tmp_path):
    artifacts = _balanced_run(api, tmp_path, "pure-meter")
    raw_hashes = artifacts.raw_hashes()
    first = artifacts.report

    api.rebuild_report(artifacts.run_dir)
    second = json.loads((artifacts.run_dir / "report.json").read_text())
    api.rebuild_report(artifacts.run_dir)
    third = json.loads((artifacts.run_dir / "report.json").read_text())

    assert first == second == third
    assert artifacts.raw_hashes() == raw_hashes


def test_report_replay_does_not_run_a_policy_or_apply_world_actions(
    api, tmp_path, monkeypatch
):
    artifacts = _balanced_run(api, tmp_path, "offline-only")
    expected = artifacts.report
    (artifacts.run_dir / "report.json").unlink()

    def forbidden(*args, **kwargs):
        raise AssertionError("offline report replay attempted live execution")

    for name in (
        "BalancedSearchPolicy",
        "BalancedPolicy",
        "SequentialSearchPolicy",
        "SequentialPolicy",
        "SeededRandomSearchPolicy",
        "SeededRandomPolicy",
    ):
        if hasattr(api.policies_module, name):
            monkeypatch.setattr(api.policies_module, name, forbidden)

    world_cls = getattr(api.world_module, "HiddenFaultWorld", None)
    if world_cls is not None:
        for name in ("apply", "apply_action"):
            if hasattr(world_cls, name):
                monkeypatch.setattr(world_cls, name, forbidden)

    api.rebuild_report(artifacts.run_dir)
    assert json.loads((artifacts.run_dir / "report.json").read_text()) == expected


def test_same_deterministic_run_has_same_factual_trace_modulo_run_metadata(api, tmp_path):
    first = api.run(
        harness=api.policy("balanced"),
        fault_id=api.fault_ids[7],
        parent_dir=tmp_path / "one",
        budget=16,
        run_id="first-id",
    )
    second = api.run(
        harness=api.policy("balanced"),
        fault_id=api.fault_ids[7],
        parent_dir=tmp_path / "two",
        budget=16,
        run_id="second-id",
    )
    assert canonical_events(first.events) == canonical_events(second.events)


def _write_events(path, events):
    path.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events))


def test_trace_reader_rejects_nonmonotonic_steps(api, tmp_path):
    artifacts = _balanced_run(api, tmp_path, "bad-step")
    damaged = json.loads(json.dumps(artifacts.events))
    assert len(damaged) >= 2
    step_key = "step" if "step" in damaged[1] else "step_number"
    damaged[1][step_key] = damaged[0].get("step", damaged[0].get("step_number"))
    _write_events(artifacts.run_dir / "events.jsonl", damaged)

    reader = getattr(api.trace_module, "read_events", None)
    if reader is None:
        reader_cls = getattr(api.trace_module, "TraceReader")
        reader = lambda path: reader_cls(path).load()
    with pytest.raises(ValueError, match="step|monotonic|order"):
        reader(artifacts.run_dir / "events.jsonl")


def test_impossible_diagnostic_result_is_trace_corruption(api, tmp_path):
    artifacts = _balanced_run(api, tmp_path, "impossible-observation")
    damaged = json.loads(json.dumps(artifacts.events))
    changed = False
    for event in damaged:
        payload = event.get("payload", {})
        observation = payload.get("observation", payload)
        if not isinstance(observation, dict):
            continue
        if observation.get("type") not in ("diagnostic_result", "diagnostic"):
            continue
        for key in ("positive", "result", "outcome", "value"):
            if key in observation:
                observation[key] = "__not_a_possible_boolean_result__"
                changed = True
                break
        if changed:
            break
    assert changed, "balanced trace did not contain a typed diagnostic observation"

    _write_events(artifacts.run_dir / "events.jsonl", damaged)
    (artifacts.run_dir / "report.json").unlink()
    with pytest.raises(ValueError, match="observation|diagnostic|bool|trace|corrupt"):
        api.rebuild_report(artifacts.run_dir)
    assert not (artifacts.run_dir / "report.json").exists()


def test_model_impossible_boolean_observation_is_not_metered_as_information(api, tmp_path):
    """A well-typed lie about the fixed instance is corruption, not evidence."""
    artifacts = _balanced_run(api, tmp_path, "model-impossible-observation")
    damaged = json.loads(json.dumps(artifacts.events))
    changed = False
    for event in damaged:
        payload = event.get("payload", {})
        observation = payload.get("observation", payload)
        if not isinstance(observation, dict):
            continue
        if observation.get("type") not in ("diagnostic_result", "diagnostic"):
            continue
        for key in ("positive", "result", "outcome", "value"):
            if key in observation and isinstance(observation[key], bool):
                observation[key] = not observation[key]
                changed = True
                break
        if changed:
            break
    assert changed
    _write_events(artifacts.run_dir / "events.jsonl", damaged)
    (artifacts.run_dir / "report.json").unlink()

    with pytest.raises(ValueError, match="impossible|model|observation|diagnostic|contradict|corrupt|reference"):
        api.rebuild_report(artifacts.run_dir)
    assert not (artifacts.run_dir / "report.json").exists()


def test_meter_failure_cannot_change_completed_world_execution_or_trace(
    api, tmp_path, monkeypatch
):
    """The controller commits raw artifacts before invoking report code."""
    run_id = "meter-bomb"
    run_dir = tmp_path / run_id
    original = getattr(api.runner_module, "build_report")

    class MeterBomb(RuntimeError):
        pass

    def explode(*args, **kwargs):
        raise MeterBomb("intentional meter failure")

    monkeypatch.setattr(api.runner_module, "build_report", explode)
    with pytest.raises(MeterBomb):
        api.run(
            harness=api.policy("balanced"),
            fault_id=api.fault_ids[2],
            parent_dir=tmp_path,
            budget=16,
            run_id=run_id,
        )

    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "events.jsonl").is_file()
    assert (run_dir / "reference.json").is_file()
    assert not (run_dir / "report.json").exists()
    raw_before = {
        name: (run_dir / name).read_bytes()
        for name in ("manifest.json", "events.jsonl", "reference.json")
    }
    raw_events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    assert "normal" in termination_reason(raw_events) or "finish" in termination_reason(raw_events)

    monkeypatch.setattr(api.runner_module, "build_report", original)
    api.rebuild_report(run_dir)
    assert (run_dir / "report.json").is_file()
    assert {
        name: (run_dir / name).read_bytes()
        for name in ("manifest.json", "events.jsonl", "reference.json")
    } == raw_before
