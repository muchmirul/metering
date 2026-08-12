from __future__ import annotations

import json

import pytest

from contract import (
    CrashingHarness,
    ScriptedHarness,
    event_payload,
    event_type,
    jsonable,
    recursive_keys,
    resource_count,
    termination_reason,
    verification_fact,
)


def _run_script(api, tmp_path, fault_id, actions, *, budget=16, run_id="scripted"):
    harness = ScriptedHarness(actions)
    artifacts = api.run(
        harness=harness,
        fault_id=fault_id,
        parent_dir=tmp_path,
        budget=budget,
        run_id=run_id,
    )
    return harness, artifacts


def _assert_reason_contains(artifacts, *tokens: str) -> None:
    reason = termination_reason(artifacts.events)
    assert any(token in reason for token in tokens), reason


def test_harness_initial_input_does_not_reveal_selected_fault(api, tmp_path):
    """A finish-only spy sees the same public instance under every truth."""
    captured = []
    for index, fault in enumerate(api.fault_ids):
        harness, artifacts = _run_script(
            api,
            tmp_path,
            fault,
            [api.action("finish")],
            run_id=f"separation-{index}",
        )
        assert harness.public_inputs, "controller did not provide the public instance"
        captured.append(harness.public_inputs[0])
        assert recursive_keys(harness.public_inputs[0]).isdisjoint(
            {"hidden_fault", "hidden_state", "ground_truth", "reference_state"}
        )
        assert verification_fact(artifacts.report, "terminated_normally") is True

    assert all(value == captured[0] for value in captured[1:])


def test_finish_is_terminal_and_controller_does_not_request_another_action(api, tmp_path):
    harness, artifacts = _run_script(
        api,
        tmp_path,
        api.fault_ids[0],
        [api.action("finish")],
        run_id="finish-is-terminal",
    )
    assert harness.action_calls == 1
    assert verification_fact(artifacts.report, "terminated_normally") is True
    assert verification_fact(artifacts.report, "success") is False
    _assert_reason_contains(artifacts, "finish", "normal")


@pytest.mark.parametrize("omit", ["verification", "correct_repair"])
def test_verifier_reports_conditions_separately(api, tmp_path, omit):
    fault = api.fault_ids[2]
    repair = fault if omit == "verification" else api.fault_ids[3]
    actions = [api.action("repair", repair)]
    if omit != "verification":
        actions.append(api.action("verify"))
    actions.append(api.action("finish"))

    _, artifacts = _run_script(
        api, tmp_path, fault, actions, run_id=f"missing-{omit}"
    )
    report = artifacts.report

    assert verification_fact(report, "repair_matches") is (omit == "verification")
    assert verification_fact(report, "verified_after_final_repair") is (
        omit == "correct_repair"
    )
    assert verification_fact(report, "terminated_normally") is True
    assert verification_fact(report, "budget_respected") is True
    assert verification_fact(report, "success") is False


def test_verification_must_follow_the_final_repair(api, tmp_path):
    fault = api.fault_ids[1]
    actions = [
        api.action("repair", fault),
        api.action("verify"),
        api.action("repair", fault),
        api.action("finish"),
    ]
    _, artifacts = _run_script(
        api, tmp_path, fault, actions, run_id="stale-verification"
    )

    assert verification_fact(artifacts.report, "repair_matches") is True
    assert verification_fact(artifacts.report, "verified_after_final_repair") is False
    assert verification_fact(artifacts.report, "success") is False


def test_unknown_diagnostic_test_is_an_explicit_protocol_failure(api, tmp_path):
    invented = "__not_in_the_public_catalogue__"
    assert invented not in api.test_ids
    harness = ScriptedHarness([api.action("diagnose", invented)])
    artifacts = api.run(
        harness=harness,
        fault_id=api.fault_ids[0],
        parent_dir=tmp_path,
        budget=8,
        run_id="unknown-test",
    )

    assert verification_fact(artifacts.report, "terminated_normally") is False
    assert verification_fact(artifacts.report, "success") is False
    _assert_reason_contains(artifacts, "invalid", "protocol")
    assert any(
        "invalid" in event_type(event).lower()
        or "protocol" in event_type(event).lower()
        or "invalid" in json.dumps(event_payload(event)).lower()
        for event in artifacts.events
    ), "invalid behavior was not recorded as a canonical protocol event"
    assert resource_count(artifacts.report, "total") == 1



@pytest.mark.parametrize("invalid_kind", ["unknown_repair", "verify_without_repair"])
def test_other_state_or_catalogue_invalid_actions_fail_explicitly(
    api, tmp_path, invalid_kind
):
    action = (
        api.action("repair", "__not_a_declared_fault__")
        if invalid_kind == "unknown_repair"
        else api.action("verify")
    )
    harness = ScriptedHarness([action])
    artifacts = api.run(
        harness=harness,
        fault_id=api.fault_ids[0],
        parent_dir=tmp_path,
        budget=8,
        run_id=f"invalid-{invalid_kind}",
    )
    assert harness.action_calls == 1
    assert verification_fact(artifacts.report, "terminated_normally") is False
    assert verification_fact(artifacts.report, "success") is False
    _assert_reason_contains(artifacts, "invalid", "protocol")
    assert resource_count(artifacts.report, "total") == 1

def test_malformed_harness_value_is_not_silently_repaired(api, tmp_path):
    harness = ScriptedHarness([{"please": "guess what I meant"}])
    artifacts = api.run(
        harness=harness,
        fault_id=api.fault_ids[0],
        parent_dir=tmp_path,
        budget=8,
        run_id="malformed-action",
    )

    assert harness.action_calls == 1
    assert verification_fact(artifacts.report, "terminated_normally") is False
    assert verification_fact(artifacts.report, "success") is False
    _assert_reason_contains(artifacts, "invalid", "protocol")
    assert resource_count(artifacts.report, "repair") == 0
    assert resource_count(artifacts.report, "verification") == 0
    assert resource_count(artifacts.report, "total") == 1


def test_never_finishing_harness_stops_at_exact_action_budget(api, tmp_path):
    budget = 5
    repeated = api.action("diagnose", api.test_ids[0])
    harness = ScriptedHarness(repeat=repeated)
    artifacts = api.run(
        harness=harness,
        fault_id=api.fault_ids[4],
        parent_dir=tmp_path,
        budget=budget,
        run_id="budget-exhaustion",
    )

    assert harness.action_calls == budget
    assert resource_count(artifacts.report, "diagnostic") == budget
    assert resource_count(artifacts.report, "total") == budget
    assert resource_count(artifacts.report, "budget_exhausted") is True
    assert verification_fact(artifacts.report, "budget_respected") is True
    assert verification_fact(artifacts.report, "terminated_normally") is False
    assert verification_fact(artifacts.report, "success") is False
    _assert_reason_contains(artifacts, "budget", "exhaust")


def test_harness_crash_has_explicit_termination_record(api, tmp_path):
    harness = CrashingHarness()
    artifacts = api.run(
        harness=harness,
        fault_id=api.fault_ids[5],
        parent_dir=tmp_path,
        budget=8,
        run_id="harness-crash",
    )

    assert harness.action_calls == 1
    assert resource_count(artifacts.report, "total") == 0
    assert verification_fact(artifacts.report, "terminated_normally") is False
    assert verification_fact(artifacts.report, "success") is False
    _assert_reason_contains(artifacts, "crash", "exception", "error")


def test_successful_run_raw_counts_remain_separate(api, tmp_path):
    fault = api.fault_ids[0]
    actions = [
        api.action("diagnose", api.test_ids[0]),
        api.action("repair", fault),
        api.action("verify"),
        api.action("finish"),
    ]
    _, artifacts = _run_script(
        api, tmp_path, fault, actions, run_id="raw-resource-units"
    )

    assert resource_count(artifacts.report, "diagnostic") == 1
    assert resource_count(artifacts.report, "repair") == 1
    assert resource_count(artifacts.report, "verification") == 1
    assert resource_count(artifacts.report, "total") == 4
    assert resource_count(artifacts.report, "budget_exhausted") is False


def test_finish_as_last_budgeted_action_is_normal_not_exhaustion(api, tmp_path):
    budget = 4
    actions = [api.action("diagnose", api.test_ids[0]) for _ in range(budget - 1)]
    actions.append(api.action("finish"))
    harness = ScriptedHarness(actions)
    artifacts = api.run(
        harness=harness,
        fault_id=api.fault_ids[0],
        parent_dir=tmp_path,
        budget=budget,
        run_id="finish-at-budget-boundary",
    )
    assert harness.action_calls == budget
    assert resource_count(artifacts.report, "total") == budget
    assert resource_count(artifacts.report, "budget_exhausted") is False
    assert verification_fact(artifacts.report, "budget_respected") is True
    assert verification_fact(artifacts.report, "terminated_normally") is True
    _assert_reason_contains(artifacts, "normal", "finish")


class DescriptorlessHarness:
    """Name/version attributes must not revive the removed implicit fallback."""

    name = "descriptorless-test-harness"
    version = "1"

    def __init__(self):
        self.action_calls = 0

    def next_action(self, instance, observations):
        self.action_calls += 1
        raise AssertionError("a descriptorless harness must never be executed")


def test_harness_without_exact_callable_descriptor_is_rejected_before_execution(
    api, tmp_path
):
    harness = DescriptorlessHarness()
    requested = tmp_path / "descriptorless"

    with pytest.raises(RuntimeError, match="descriptor"):
        api.run(
            harness=harness,
            fault_id=api.fault_ids[0],
            parent_dir=tmp_path,
            budget=8,
            run_id="descriptorless",
        )

    assert harness.action_calls == 0
    assert not requested.exists()
    assert not list(tmp_path.rglob("events.jsonl"))
