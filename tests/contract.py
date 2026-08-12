"""Test-side adapter for the small public API assumed by the tests.

The plan fixes concepts and module names, but it does not fix constructor or
function spellings.  Behavioural tests import only this module.  Supporting a
new spelling should require a small change here rather than weakening those
tests.

Expected production surface (accepted aliases are kept deliberately narrow):

* ``metering.events.Action`` with typed diagnose/repair/verify/finish factories;
* ``metering.hidden_fault`` exposes the canonical spec, its eight fault ids, and a
  ``HiddenFaultWorld`` (or ``make_world``);
* ``metering.runner.run`` executes one policy and writes a run directory;
* ``metering.policies`` exposes balanced, sequential, and seeded-random
  policies;
* ``metering.report.rebuild_report`` rebuilds ``report.json`` from a run dir.

The policy protocol itself is intentionally duck typed in the plan.  The test
harness doubles below implement the common ``start`` + ``next_action`` shape
and a few spelling aliases.  This is the sole compatibility boundary for that
uncertainty.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from hashlib import sha256
import importlib
import inspect
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


class ContractError(AssertionError):
    """The implementation does not expose a concept required by the plan."""


def _module(name: str):
    try:
        return importlib.import_module(f"metering.{name}")
    except ImportError as exc:  # a much clearer collection failure
        raise ContractError(f"cannot import required module metering.{name}") from exc


def _first_attr(obj: Any, names: Sequence[str], *, required: bool = True) -> Any:
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    if required:
        joined = ", ".join(names)
        raise ContractError(f"{obj!r} must expose one of: {joined}")
    return None


def jsonable(value: Any) -> Any:
    """Return the object's canonical public JSON representation when available."""
    # Typed protocol dataclasses often keep their discriminator as a ClassVar,
    # which dataclasses.asdict intentionally omits.  Their explicit encoder is
    # therefore authoritative at this boundary.
    if hasattr(value, "to_dict"):
        return jsonable(value.to_dict())
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Enum):
        return jsonable(value.value)
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        return {
            key: jsonable(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
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


def _ids_from_container(container: Any, names: Sequence[str]) -> tuple[str, ...] | None:
    if container is None:
        return None
    for name in names:
        if isinstance(container, Mapping) and name in container:
            raw = container[name]
        elif hasattr(container, name):
            raw = getattr(container, name)
        else:
            continue
        if callable(raw):
            raw = raw()
        if isinstance(raw, Mapping):
            return tuple(str(item) for item in raw.keys())
        result: list[str] = []
        for item in raw:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, Mapping):
                identifier = next(
                    (item[key] for key in ("id", "fault_id", "test_id", "name") if key in item),
                    None,
                )
                if identifier is None:
                    raise ContractError(f"catalogue entry has no identifier: {item!r}")
                result.append(str(identifier))
            else:
                identifier = _first_attr(
                    item, ("id", "fault_id", "test_id", "name"), required=False
                )
                if identifier is None:
                    raise ContractError(f"catalogue entry has no identifier: {item!r}")
                result.append(str(identifier))
        return tuple(result)
    return None


class MeteringAPI:
    """Small normalised view of the production API used by the tests."""

    def __init__(self) -> None:
        self.events_module = _module("events")
        self.world_module = _module("hidden_fault")
        self.runner_module = _module("runner")
        self.policies_module = _module("policies")
        self.report_module = _module("report")
        self.trace_module = _module("trace")
        self._spec: Any = None

    @property
    def spec(self) -> Any:
        if self._spec is not None:
            return self._spec
        factory = _first_attr(
            self.world_module,
            ("default_specification", "default_spec", "make_default_spec"),
            required=False,
        )
        if factory is not None:
            self._spec = factory()
            return self._spec
        value = _first_attr(
            self.world_module, ("DEFAULT_SPEC", "WORLD_SPEC", "SPEC"), required=False
        )
        if value is not None:
            self._spec = value() if callable(value) and inspect.isclass(value) else value
            return self._spec
        spec_class = _first_attr(
            self.world_module, ("HiddenFaultSpec", "WorldSpec"), required=False
        )
        if spec_class is not None:
            constructor = _first_attr(spec_class, ("default",), required=False)
            self._spec = constructor() if constructor else spec_class()
            return self._spec
        # A module-level catalogue plus a spec-less world is also a reasonable Metering API.
        self._spec = self.world_module
        return self._spec

    @property
    def fault_ids(self) -> tuple[str, ...]:
        ids = _ids_from_container(
            self.world_module, ("FAULT_IDS", "fault_ids", "HIDDEN_STATES")
        )
        ids = ids or _ids_from_container(
            self.spec, ("fault_ids", "faults", "hidden_states", "states")
        )
        if not ids:
            raise ContractError("hidden_fault must expose the complete fault-id catalogue")
        return ids

    def world(self, fault_id: str) -> Any:
        factory = _first_attr(
            self.world_module, ("make_world", "create_world"), required=False
        )
        if factory is not None:
            return self._call_world_factory(factory, fault_id)
        cls = _first_attr(self.world_module, ("HiddenFaultWorld", "World"))
        from_spec = _first_attr(cls, ("from_spec", "create"), required=False)
        if from_spec is not None:
            try:
                return from_spec(self.spec, hidden_fault=fault_id)
            except TypeError:
                try:
                    return from_spec(self.spec, fault_id=fault_id)
                except TypeError:
                    pass
        return self._call_world_factory(cls, fault_id)

    def _call_world_factory(self, factory: Callable[..., Any], fault_id: str) -> Any:
        signature = inspect.signature(factory)
        kwargs: dict[str, Any] = {}
        aliases = {
            "spec": self.spec,
            "specification": self.spec,
            "world_spec": self.spec,
            "hidden_fault": fault_id,
            "fault_id": fault_id,
            "hidden_state": fault_id,
            "state": fault_id,
        }
        for name, parameter in signature.parameters.items():
            if name in aliases:
                kwargs[name] = aliases[name]
            elif (
                parameter.default is inspect.Parameter.empty
                and parameter.kind
                not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            ):
                break
        else:
            return factory(**kwargs)
        # Deliberately limited positional fallbacks for simple constructors.
        for args in ((self.spec, fault_id), (fault_id, self.spec), (fault_id,)):
            try:
                return factory(*args)
            except TypeError:
                continue
        raise ContractError(f"cannot construct a hidden-fault world with {factory!r}")

    def public_description(self, world: Any) -> Any:
        value = _first_attr(
            world,
            ("public_description", "describe_public", "get_public_description"),
        )
        return value() if callable(value) else value

    @property
    def test_ids(self) -> tuple[str, ...]:
        ids = _ids_from_container(
            self.world_module, ("TEST_IDS", "DIAGNOSTIC_TEST_IDS", "diagnostic_tests")
        )
        ids = ids or _ids_from_container(
            self.spec,
            ("test_ids", "diagnostic_test_ids", "diagnostic_tests", "tests", "catalogue"),
        )
        if ids:
            return ids
        public = self.public_description(self.world(self.fault_ids[0]))
        ids = _ids_from_container(
            public,
            ("test_ids", "diagnostic_test_ids", "diagnostic_tests", "tests", "catalogue"),
        )
        if not ids:
            raise ContractError("public description must expose a diagnostic-test catalogue")
        return ids

    def action(self, kind: str, identifier: str | None = None) -> Any:
        # Separate typed command classes are the clearest implementation of the
        # plan and avoid trying to instantiate a typing-only ``Action`` union.
        typed_name = {
            "diagnose": "Diagnose",
            "repair": "Repair",
            "verify": "Verify",
            "finish": "Finish",
        }[kind]
        typed_cls = _first_attr(self.events_module, (typed_name,), required=False)
        if typed_cls is not None:
            return typed_cls(identifier) if identifier is not None else typed_cls()

        action_cls = _first_attr(self.events_module, ("Action",))
        factory = _first_attr(action_cls, (kind,), required=False)
        if factory is not None:
            return factory(identifier) if identifier is not None else factory()
        module_factory = _first_attr(
            self.events_module, (kind, f"{kind}_action", f"make_{kind}"), required=False
        )
        if module_factory is not None:
            return module_factory(identifier) if identifier is not None else module_factory()

        # Typed dataclass fallback.  This remains here because the plan mandates a
        # typed command but leaves its constructor spelling open.
        kind_parameter = next(
            (name for name in ("kind", "type", "action_type") if name in inspect.signature(action_cls).parameters),
            None,
        )
        if kind_parameter is None:
            raise ContractError("Action needs typed factories or a kind/type constructor")
        kwargs: dict[str, Any] = {kind_parameter: kind}
        if identifier is not None:
            id_name = "test_id" if kind == "diagnose" else "fault_id"
            if id_name in inspect.signature(action_cls).parameters:
                kwargs[id_name] = identifier
            elif "target_id" in inspect.signature(action_cls).parameters:
                kwargs["target_id"] = identifier
            elif "payload" in inspect.signature(action_cls).parameters:
                kwargs["payload"] = {id_name: identifier}
            else:
                raise ContractError(f"Action constructor cannot carry {id_name}")
        return action_cls(**kwargs)

    def validate(self, world: Any, action: Any) -> Any:
        function = _first_attr(world, ("validate_action", "validate"))
        return function(action)

    def apply(self, world: Any, action: Any) -> tuple[Any, Any]:
        function = _first_attr(world, ("apply_action", "apply"))
        result = function(action)
        if isinstance(result, tuple) and len(result) == 2:
            return result
        if hasattr(result, "observation") and hasattr(result, "cost"):
            return result.observation, result.cost
        if isinstance(result, Mapping) and "observation" in result and "cost" in result:
            return result["observation"], result["cost"]
        raise ContractError("World.apply must return an observation and raw action cost")

    def policy(self, name: str, *, seed: int | None = None) -> Any:
        candidates = {
            "balanced": ("BalancedSearchPolicy", "BalancedPolicy", "BalancedSearch"),
            "sequential": ("SequentialSearchPolicy", "SequentialPolicy", "SequentialSearch"),
            "seeded_random": (
                "SeededRandomSearchPolicy",
                "SeededRandomPolicy",
                "RandomSearchPolicy",
            ),
        }
        cls = _first_attr(self.policies_module, candidates[name])
        signature = inspect.signature(cls)
        kwargs: dict[str, Any] = {}
        for parameter in signature.parameters.values():
            if parameter.name in ("spec", "world_spec", "specification"):
                kwargs[parameter.name] = self.spec
            elif parameter.name in ("seed", "random_seed") and seed is not None:
                kwargs[parameter.name] = seed
            elif (
                parameter.default is inspect.Parameter.empty
                and parameter.kind
                not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            ):
                raise ContractError(
                    f"cannot supply required {cls.__name__} parameter {parameter.name!r}"
                )
        return cls(**kwargs)

    def run(
        self,
        *,
        harness: Any,
        fault_id: str,
        parent_dir: Path,
        budget: int = 32,
        run_id: str = "test-run",
        seed: int | None = None,
    ) -> "RunArtifacts":
        parent_dir.mkdir(parents=True, exist_ok=True)
        requested_dir = parent_dir / run_id
        function = _first_attr(
            self.runner_module, ("run", "run_episode", "run_experiment", "execute_run"), required=False
        )
        world = self.world(fault_id)
        result: Any
        if function is not None:
            signature = inspect.signature(function)
            kwargs: dict[str, Any] = {}
            concept = {
                "harness": harness,
                "policy": harness,
                "agent": harness,
                "world": world,
                "instance": world,
                "spec": self.spec,
                "world_spec": self.spec,
                "hidden_fault": fault_id,
                "fault_id": fault_id,
                "hidden_state": fault_id,
                "run_dir": requested_dir,
                "output_dir": requested_dir,
                "artifact_dir": requested_dir,
                "artifacts_dir": requested_dir,
                "action_budget": budget,
                "budget": budget,
                "max_actions": budget,
                "run_id": run_id,
                "seed": seed,
                "random_seed": seed,
            }
            missing: list[str] = []
            for parameter in signature.parameters.values():
                if parameter.name in concept and concept[parameter.name] is not None:
                    kwargs[parameter.name] = concept[parameter.name]
                elif (
                    parameter.default is inspect.Parameter.empty
                    and parameter.kind
                    not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                ):
                    missing.append(parameter.name)
            if missing:
                raise ContractError(
                    f"runner function has unmapped required parameters: {missing}"
                )
            result = function(**kwargs)
        else:
            controller_cls = _first_attr(self.runner_module, ("Controller",))
            signature = inspect.signature(controller_cls)
            kwargs = {}
            available = {
                "world": world,
                "harness": harness,
                "policy": harness,
                "action_budget": budget,
                "budget": budget,
                "run_id": run_id,
            }
            for parameter in signature.parameters.values():
                if parameter.name in available:
                    kwargs[parameter.name] = available[parameter.name]
                elif parameter.default is inspect.Parameter.empty:
                    raise ContractError(
                        f"Controller has unmapped required parameter {parameter.name!r}"
                    )
            controller = controller_cls(**kwargs)
            method = _first_attr(controller, ("run", "execute"))
            try:
                result = method(run_dir=requested_dir)
            except TypeError:
                result = method(requested_dir)

        candidates = [requested_dir, parent_dir]
        if isinstance(result, (str, Path)):
            candidates.insert(0, Path(result))
        else:
            returned_dir = _first_attr(result, ("run_dir", "artifact_dir"), required=False) if result is not None else None
            if returned_dir is not None:
                candidates.insert(0, Path(returned_dir))
        located = locate_run_dir(candidates)
        return RunArtifacts.load(located)

    def rebuild_report(self, run_dir: Path) -> Any:
        function = _first_attr(
            self.report_module,
            ("rebuild_report", "regenerate_report", "rebuild_report_from_artifacts", "replay_report"),
        )
        signature = inspect.signature(function)
        if len(signature.parameters) == 1:
            return function(run_dir)
        kwargs: dict[str, Any] = {}
        for name, parameter in signature.parameters.items():
            if name in ("run_dir", "artifact_dir", "path"):
                kwargs[name] = run_dir
            elif name in ("spec", "world_spec"):
                kwargs[name] = self.spec
            elif parameter.default is inspect.Parameter.empty:
                raise ContractError(f"cannot supply rebuild_report parameter {name!r}")
        return function(**kwargs)


def locate_run_dir(candidates: Iterable[Path]) -> Path:
    seen: set[Path] = set()
    for raw in candidates:
        candidate = Path(raw)
        if candidate in seen:
            continue
        seen.add(candidate)
        if all((candidate / name).is_file() for name in RunArtifacts.FILENAMES):
            return candidate
        if candidate.exists():
            matches = [
                path.parent
                for path in candidate.rglob("manifest.json")
                if all((path.parent / name).is_file() for name in RunArtifacts.FILENAMES)
            ]
            if len(matches) == 1:
                return matches[0]
    raise ContractError(
        "a completed run must contain manifest.json, events.jsonl, reference.json, and report.json"
    )


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
    """Cooperative harness double implementing the Metering in-process protocol."""

    name = "pytest-scripted-harness"
    version = "1"

    def __init__(self, actions: Sequence[Any] | None = None, *, repeat: Any = None):
        self._actions = list(actions or ())
        self._repeat = repeat
        self.public_inputs: list[Any] = []
        self.action_inputs: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.action_calls = 0

    def start(self, public_description: Any) -> None:
        self.public_inputs.append(jsonable(public_description))

    reset = start
    initialize = start

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {"kind": "pytest-double"},
            "seed_policy": {"kind": "none"},
        }

    def next_action(self, *args: Any, **kwargs: Any) -> Any:
        self.action_calls += 1
        self.action_inputs.append((args, kwargs))
        if not self.public_inputs:
            # In the stateless protocol the public description is normally the
            # first positional argument or an explicitly named keyword.
            public = next(
                (kwargs[key] for key in ("public_description", "instance", "public_instance") if key in kwargs),
                args[0] if args else None,
            )
            if public is not None:
                self.public_inputs.append(jsonable(public))
        if self._actions:
            return self._actions.pop(0)
        if self._repeat is not None:
            return self._repeat
        raise AssertionError("controller requested an action after the script ended")

    choose_action = next_action
    choose_next_action = next_action
    act = next_action
    __call__ = next_action


class CrashingHarness(ScriptedHarness):
    class DeliberateHarnessCrash(RuntimeError):
        pass

    def next_action(self, *args: Any, **kwargs: Any) -> Any:
        self.action_calls += 1
        raise self.DeliberateHarnessCrash("intentional test crash")

    choose_action = next_action
    choose_next_action = next_action
    act = next_action
    __call__ = next_action


def get_path(mapping: Mapping[str, Any], *paths: str) -> Any:
    """Resolve one documented schema spelling; fail rather than return None."""
    for path in paths:
        value: Any = mapping
        for part in path.split("."):
            if not isinstance(value, Mapping) or part not in value:
                break
            value = value[part]
        else:
            return value
    raise ContractError(f"none of these required artifact fields exists: {paths}")


def report_verification(report: Mapping[str, Any]) -> Mapping[str, Any]:
    value = get_path(report, "verification", "verifier", "correctness")
    if not isinstance(value, Mapping):
        raise ContractError("verification report must be an object of separate facts")
    return value


def verification_fact(report: Mapping[str, Any], name: str) -> bool:
    aliases = {
        "repair_matches": (
            "repair_matches_hidden_fault",
            "selected_repair_matches_hidden_fault",
            "selected_repair_matches_fault",
            "repair_matches_fault",
        ),
        "verified_after_final_repair": (
            "verification_after_final_repair",
            "verification_occurred_after_final_repair",
            "verified_after_final_repair",
        ),
        "terminated_normally": (
            "terminated_normally",
            "harness_terminated_normally",
            "normal_termination",
        ),
        "budget_respected": (
            "action_budget_respected",
            "action_budget_was_respected",
            "budget_respected",
        ),
        "success": ("overall_success", "overall_task_success", "task_success", "success"),
    }
    section = report_verification(report)
    return bool(get_path(section, *aliases[name]))


def report_resources(report: Mapping[str, Any]) -> Mapping[str, Any]:
    value = get_path(report, "resources", "resource_cost", "raw_resource_cost")
    if not isinstance(value, Mapping):
        raise ContractError("resource report must be an object of separate raw counts")
    return value


def resource_count(report: Mapping[str, Any], name: str) -> int | bool:
    aliases = {
        "diagnostic": ("diagnostic_observations", "diagnostic_actions"),
        "repair": ("repair_actions",),
        "verification": ("verification_actions", "verify_actions"),
        "total": ("total_actions",),
        "budget_exhausted": ("budget_exhaustion", "budget_exhausted"),
    }
    return get_path(report_resources(report), *aliases[name])


def report_information(report: Mapping[str, Any]) -> Mapping[str, Any]:
    value = get_path(
        report, "information", "diagnostic_information", "diagnostic_information_exposure"
    )
    if not isinstance(value, Mapping):
        raise ContractError("information report must be an object")
    return value


def information_value(report: Mapping[str, Any], name: str) -> Any:
    aliases = {
        "initial": ("initial_uncertainty_bits", "initial_uncertainty"),
        "removed": (
            "total_uncertainty_removed_bits",
            "uncertainty_removed_bits",
            "total_information_exposed_bits",
        ),
        "per_observation": (
            "uncertainty_removed_per_diagnostic_observation_bits",
            "information_per_diagnostic_observation_bits",
            "bits_per_diagnostic_observation",
        ),
    }
    section = report_information(report)
    if name == "remaining":
        # The plan asks for uncertainty after *each* diagnostic result.  Some
        # reports expose that as a direct list; the canonical Metering report keeps a
        # richer progression with the same values.
        for key in (
            "uncertainty_remaining_bits",
            "remaining_after_each_diagnostic_bits",
        ):
            if key in section:
                return section[key]
        progression = section.get("progression")
        if isinstance(progression, list):
            return [
                get_path(item, "uncertainty_after_bits", "remaining_uncertainty_bits")
                for item in progression
            ]
        value = get_path(section, "remaining_uncertainty_bits")
        return [] if not section.get("diagnostic_observations") else [value]
    return get_path(section, *aliases[name])



def artifact_set_id(document: Mapping[str, Any]) -> str:
    """Return the controller-owned identity binding one physical artifact set."""
    value = get_path(
        document,
        "artifact_set_id",
        "artifact_set_identifier",
        "provenance.artifact_set_id",
        "artifact_provenance.artifact_set_id",
        "payload.artifact_set_id",
    )
    if not isinstance(value, str) or not value:
        raise ContractError("artifact_set_id must be a non-empty string")
    return value


def report_raw_input_sha256(report: Mapping[str, Any]) -> dict[str, str]:
    """Normalize the report's hashes of its three byte-exact raw inputs."""
    section = get_path(
        report,
        "raw_input_sha256",
        "raw_input_hashes",
        "provenance.raw_input_sha256",
        "provenance.raw_input_hashes",
        "artifact_provenance.raw_input_sha256",
        "artifact_hashes",
    )
    if not isinstance(section, Mapping):
        raise ContractError("raw input SHA-256 provenance must be an object")
    aliases = {
        "manifest.json": ("manifest.json", "manifest", "manifest_sha256"),
        "events.jsonl": ("events.jsonl", "events", "events_sha256"),
        "reference.json": ("reference.json", "reference", "reference_sha256"),
    }
    normalized: dict[str, str] = {}
    for filename, names in aliases.items():
        value = next((section[name] for name in names if name in section), None)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ContractError(f"missing lowercase SHA-256 for {filename}")
        normalized[filename] = value
    return normalized

def event_type(event: Mapping[str, Any]) -> str:
    return str(get_path(event, "event_type", "type"))


def event_payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    value = get_path(event, "payload")
    if not isinstance(value, Mapping):
        raise ContractError("event payload must be a structured object")
    return value


def event_step(event: Mapping[str, Any]) -> int:
    return int(get_path(event, "step", "step_number"))


def canonical_events(events: Sequence[Mapping[str, Any]]) -> list[Any]:
    volatile = {
        "run_id",
        "run_identifier",
        # Controller-owned nonce binds one physical artifact set.  It is
        # intentionally ignored only when comparing factual policy/world replay.
        "artifact_set_id",
        "artifact_set_identifier",
        "timestamp",
        "wall_clock_timestamp",
        "created_at",
        "finished_at",
        "duration",
        "path",
        "run_dir",
    }

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
    candidates = [event for event in events if "terminat" in event_type(event).lower()]
    if not candidates:
        raise ContractError("trace has no explicit termination event")
    payload = event_payload(candidates[-1])
    value = get_path(payload, "reason", "termination_reason", "status")
    return str(value).lower()


def diagnostic_result(observation: Any) -> Any:
    data = jsonable(observation)
    if isinstance(data, Mapping) and "observation" in data:
        data = data["observation"]
    if not isinstance(data, Mapping):
        raise ContractError("diagnostic observation must be typed and structured")
    return get_path(data, "result", "value", "positive", "passed", "outcome")
