"""Test-side helpers bound to the one canonical Metering API.

Behavioural tests import only this module.  It imports the production
package's real names directly, so renaming or reshaping anything public in
``metering`` fails these tests immediately — which is what the tests are for.
The helpers exist to keep test call sites short and to translate between the
tests' compact vocabulary and the exact artifact field names, never to
tolerate alternative spellings of the API or of the artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from metering import hidden_fault as world_module
from metering import policies as policies_module
from metering import report as report_module
from metering import runner as runner_module
from metering import trace as trace_module
from metering.events import Diagnose, Finish, Repair, Verify
from metering.hidden_fault import HiddenFaultSpec, HiddenFaultWorld
from metering.policies import (
    BalancedSearchPolicy,
    SeededRandomSearchPolicy,
    SequentialSearchPolicy,
)
from metering.report import regenerate_report
from metering.runner import run_hidden_fault


class ContractError(AssertionError):
    """A test-side helper was handed a value outside the documented schema."""


def jsonable(value: Any) -> Any:
    """Return the canonical public JSON representation of a protocol value."""

    if hasattr(value, "to_dict"):
        return jsonable(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ContractError(f"{type(value).__name__} is not deterministically serializable")


def recursive_keys(value: Any) -> set[str]:
    value = jsonable(value)
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(recursive_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(recursive_keys(item))
    return keys


def recursive_values_for_keys(value: Any, wanted: set[str]) -> list[Any]:
    value = jsonable(value)
    found: list[Any] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in wanted:
                found.append(item)
            found.extend(recursive_values_for_keys(item, wanted))
    elif isinstance(value, list):
        for item in value:
            found.extend(recursive_values_for_keys(item, wanted))
    return found


def get_path(mapping: Mapping[str, Any], *paths: str) -> Any:
    """Resolve the first dotted path that exists; fail rather than return None."""

    for path in paths:
        value: Any = mapping
        for part in path.split("."):
            if not isinstance(value, Mapping) or part not in value:
                break
            value = value[part]
        else:
            return value
    raise ContractError(f"none of these required artifact fields exists: {paths}")


class MeteringAPI:
    """Direct view of the production API used by the tests."""

    def __init__(self) -> None:
        self.world_module = world_module
        self.runner_module = runner_module
        self.policies_module = policies_module
        self.report_module = report_module
        self.trace_module = trace_module
        self.spec = HiddenFaultSpec.default()

    @property
    def fault_ids(self) -> tuple[str, ...]:
        return self.spec.fault_ids

    @property
    def test_ids(self) -> tuple[str, ...]:
        return tuple(test.test_id for test in self.spec.diagnostic_tests)

    def world(self, fault_id: str) -> HiddenFaultWorld:
        return HiddenFaultWorld(self.spec, fault_id)

    def public_description(self, world: HiddenFaultWorld) -> Any:
        return world.public_description()

    def action(self, kind: str, identifier: str | None = None) -> Any:
        factory = {
            "diagnose": Diagnose,
            "repair": Repair,
            "verify": Verify,
            "finish": Finish,
        }[kind]
        return factory(identifier) if identifier is not None else factory()

    def validate(self, world: HiddenFaultWorld, action: Any) -> Any:
        return world.validate_action(action)

    def apply(self, world: HiddenFaultWorld, action: Any) -> tuple[Any, Any]:
        return world.apply(action)

    def policy(self, name: str, *, seed: int | None = None) -> Any:
        if name == "seeded_random":
            if seed is not None:
                return SeededRandomSearchPolicy(seed)
            return SeededRandomSearchPolicy()
        if seed is not None:
            raise ContractError(f"policy {name!r} does not take a seed")
        return {
            "balanced": BalancedSearchPolicy,
            "sequential": SequentialSearchPolicy,
        }[name]()

    def run(
        self,
        *,
        harness: Any,
        fault_id: str,
        parent_dir: Path,
        budget: int = 32,
        run_id: str = "test-run",
    ) -> "RunArtifacts":
        parent = Path(parent_dir)
        parent.mkdir(parents=True, exist_ok=True)
        result = run_hidden_fault(
            harness,
            fault_id,
            parent / run_id,
            spec=self.spec,
            run_id=run_id,
            action_budget=budget,
        )
        return RunArtifacts.load(result.run_dir)

    def rebuild_report(self, run_dir: Path) -> Any:
        return regenerate_report(run_dir)


@dataclass
class RunArtifacts:
    FILENAMES = ("manifest.json", "events.jsonl", "reference.json", "report.json")

    run_dir: Path
    manifest: dict[str, Any]
    events: list[dict[str, Any]]
    reference: dict[str, Any]
    report: dict[str, Any]

    @classmethod
    def load(cls, run_dir: Path) -> "RunArtifacts":
        run_dir = Path(run_dir)
        for name in cls.FILENAMES:
            if not (run_dir / name).is_file():
                raise ContractError(f"missing required run artifact: {name}")
        manifest = json.loads((run_dir / "manifest.json").read_text())
        reference = json.loads((run_dir / "reference.json").read_text())
        report = json.loads((run_dir / "report.json").read_text())
        lines = (run_dir / "events.jsonl").read_text().splitlines()
        if not lines:
            raise ContractError("events.jsonl must not be empty")
        events = [json.loads(line) for line in lines]
        return cls(run_dir, manifest, events, reference, report)

    def reload(self) -> "RunArtifacts":
        return type(self).load(self.run_dir)

    def raw_hashes(self) -> dict[str, str]:
        return {
            name: sha256((self.run_dir / name).read_bytes()).hexdigest()
            for name in ("manifest.json", "events.jsonl", "reference.json")
        }


class ScriptedHarness:
    """Cooperative harness double implementing the typed in-process protocol."""

    name = "pytest-scripted-harness"
    version = "1"

    def __init__(self, actions: Sequence[Any] | None = None, *, repeat: Any = None):
        self._actions = list(actions or ())
        self._repeat = repeat
        self.public_inputs: list[Any] = []
        self.action_inputs: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.action_calls = 0

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {"kind": "pytest-double"},
            "seed_policy": {"kind": "none"},
        }

    def next_action(self, instance: Any, observations: Sequence[Any]) -> Any:
        self.action_calls += 1
        self.action_inputs.append(((instance, observations), {}))
        self.public_inputs.append(jsonable(instance))
        if self._actions:
            return self._actions.pop(0)
        if self._repeat is not None:
            return self._repeat
        raise AssertionError("controller requested an action after the script ended")


class CrashingHarness(ScriptedHarness):
    class DeliberateHarnessCrash(RuntimeError):
        pass

    def next_action(self, instance: Any, observations: Sequence[Any]) -> Any:
        self.action_calls += 1
        raise self.DeliberateHarnessCrash("intentional test crash")


# The tests' compact fact names, mapped to the exact report field spellings.
_VERIFICATION_FACTS = {
    "repair_matches": "selected_repair_matches_hidden_fault",
    "verified_after_final_repair": "verification_occurred_after_final_repair",
    "terminated_normally": "harness_terminated_normally",
    "budget_respected": "action_budget_was_respected",
    "success": "overall_task_success",
}
_RESOURCE_COUNTS = {
    "diagnostic": "diagnostic_observations",
    "repair": "repair_actions",
    "verification": "verification_actions",
    "total": "total_actions",
    "budget_exhausted": "budget_exhaustion",
}
_INFORMATION_VALUES = {
    "initial": "initial_uncertainty_bits",
    "removed": "total_uncertainty_removed_bits",
    "per_observation": "uncertainty_removed_per_diagnostic_observation_bits",
}


def verification_fact(report: Mapping[str, Any], name: str) -> bool:
    return bool(get_path(report, f"correctness.{_VERIFICATION_FACTS[name]}"))


def report_resources(report: Mapping[str, Any]) -> Mapping[str, Any]:
    value = get_path(report, "resources")
    if not isinstance(value, Mapping):
        raise ContractError("resource report must be an object of separate raw counts")
    return value


def resource_count(report: Mapping[str, Any], name: str) -> int | bool:
    return get_path(report_resources(report), _RESOURCE_COUNTS[name])


def information_value(report: Mapping[str, Any], name: str) -> Any:
    section = get_path(report, "diagnostic_information")
    if not isinstance(section, Mapping):
        raise ContractError("information report must be an object")
    if name == "remaining":
        progression = get_path(section, "progression")
        if not isinstance(progression, list):
            raise ContractError("information report must record its progression")
        return [get_path(item, "uncertainty_after_bits") for item in progression]
    return get_path(section, _INFORMATION_VALUES[name])


def artifact_set_id(document: Mapping[str, Any]) -> str:
    """Return the controller-owned identity binding one physical artifact set.

    The manifest, reference, and report carry it at top level; in the trace it
    lives in the run_started payload.
    """

    value = get_path(document, "artifact_set_id", "payload.artifact_set_id")
    if not isinstance(value, str) or not value:
        raise ContractError("artifact_set_id must be a non-empty string")
    return value


def report_raw_input_sha256(report: Mapping[str, Any]) -> dict[str, str]:
    """Normalize the report's hashes of its three byte-exact raw inputs."""

    section = get_path(report, "artifact_hashes")
    if not isinstance(section, Mapping):
        raise ContractError("raw input SHA-256 provenance must be an object")
    normalized: dict[str, str] = {}
    for filename, key in (
        ("manifest.json", "manifest_sha256"),
        ("events.jsonl", "events_sha256"),
        ("reference.json", "reference_sha256"),
    ):
        value = section.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ContractError(f"missing lowercase SHA-256 for {filename}")
        normalized[filename] = value
    return normalized


def event_type(event: Mapping[str, Any]) -> str:
    return str(get_path(event, "event_type"))


def event_payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    value = get_path(event, "payload")
    if not isinstance(value, Mapping):
        raise ContractError("event payload must be a structured object")
    return value


def event_step(event: Mapping[str, Any]) -> int:
    return int(get_path(event, "step"))


def canonical_events(events: Sequence[Mapping[str, Any]]) -> list[Any]:
    """Strip the two per-run identifiers so factual traces can be compared."""

    volatile = {"run_id", "artifact_set_id"}

    def clean(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: clean(item)
                for key, item in sorted(value.items())
                if key not in volatile
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return [clean(jsonable(event)) for event in events]


def termination_reason(events: Sequence[Mapping[str, Any]]) -> str:
    terminations = [
        event for event in events if event_type(event) == "termination"
    ]
    if not terminations:
        raise ContractError("trace has no explicit termination event")
    return str(get_path(event_payload(terminations[-1]), "reason")).lower()


def diagnostic_result(observation: Any) -> Any:
    data = jsonable(observation)
    if not isinstance(data, Mapping):
        raise ContractError("diagnostic observation must be typed and structured")
    return get_path(data, "positive")
