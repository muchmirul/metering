"""In-process Metering controller and run-artifact orchestration.

The controller owns the loop that turns a policy into a trace.  It hands the
policy a truth-free public instance plus the observations delivered so far,
takes back exactly one typed action, charges it against the budget, routes it
through the world, and records the result as one canonical event.

Around that loop, :func:`run_experiment` produces the four files of a run in a
fixed order.  The manifest is written before the policy starts and already
contains a salted commitment to the generated truth.  The trace is appended
during execution.  The private reference is written afterwards and binds the
exact bytes of the first two files.  Only then do the meters run, which is what
makes a report a claim about artifacts that already exist rather than about a
process the reader has to trust.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping
import uuid

from .binding import REFERENCE_COMMITMENT_ALGORITHM, compute_reference_commitment
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
    HiddenFaultSpec,
    HiddenFaultWorld,
)
from .policies import HarnessPolicy
from .provenance import implementation_provenance
from .report import build_report
from .schema import (
    EVENT_INTERACTION,
    EVENT_PROTOCOL_ERROR,
    EVENT_RUN_STARTED,
    EVENT_TERMINATION,
    MANIFEST_SCHEMA_VERSION,
    TERMINATION_BUDGET_EXHAUSTED,
    TERMINATION_HARNESS_CRASH,
    TERMINATION_INVALID_ACTION,
    TERMINATION_NORMAL,
    StrictFields,
)
from .trace import RunPaths, TraceWriter, read_events, sha256_hex, write_json_atomic

DEFAULT_ACTION_BUDGET = 16

_DESCRIPTOR_FIELDS = ("name", "version", "configuration", "seed_policy")


class RunnerError(RuntimeError):
    """Raised when a run cannot be configured or its artifacts cannot be made."""


_check = StrictFields(RunnerError)


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


class Controller:
    """Own the Metering action loop and record canonical public events.

    The policy receives only the immutable public instance and the observations
    delivered so far.  The controller never passes it the world object or the
    private reference state.  This is a cooperative in-process boundary, which
    prevents accidental disclosure through the documented API and provides no
    protection against code that sets out to break the rules.

    Input validation lives in :func:`run_experiment`, the entry point that
    creates controllers, because it must reject bad input before it touches
    the filesystem.  The controller trusts what it is given.
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

    def _reject(self, output: object, code: str, message: str) -> ControllerOutcome:
        """Record a rejected action, charge it, and terminate the run.

        A rejected attempt still costs one unit of budget.  Charging it is what
        stops a harness from probing the validator for free, and recording the
        attempt keeps the failure explicit instead of silently repaired.
        """

        try:
            attempted_action: dict[str, Any] | None = action_to_dict(output)  # type: ignore[arg-type]
        except EventError:
            attempted_action = None
        self._actions_used += 1
        self.trace.append(
            self._event(
                EVENT_PROTOCOL_ERROR,
                {
                    "code": code,
                    "message": message,
                    "received_type": type(output).__name__,
                    "attempted_action": attempted_action,
                },
                RawActionCost(total_actions=1),
            )
        )
        return self._terminate(TERMINATION_INVALID_ACTION)

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

        # Budget is enforced once, after each charged action.  The loop is
        # entered only with budget remaining, so no request is ever made past
        # the budget: run_experiment requires a budget of at least one, and
        # every iteration that spends the last unit terminates below.
        while True:
            try:
                output = self.policy.next_action(public, tuple(self._observations))
            except Exception:
                # The exception text is deliberately not recorded or
                # interpreted.  Hard process exits and callbacks that never
                # return are outside this cooperative boundary entirely.
                return self._terminate(TERMINATION_HARNESS_CRASH)

            validation = self.world.validate_action(output)
            if not validation.valid:
                return self._reject(output, validation.code, validation.message)

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

            # A valid finish at exactly the budget boundary is normal success
            # rather than budget exhaustion.
            if isinstance(action, Finish):
                return self._terminate(TERMINATION_NORMAL)
            if self._actions_used >= self.action_budget:
                return self._terminate(TERMINATION_BUDGET_EXHAUSTED)


def _policy_descriptor(policy: object) -> dict[str, Any]:
    """Require a complete, finite JSON descriptor from the policy.

    Metering records how a run was configured rather than inferring it later.
    A policy that does not declare its name, version, configuration, and seed
    policy is rejected before the run starts, because its result would not be
    reproducible by anyone reading the artifacts.
    """

    descriptor_method = getattr(policy, "descriptor", None)
    if not callable(descriptor_method):
        raise RunnerError(
            "canonical Metering policies must declare descriptor() with name, "
            "version, configuration, and seed policy"
        )
    descriptor = descriptor_method()
    if type(descriptor) is not dict or set(descriptor) != set(_DESCRIPTOR_FIELDS):
        raise RunnerError("policy descriptor has missing or unexpected fields")
    for key in ("name", "version"):
        if type(descriptor[key]) is not str or not descriptor[key]:
            raise RunnerError("policy name and version must be non-empty strings")
    if type(descriptor["configuration"]) is not dict:
        raise RunnerError("policy configuration must be an exact object")

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

    _check.finite_json(descriptor, "policy descriptor")
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


def _build_manifest(
    world: HiddenFaultWorld,
    descriptor: Mapping[str, Any],
    *,
    run_id: str,
    artifact_set_id: str,
    reference_commitment: str,
    action_budget: int,
) -> dict[str, Any]:
    """Describe the run completely enough to replay it, without the truth."""

    public = world.public_description()
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_set_id": artifact_set_id,
        "reference_commitment": {
            "algorithm": REFERENCE_COMMITMENT_ALGORITHM,
            "digest": reference_commitment,
        },
        "run_id": run_id,
        "world": {
            "world_id": public.world_id,
            "world_version": public.world_version,
        },
        "instance": public.to_dict(),
        "world_specification": world.spec.to_dict(),
        "controller": {"action_budget": action_budget},
        "policy": dict(descriptor),
        # These two blocks state what the artifact does and does not promise,
        # and strict replay refuses a manifest that claims more.
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


def run_experiment(
    world: HiddenFaultWorld,
    policy: HarnessPolicy,
    run_dir: str | Path,
    *,
    run_id: str | None = None,
    action_budget: int = DEFAULT_ACTION_BUDGET,
    sync_trace: bool = False,
) -> RunResult:
    """Run one policy and world pair and write the four bound Metering artifacts."""

    if type(world) is not HiddenFaultWorld:
        raise RunnerError("world must be an exact HiddenFaultWorld in Metering")
    if type(action_budget) is not int or action_budget < 1:
        raise RunnerError("action_budget must be a positive integer")
    if run_id is None:
        actual_run_id = str(uuid.uuid4())
    elif type(run_id) is str and run_id:
        actual_run_id = run_id
    else:
        raise RunnerError("run_id must be None or a non-empty string")

    # The binding identifier is controller-owned and never derived from the
    # caller's display-oriented run_id, so two runs sharing a label still have
    # artifacts that cannot be mixed.
    artifact_set_id = str(uuid.uuid4())
    reference_binding_nonce = str(uuid.uuid4())
    reference_commitment = compute_reference_commitment(
        artifact_set_id,
        reference_binding_nonce,
        world.generated_instance_reference(),
    )
    descriptor = _policy_descriptor(policy)
    paths = _prepare_run_directory(run_dir)
    manifest = _build_manifest(
        world,
        descriptor,
        run_id=actual_run_id,
        artifact_set_id=artifact_set_id,
        reference_commitment=reference_commitment,
        action_budget=action_budget,
    )
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

    # Hashing happens only after the append-only writer is closed, so the events
    # digest covers the exact bytes a reader will find on disk.
    manifest_bytes = paths.manifest.read_bytes()
    events_bytes = paths.events.read_bytes()
    public = world.public_description()
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

    # The meters run last, over files that are already committed.  A failure
    # here leaves the raw record intact and recoverable with `metering report`.
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
    """Create one hidden-fault instance and run a cooperative policy against it."""

    world = HiddenFaultWorld(
        spec or HiddenFaultSpec.default(), hidden_fault_id, instance_id=instance_id
    )
    return run_experiment(
        world,
        policy,
        run_dir,
        run_id=run_id,
        action_budget=action_budget,
        sync_trace=sync_trace,
    )
