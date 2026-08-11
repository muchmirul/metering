from __future__ import annotations

from collections.abc import Mapping
import math

import pytest

from v0_contract import diagnostic_result, jsonable, recursive_keys


def _raw_cost_is_nonnegative(cost) -> bool:
    data = jsonable(cost)
    if isinstance(data, bool):
        return False
    if isinstance(data, (int, float)):
        return math.isfinite(float(data)) and data >= 0
    if isinstance(data, Mapping) and data:
        numeric = [value for value in data.values() if isinstance(value, (int, float)) and not isinstance(value, bool)]
        return bool(numeric) and all(math.isfinite(float(value)) and value >= 0 for value in numeric)
    return False


def test_v0_spec_declares_exactly_eight_distinct_hidden_states(api):
    """Calibration means the complete declared set, not eight sampled draws."""
    assert len(api.fault_ids) == 8
    assert len(set(api.fault_ids)) == 8



def test_v0_catalogue_contains_three_bit_splits_and_all_singletons(api):
    """Pin the controlled fixture that makes exact calibration costs meaningful."""
    public = jsonable(api.public_description(api.world(api.fault_ids[0])))
    tests = public["diagnostic_tests"]
    positive_sets = {
        frozenset(test["positive_fault_ids"])
        for test in tests
    }
    faults = list(api.fault_ids)
    expected_bit_splits = {
        frozenset(fault for index, fault in enumerate(faults) if (index >> bit) & 1)
        for bit in range(3)
    }
    expected_singletons = {frozenset({fault}) for fault in faults}
    assert expected_bit_splits <= positive_sets
    assert expected_singletons <= positive_sets

def test_public_description_is_identical_for_every_hidden_state(api):
    """Changing controller-private truth must not change a harness input."""
    descriptions = [jsonable(api.public_description(api.world(fault))) for fault in api.fault_ids]
    assert descriptions
    assert all(description == descriptions[0] for description in descriptions[1:])


def test_public_description_contains_fixed_diagnostic_catalogue(api):
    """The harness may select declared tests, but may not invent arbitrary tests."""
    assert api.test_ids
    assert len(set(api.test_ids)) == len(api.test_ids)
    public_keys = recursive_keys(api.public_description(api.world(api.fault_ids[0])))
    assert public_keys & {
        "tests",
        "test_ids",
        "catalogue",
        "diagnostic_tests",
        "diagnostic_test_ids",
    }, "the diagnostic catalogue must be part of the public instance"


def test_diagnostic_catalogue_distinguishes_all_eight_states(api):
    """Each hidden state needs a unique complete public-test signature."""
    signatures = {}
    for fault in api.fault_ids:
        outcomes = []
        for test_id in api.test_ids:
            world = api.world(fault)
            observation, _ = api.apply(world, api.action("diagnose", test_id))
            outcomes.append(jsonable(diagnostic_result(observation)))
        signatures[fault] = tuple(outcomes)

    assert len(set(signatures.values())) == 8, signatures


@pytest.mark.parametrize("fault_index", range(8))
def test_diagnose_returns_typed_result_and_raw_cost(api, fault_index):
    world = api.world(api.fault_ids[fault_index])
    test_id = api.test_ids[0]
    action = api.action("diagnose", test_id)
    validation = api.validate(world, action)
    if validation is not None:
        if hasattr(validation, "valid"):
            assert validation.valid
        elif hasattr(validation, "ok"):
            assert validation.ok
        else:
            assert validation is True

    observation, raw_cost = api.apply(world, action)
    data = jsonable(observation)
    assert isinstance(data, Mapping), "observations are typed protocol values, not free-form strings"
    assert diagnostic_result(observation) is not None
    assert _raw_cost_is_nonnegative(raw_cost), "the world must return an explicit raw action cost"

    forbidden = {"hidden_fault", "hidden_state", "ground_truth", "reference_state"}
    assert recursive_keys(data).isdisjoint(forbidden)


def test_action_factories_produce_all_four_typed_commands(api):
    actions = [
        api.action("diagnose", api.test_ids[0]),
        api.action("repair", api.fault_ids[0]),
        api.action("verify"),
        api.action("finish"),
    ]
    serialised = [jsonable(action) for action in actions]
    assert all(isinstance(action, Mapping) for action in serialised)
    assert len({str(action) for action in serialised}) == 4
