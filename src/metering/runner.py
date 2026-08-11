"""In-process v0 controller and run-artifact orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Mapping
import uuid

from .binding import (
    REFERENCE_COMMITMENT_ALGORITHM,
    compute_reference_commitment,
)
from .events import (
    Action,
    Event,
    EventError,
    Finish,
    Observation,
    RawActionCost,
    action_to_dict,
    observation_to_dict,
)
from .hidden_fault import (
    DEFAULT_INSTANCE_ID,
    ActionValidation,
    HiddenFaultSpec,
    HiddenFaultWorld,
)
from .policies import HarnessPolicy
from .provenance import implementation_provenance
from .report import (
    EVENT_INTERACTION,
    EVENT_PROTOCOL_ERROR,
    EVENT_RUN_STARTED,
    EVENT_TERMINATION,
    MANIFEST_SCHEMA_VERSION,
    TERMINATION_BUDGET_EXHAUSTED,
    TERMINATION_HARNESS_CRASH,
    TERMINATION_INVALID_ACTION,
    TERMINATION_NORMAL,
    build_report,
)
from .trace import (
    RunPaths,
    TraceWriter,
    read_events,
    sha256_hex,
    write_json_atomic,
)

DEFAULT_ACTION_BUDGET = 16


class RunnerError(RuntimeError):
    """Raised when a run cannot be configured or its artifacts cannot be made."""


@dataclass(frozen=True, slots=True)
class ControllerOutcome:
    termination_reason: str
    actions_used: int
    observations: tuple[Observation, ...]


@dataclass(frozen=True, slots=True)
class RunResult:
    """Paths and decoded results of one completed artifact-producing run."""

    paths: RunPaths
    manifest: Mapping[str, Any]
    events: tuple[Event, ...]
    reference: Mapping[str, Any]
    report: Mapping[str, Any]

    @property
    def run_dir(self) -> Path:
        return self.paths.run_dir

    @property
    def succeeded(self) -> bool:
        correctness = self.report.get("correctness")
        return bool(
            isinstance(correctness, Mapping)
            and correctness.get("overall_task_success") is True
        )


def _is_canonical_uuid4(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value


class Controller:
    """Own the v0 action loop and record canonical public events.

    The policy receives only the immutable public instance and the observation
    tuple delivered so far.  The controller never passes it the world or the
    controller-private reference state.  This is a cooperative in-process
    boundary; it is intentionally not process isolation or a hostile sandbox.
    """

    def __init__(
        self,
        world: HiddenFaultWorld,
        policy: HarnessPolicy,
        trace: TraceWriter,
        *,
        run_id: str,
        artifact_set_id: str,
        action_budget: int = DEFAULT_ACTION_BUDGET,
    ) -> None:
        if type(world) is not HiddenFaultWorld:
            raise RunnerError("world must be an exact HiddenFaultWorld in v0")
        if type(run_id) is not str or not run_id:
            raise RunnerError("run_id must be a non-empty string")
        if not _is_canonical_uuid4(artifact_set_id):
            raise RunnerError("artifact_set_id must be a canonical UUID4 string")
        if type(action_budget) is not int or action_budget < 1:
            raise RunnerError("action_budget must be a positive integer")
        self.world = world
        self.policy = policy
        self.trace = trace
        self.run_id = run_id
        self.artifact_set_id = artifact_set_id
        self.action_budget = action_budget
        self._actions_used = 0
        self._observations: list[Observation] = []

    def _event(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        resources: RawActionCost | None = None,
    ) -> Event:
        public = self.world.public_description()
        return Event(
            run_id=self.run_id,
            world_id=public.world_id,
            world_version=public.world_version,
            instance_id=public.instance_id,
            instance_version=public.instance_version,
            step=self.trace.next_step,
            event_type=event_type,
            payload=payload,
            resources=resources or RawActionCost.zero(),
        )

    def _terminate(self, reason: str) -> ControllerOutcome:
        self.trace.append(
            self._event(
                EVENT_TERMINATION,
                {
                    "reason": reason,
                    "normal": reason == TERMINATION_NORMAL,
                    "actions_used": self._actions_used,
                    "action_budget": self.action_budget,
                },
            )
        )
        return ControllerOutcome(
            termination_reason=reason,
            actions_used=self._actions_used,
            observations=tuple(self._observations),
        )

    def run(self) -> ControllerOutcome:
        public = self.world.public_description()
        self.trace.append(
            self._event(
                EVENT_RUN_STARTED,
                {
                    "action_budget": self.action_budget,
                    "artifact_set_id": self.artifact_set_id,
                    "public_instance": public.to_dict(),
                },
            )
        )

        while True:
            # No B+1 request is made.  A finish applied as action B is handled
            # below before this boundary is considered again.
            if self._actions_used >= self.action_budget:
                return self._terminate(TERMINATION_BUDGET_EXHAUSTED)

            try:
                output = self.policy.next_action(public, tuple(self._observations))
            except Exception:
                # Exception text is deliberately not interpreted by any meter.
                # Hard process exits and callbacks that never return are outside
                # the cooperative in-process v0 boundary.
                return self._terminate(TERMINATION_HARNESS_CRASH)

            validation: ActionValidation = self.world.validate_action(output)
            attempted_action: dict[str, Any] | None
            try:
                attempted_action = action_to_dict(output)  # type: ignore[arg-type]
            except EventError:
                attempted_action = None

            if not validation.valid:
                self._actions_used += 1
                self.trace.append(
                    self._event(
                        EVENT_PROTOCOL_ERROR,
                        {
                            "code": validation.code,
                            "message": validation.message,
                            "received_type": type(output).__name__,
                            "attempted_action": attempted_action,
                        },
                        RawActionCost(total_actions=1),
                    )
                )
                return self._terminate(TERMINATION_INVALID_ACTION)

            action: Action = output  # type: ignore[assignment]
            observation, cost = self.world.apply(action)
            self._actions_used += cost.total_actions
            self._observations.append(observation)
            self.trace.append(
                self._event(
                    EVENT_INTERACTION,
                    {
                        "action": action_to_dict(action),
                        "observation": observation_to_dict(observation),
                    },
                    cost,
                )
            )

            # A valid finish at exactly the budget boundary is normal success,
            # not budget exhaustion.
            if isinstance(action, Finish):
                return self._terminate(TERMINATION_NORMAL)
            if self._actions_used >= self.action_budget:
                return self._terminate(TERMINATION_BUDGET_EXHAUSTED)


def _validate_policy_json(value: object, name: str) -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise RunnerError(f"{name} contains a non-finite number")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_policy_json(item, f"{name}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise RunnerError(f"{name} contains a non-string key")
            _validate_policy_json(item, f"{name}.{key}")
        return
    raise RunnerError(f"{name} contains a non-JSON value")


def _policy_descriptor(policy: object) -> dict[str, Any]:
    descriptor_method = getattr(policy, "descriptor", None)
    if not callable(descriptor_method):
        raise RunnerError(
            "canonical v0 policies must declare descriptor() with name, version, "
            "configuration, and seed policy"
        )
    raw = descriptor_method()
    if type(raw) is not dict:
        raise RunnerError("policy descriptor must be an exact object")
    descriptor = raw
    if set(descriptor) != {"name", "version", "configuration", "seed_policy"}:
        raise RunnerError("policy descriptor has missing or unexpected fields")
    for key in ("name", "version"):
        if type(descriptor[key]) is not str or not descriptor[key]:
            raise RunnerError("policy name and version must be non-empty strings")
    if type(descriptor["configuration"]) is not dict:
        raise RunnerError("policy configuration must be an exact object")
    _validate_policy_json(descriptor["configuration"], "policy configuration")
    seed_policy = descriptor["seed_policy"]
    if type(seed_policy) is not dict or type(seed_policy.get("kind")) is not str:
        raise RunnerError("policy seed_policy must be a declared object")
    if seed_policy["kind"] == "none":
        if set(seed_policy) != {"kind"}:
            raise RunnerError("unseeded policy declaration has unexpected fields")
    elif seed_policy["kind"] == "fixed":
        if set(seed_policy) != {"kind", "seed"} or type(seed_policy["seed"]) is not int:
            raise RunnerError("fixed seed policy requires one exact integer seed")
    else:
        raise RunnerError("unknown policy seed declaration")
    _validate_policy_json(descriptor, "policy descriptor")
    try:
        return json.loads(json.dumps(descriptor, allow_nan=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise RunnerError("policy descriptor must contain finite JSON values") from exc


def _prepare_run_directory(run_dir: str | Path) -> RunPaths:
    path = Path(run_dir)
    if path.exists():
        if not path.is_dir():
            raise RunnerError(f"run path is not a directory: {path}")
        if any(path.iterdir()):
            raise RunnerError(f"run directory is not empty: {path}")
    else:
        path.mkdir(parents=True)
    return RunPaths.at(path)


def run_experiment(
    world: HiddenFaultWorld,
    policy: HarnessPolicy,
    run_dir: str | Path,
    *,
    run_id: str | None = None,
    action_budget: int = DEFAULT_ACTION_BUDGET,
    sync_trace: bool = False,
) -> RunResult:
    """Run one policy/world pair and write the four bound v0 artifacts."""

    if type(world) is not HiddenFaultWorld:
        raise RunnerError("world must be an exact HiddenFaultWorld in v0")
    if type(action_budget) is not int or action_budget < 1:
        raise RunnerError("action_budget must be a positive integer")
    if run_id is None:
        actual_run_id = str(uuid.uuid4())
    elif type(run_id) is str and run_id:
        actual_run_id = run_id
    else:
        raise RunnerError("run_id must be None or a non-empty string")

    # This binding identifier is controller-owned and never derived from the
    # caller's display-oriented run_id.
    artifact_set_id = str(uuid.uuid4())
    reference_binding_nonce = str(uuid.uuid4())
    generated_instance = world.generated_instance_reference()
    reference_commitment = compute_reference_commitment(
        artifact_set_id,
        reference_binding_nonce,
        generated_instance,
    )
    descriptor = _policy_descriptor(policy)
    paths = _prepare_run_directory(run_dir)
    public = world.public_description()
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_set_id": artifact_set_id,
        "reference_commitment": {
            "algorithm": REFERENCE_COMMITMENT_ALGORITHM,
            "digest": reference_commitment,
        },
        "run_id": actual_run_id,
        "world": {
            "world_id": public.world_id,
            "world_version": public.world_version,
        },
        "instance": public.to_dict(),
        "world_specification": world.spec.to_dict(),
        "controller": {"action_budget": action_budget},
        "policy": descriptor,
        "execution_boundary": {
            "kind": "cooperative_in_process",
            "hostile_code_sandbox_enforced": False,
        },
        "reproducibility": {
            "generated_instance_materialized": True,
            "event_timestamps_in_deterministic_comparison": False,
            "artifact_binding": "sha256",
        },
        "implementation": implementation_provenance(),
    }
    write_json_atomic(paths.manifest, manifest)

    with TraceWriter(paths.events, sync=sync_trace) as trace:
        Controller(
            world,
            policy,
            trace,
            run_id=actual_run_id,
            artifact_set_id=artifact_set_id,
            action_budget=action_budget,
        ).run()

    # Hash only after the append-only event writer is closed.  Both source
    # artifacts were written canonically, and the events hash covers the exact
    # bytes on disk.
    manifest_bytes = paths.manifest.read_bytes()
    events_bytes = paths.events.read_bytes()
    reference = {
        **world.final_reference_state(),
        "artifact_set_id": artifact_set_id,
        "binding_nonce": reference_binding_nonce,
        "run_id": actual_run_id,
        "world_id": public.world_id,
        "world_version": public.world_version,
        "instance_id": public.instance_id,
        "instance_version": public.instance_version,
        "artifact_hashes": {
            "algorithm": REFERENCE_COMMITMENT_ALGORITHM,
            "manifest_sha256": sha256_hex(manifest_bytes),
            "events_sha256": sha256_hex(events_bytes),
        },
    }
    write_json_atomic(paths.reference, reference, private=True)
    reference_bytes = paths.reference.read_bytes()

    # Meters run only after world execution, binding, and tracing are complete.
    events = read_events(paths.events)
    report = build_report(
        manifest,
        events,
        reference,
        artifact_bytes={
            "manifest": manifest_bytes,
            "events": events_bytes,
            "reference": reference_bytes,
        },
    )
    write_json_atomic(paths.report, report)
    return RunResult(paths, manifest, events, reference, report)


def run_hidden_fault(
    policy: HarnessPolicy,
    hidden_fault_id: str,
    run_dir: str | Path,
    *,
    spec: HiddenFaultSpec | None = None,
    instance_id: str = DEFAULT_INSTANCE_ID,
    run_id: str | None = None,
    action_budget: int = DEFAULT_ACTION_BUDGET,
    sync_trace: bool = False,
) -> RunResult:
    """Create one v0 hidden-fault instance and run a cooperative policy."""

    actual_spec = spec or HiddenFaultSpec.v0()
    world = HiddenFaultWorld.from_spec(
        actual_spec, hidden_fault_id, instance_id=instance_id
    )
    return run_experiment(
        world,
        policy,
        run_dir,
        run_id=run_id,
        action_budget=action_budget,
        sync_trace=sync_trace,
    )
