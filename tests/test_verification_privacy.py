from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


from contract import (
    jsonable,
    recursive_keys,
    verification_fact,
)


TRUTH_KEYS = {
    "passed",
    "pass",
    "failed",
    "success",
    "correct",
    "matches",
    "match",
    "result",
    "outcome",
    "positive",
    "hidden_fault",
    "hidden_fault_id",
    "hidden_state",
    "ground_truth",
}


def _truth_signal(value: Any) -> bool | None:
    data = jsonable(value)

    def walk(item: Any) -> bool | None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if str(key).lower() in TRUTH_KEYS and isinstance(child, bool):
                    return child
                found = walk(child)
                if found is not None:
                    return found
        elif isinstance(item, list):
            for child in item:
                found = walk(child)
                if found is not None:
                    return found
        return None

    signal = walk(data)
    if signal is not None:
        return signal
    # A property omitted from serialization would still be visible to an
    # in-process cooperative harness, so probe the obvious truth-bearing names.
    for attribute in dir(value):
        normalized = attribute.lower().lstrip("_")
        if normalized not in TRUTH_KEYS:
            continue
        try:
            candidate = getattr(value, attribute)
        except Exception:
            continue
        if isinstance(candidate, bool):
            return candidate
    return None


class RepairVerifyProbePolicy:
    """Try to branch on verify feedback, recording exactly what was delivered."""

    name = "pytest-repair-verify-probe"
    version = "1"

    def __init__(self, api):
        self.api = api
        self.verification_payload: dict[str, Any] | None = None
        self.verification_object: Any | None = None
        self.post_verification_action: dict[str, Any] | None = None
        self._probed = False

    def descriptor(self):
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {"probe_truth_bearing_verify_fields": True},
            "seed_policy": {"kind": "none"},
        }

    def next_action(self, instance, observations: Sequence[Any]):
        serialised = [jsonable(observation) for observation in observations]
        types = [
            item.get("type", "") if isinstance(item, Mapping) else ""
            for item in serialised
        ]
        if not any("repair" in kind for kind in types):
            return self.api.action("repair", self.api.fault_ids[0])
        verification_indices = [
            index for index, kind in enumerate(types) if "verif" in kind
        ]
        if not verification_indices:
            return self.api.action("verify")
        if self._probed:
            return self.api.action("finish")

        self._probed = True
        observation = observations[verification_indices[-1]]
        payload = jsonable(observation)
        assert isinstance(payload, dict)
        self.verification_payload = payload
        self.verification_object = observation
        signal = _truth_signal(observation)
        if signal is True:
            action = self.api.action("repair", self.api.fault_ids[0])
        elif signal is False:
            action = self.api.action("repair", self.api.fault_ids[1])
        else:
            action = self.api.action("finish")
        encoded = jsonable(action)
        assert isinstance(encoded, dict)
        self.post_verification_action = encoded
        return action


def _verification_observations(events):
    results = []
    for event in events:
        payload = event.get("payload", {})
        action = payload.get("action", {}) if isinstance(payload, dict) else {}
        observation = payload.get("observation", {}) if isinstance(payload, dict) else {}
        if isinstance(action, dict) and action.get("type") == "verify":
            results.append(observation)
    return results


def test_verification_observation_delivered_to_harness_is_content_free(api, tmp_path):
    delivered = []
    delivered_objects = []
    public_trace_values = []
    post_actions = []

    for index, fault_id in enumerate(api.fault_ids):
        policy = RepairVerifyProbePolicy(api)
        run = api.run(
            harness=policy,
            fault_id=fault_id,
            parent_dir=tmp_path / str(index),
            budget=8,
            run_id=f"verify-probe-{index}",
        )
        assert policy.verification_payload is not None
        assert policy.verification_object is not None
        assert policy.post_verification_action is not None
        delivered.append(policy.verification_payload)
        delivered_objects.append(policy.verification_object)
        post_actions.append(policy.post_verification_action)

        observations = _verification_observations(run.events)
        assert len(observations) == 1
        public_trace_values.append(observations[0])

        assert verification_fact(run.report, "verified_after_final_repair") is True
        assert verification_fact(run.report, "repair_matches") is (index == 0)
        assert verification_fact(run.report, "success") is (index == 0)

    # A typed discriminator is the only content.  In particular there is no
    # Boolean whose value could reveal whether the chosen repair matched truth.
    for value in delivered + public_trace_values:
        assert set(value) == {"type"}
        assert isinstance(value["type"], str) and "verif" in value["type"]
        assert recursive_keys(value).isdisjoint(TRUTH_KEYS)
        assert not any(isinstance(item, bool) for item in value.values())

    assert all(value == delivered[0] for value in delivered[1:])
    assert all(value == public_trace_values[0] for value in public_trace_values[1:])
    assert len({type(value) for value in delivered_objects}) == 1
    assert all(repr(value) == repr(delivered_objects[0]) for value in delivered_objects[1:])
    assert _truth_signal(delivered_objects[0]) is None

    # The deliberately probing policy therefore takes one fixed action rather
    # than adapting differently after a successful versus failed repair.
    assert all(action == {"type": "finish"} for action in post_actions)
