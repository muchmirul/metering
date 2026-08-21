"""Strict offline replay of a saved Metering run.

Replay reads the three raw artifacts of a finished run and rebuilds the
controller state that produced them.  It never calls the policy and never calls
the world, so it can check a trace that some other machine recorded and it
cannot be influenced by whatever the policy would do today.

The checks run in a deliberate order.  Schemas and identity come first, then
the private commitment, then every transition and its recorded cost, and only
then the exact artifact bytes.  Ordering it this way means a contradictory
observation is reported as trace corruption rather than as an unexplained hash
mismatch.  Any failure raises :class:`~metering.schema.ReportError` before a
report is written, so a corrupt run never replaces a good report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .binding import (
    GENERATED_INSTANCE_FIELDS,
    REFERENCE_COMMITMENT_ALGORITHM,
    BindingError,
    compute_reference_commitment,
)
from .events import (
    Action,
    Diagnose,
    DiagnosticObservation,
    Event,
    EventError,
    Finish,
    FinishObservation,
    Observation,
    RawActionCost,
    Repair,
    RepairObservation,
    VerificationObservation,
    Verify,
    action_from_dict,
    observation_from_dict,
)
from .hidden_fault import HiddenFaultSpec, PublicInstance, validate_action_in_state
from .provenance import implementation_provenance
from .schema import (
    EVENT_INTERACTION,
    EVENT_PROTOCOL_ERROR,
    EVENT_RUN_STARTED,
    EVENT_TERMINATION,
    MANIFEST_SCHEMA_VERSION,
    REFERENCE_SCHEMA_VERSION,
    TERMINATION_BUDGET_EXHAUSTED,
    TERMINATION_HARNESS_CRASH,
    TERMINATION_INVALID_ACTION,
    TERMINATION_NORMAL,
    TERMINATION_REASONS,
    ReportError,
    StrictFields,
)
from .trace import canonical_document_bytes, canonical_events_bytes, sha256_hex

_check = StrictFields(ReportError)

_MANIFEST_FIELDS = (
    "schema_version",
    "artifact_set_id",
    "reference_commitment",
    "run_id",
    "world",
    "instance",
    "world_specification",
    "controller",
    "policy",
    "execution_boundary",
    "reproducibility",
    "implementation",
)
_REFERENCE_FIELDS = (
    "schema_version",
    "artifact_set_id",
    "binding_nonce",
    "run_id",
    "world_id",
    "world_version",
    "instance_id",
    "instance_version",
    "generated_instance",
    "final_world_state",
    "artifact_hashes",
)
_FINAL_STATE_FIELDS = (
    "selected_repair",
    "repair_count",
    "verification_count",
    "last_verification_passed",
    "finish_applied",
    "actions_applied",
)
_POLICY_FIELDS = ("name", "version", "configuration", "seed_policy")
_IMPLEMENTATION_FIELDS = (
    "package",
    "package_version",
    "controller_version",
    "verifier_version",
    "meter_version",
)
_ARTIFACT_NAMES = ("manifest", "events", "reference")


@dataclass(frozen=True, slots=True)
class ReplayedInteraction:
    """One action and its observation, recovered from the trace."""

    event_step: int
    action: Action
    observation: Observation


@dataclass(frozen=True, slots=True)
class ManifestFacts:
    """The parts of a validated manifest that later checks depend on."""

    instance: PublicInstance
    action_budget: int
    artifact_set_id: str
    run_id: str
    reference_commitment: str


@dataclass(frozen=True, slots=True)
class ReferenceFacts:
    """The parts of a validated reference that later checks depend on."""

    hidden_fault_id: str
    final_state: Mapping[str, Any]
    bound_hashes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ReplayState:
    """Controller state reconstructed without executing a policy or RNG."""

    public_instance: PublicInstance
    hidden_fault_id: str
    artifact_set_id: str
    artifact_hashes: Mapping[str, str]
    action_budget: int
    interactions: tuple[ReplayedInteraction, ...]
    termination_reason: str
    termination_step: int
    actions_used: int
    final_repair: str | None
    final_repair_step: int | None
    verification_steps: tuple[int, ...]
    last_verification_passed: bool | None
    finish_applied: bool
    protocol_error_step: int | None


def _validate_policy_declaration(policy: Mapping[str, Any]) -> None:
    """Require an exact policy descriptor with a declared seed policy.

    Provenance has to be declared rather than inferred.  A run whose policy did
    not say whether it used a seed is not reproducible, so replay rejects it
    instead of guessing.
    """

    fields = _check.exact_keys(policy, _POLICY_FIELDS, "manifest.policy")
    _check.text(fields["name"], "manifest.policy.name")
    _check.text(fields["version"], "manifest.policy.version")
    _check.mapping(fields["configuration"], "manifest.policy.configuration")
    _check.finite_json(fields["configuration"], "manifest.policy.configuration")

    seed_policy = _check.mapping(fields["seed_policy"], "manifest.policy.seed_policy")
    kind = seed_policy.get("kind")
    if kind == "none":
        _check.exact_keys(seed_policy, {"kind"}, "manifest.policy.seed_policy")
        return
    if kind == "fixed":
        _check.exact_keys(seed_policy, {"kind", "seed"}, "manifest.policy.seed_policy")
        _check.integer(
            seed_policy["seed"], "manifest.policy.seed_policy.seed", minimum=None
        )
        return
    raise ReportError("manifest.policy.seed_policy.kind is not declared by Metering")


def _validate_declared_limits(data: Mapping[str, Any]) -> None:
    """Reject a manifest that claims a guarantee Metering does not provide."""

    execution = _check.exact_keys(
        data["execution_boundary"],
        {"kind", "hostile_code_sandbox_enforced"},
        "manifest.execution_boundary",
    )
    if _check.text(execution["kind"], "manifest.execution_boundary.kind") != (
        "cooperative_in_process"
    ):
        raise ReportError("Metering execution boundary must be cooperative_in_process")
    if _check.boolean(
        execution["hostile_code_sandbox_enforced"],
        "manifest.execution_boundary.hostile_code_sandbox_enforced",
    ):
        raise ReportError("Metering must not claim hostile-code sandbox enforcement")

    reproducibility = _check.exact_keys(
        data["reproducibility"],
        {
            "generated_instance_materialized",
            "event_timestamps_in_deterministic_comparison",
            "artifact_binding",
        },
        "manifest.reproducibility",
    )
    if not _check.boolean(
        reproducibility["generated_instance_materialized"],
        "manifest.reproducibility.generated_instance_materialized",
    ):
        raise ReportError("manifest must declare that the instance was materialized")
    if _check.boolean(
        reproducibility["event_timestamps_in_deterministic_comparison"],
        "manifest.reproducibility.event_timestamps_in_deterministic_comparison",
    ):
        raise ReportError(
            "Metering deterministic comparison must exclude event timestamps"
        )
    if (
        _check.text(
            reproducibility["artifact_binding"],
            "manifest.reproducibility.artifact_binding",
        )
        != "sha256"
    ):
        raise ReportError("Metering artifact binding must be sha256")


def _validate_implementation(data: Mapping[str, Any]) -> None:
    """Require component versions this installation can still interpret.

    The release version is recorded as provenance only.  Compatibility is
    decided by the controller, verifier, and meter versions, because those are
    the parts whose behavior a replay depends on.
    """

    implementation = _check.exact_keys(
        data["implementation"], _IMPLEMENTATION_FIELDS, "manifest.implementation"
    )
    for key in _IMPLEMENTATION_FIELDS:
        _check.text(implementation[key], f"manifest.implementation.{key}")
    current = implementation_provenance()
    for key in ("package", "controller_version", "verifier_version", "meter_version"):
        if implementation[key] != current[key]:
            raise ReportError("manifest implementation provenance is incompatible")


def _validate_manifest(manifest: Mapping[str, Any]) -> ManifestFacts:
    data = _check.exact_keys(manifest, _MANIFEST_FIELDS, "manifest")
    if _check.integer(data["schema_version"], "manifest.schema_version") != (
        MANIFEST_SCHEMA_VERSION
    ):
        raise ReportError("unsupported manifest schema version")

    artifact_set_id = _check.uuid4(data["artifact_set_id"], "manifest.artifact_set_id")
    commitment = _check.exact_keys(
        data["reference_commitment"],
        {"algorithm", "digest"},
        "manifest.reference_commitment",
    )
    if (
        _check.text(commitment["algorithm"], "manifest.reference_commitment.algorithm")
        != REFERENCE_COMMITMENT_ALGORITHM
    ):
        raise ReportError("reference commitment algorithm must be sha256")
    reference_commitment = _check.sha256_digest(
        commitment["digest"], "manifest.reference_commitment.digest"
    )
    run_id = _check.text(data["run_id"], "manifest.run_id")

    # Both decoders enforce their own exact key sets, so replay decodes instead
    # of repeating those field lists and risking a stale second copy.
    try:
        instance = PublicInstance.from_dict(data["instance"])
        specification = HiddenFaultSpec.from_dict(data["world_specification"])
    except ValueError as exc:
        raise ReportError(f"invalid manifest world definition: {exc}") from exc
    if specification.public_instance(instance.instance_id) != instance:
        raise ReportError("materialized instance contradicts its world specification")

    world = _check.exact_keys(
        data["world"], {"world_id", "world_version"}, "manifest.world"
    )
    if _check.text(world["world_id"], "manifest.world.world_id") != instance.world_id:
        raise ReportError("manifest world_id contradicts its instance")
    if (
        _check.text(world["world_version"], "manifest.world.world_version")
        != instance.world_version
    ):
        raise ReportError("manifest world_version contradicts its instance")

    controller = _check.exact_keys(
        data["controller"], {"action_budget"}, "manifest.controller"
    )
    budget = _check.integer(
        controller["action_budget"], "manifest.controller.action_budget", minimum=1
    )

    _validate_policy_declaration(data["policy"])
    _validate_declared_limits(data)
    _validate_implementation(data)
    _check.finite_json(data, "manifest")
    return ManifestFacts(
        instance=instance,
        action_budget=budget,
        artifact_set_id=artifact_set_id,
        run_id=run_id,
        reference_commitment=reference_commitment,
    )


def _validate_reference(
    reference: Mapping[str, Any], facts: ManifestFacts
) -> ReferenceFacts:
    """Check the private artifact against the manifest and its commitment.

    The manifest published a salted hash of the generated truth before the
    policy ran.  Recomputing that hash from the revealed reference is what
    prevents a plausible hidden fault from being substituted afterwards, while
    the salt keeps the eight-state truth unguessable from the public manifest.
    """

    instance = facts.instance
    data = _check.exact_keys(reference, _REFERENCE_FIELDS, "reference")
    if _check.integer(data["schema_version"], "reference.schema_version") != (
        REFERENCE_SCHEMA_VERSION
    ):
        raise ReportError("unsupported reference schema version")
    if _check.uuid4(data["artifact_set_id"], "reference.artifact_set_id") != (
        facts.artifact_set_id
    ):
        raise ReportError("reference artifact_set_id does not match manifest")
    binding_nonce = _check.uuid4(data["binding_nonce"], "reference.binding_nonce")

    expected_identity = {
        "run_id": facts.run_id,
        "world_id": instance.world_id,
        "world_version": instance.world_version,
        "instance_id": instance.instance_id,
        "instance_version": instance.instance_version,
    }
    for key, expected in expected_identity.items():
        if _check.text(data[key], f"reference.{key}") != expected:
            raise ReportError(f"reference {key} does not match manifest")

    generated = _check.exact_keys(
        data["generated_instance"],
        GENERATED_INSTANCE_FIELDS,
        "reference.generated_instance",
    )
    for key in ("world_id", "world_version", "instance_id", "instance_version"):
        if _check.text(generated[key], f"reference.generated_instance.{key}") != (
            expected_identity[key]
        ):
            raise ReportError(f"generated instance {key} does not match manifest")
    hidden_fault_id = _check.text(
        generated["hidden_fault_id"], "reference.generated_instance.hidden_fault_id"
    )
    try:
        computed = compute_reference_commitment(
            facts.artifact_set_id, binding_nonce, generated
        )
    except BindingError as exc:
        raise ReportError(f"invalid reference commitment input: {exc}") from exc
    if computed != facts.reference_commitment:
        raise ReportError(
            "reference ground truth does not match the pre-run manifest commitment"
        )
    if hidden_fault_id not in instance.fault_ids:
        raise ReportError("reference contains an unknown hidden fault")

    final_state = _check.exact_keys(
        data["final_world_state"], _FINAL_STATE_FIELDS, "reference.final_world_state"
    )
    selected = final_state["selected_repair"]
    if selected is not None:
        selected = _check.text(selected, "reference.final_world_state.selected_repair")
        if selected not in instance.fault_ids:
            raise ReportError("reference final repair is outside the public catalogue")
    _check.integer(
        final_state["repair_count"], "reference.final_world_state.repair_count"
    )
    _check.integer(
        final_state["verification_count"],
        "reference.final_world_state.verification_count",
    )
    if final_state["last_verification_passed"] is not None:
        _check.boolean(
            final_state["last_verification_passed"],
            "reference.final_world_state.last_verification_passed",
        )
    _check.boolean(
        final_state["finish_applied"], "reference.final_world_state.finish_applied"
    )
    _check.integer(
        final_state["actions_applied"], "reference.final_world_state.actions_applied"
    )

    hashes = _check.exact_keys(
        data["artifact_hashes"],
        {"algorithm", "manifest_sha256", "events_sha256"},
        "reference.artifact_hashes",
    )
    if (
        _check.text(hashes["algorithm"], "reference.artifact_hashes.algorithm")
        != REFERENCE_COMMITMENT_ALGORITHM
    ):
        raise ReportError("reference artifact hash algorithm must be sha256")
    bound_hashes = {
        name: _check.sha256_digest(hashes[name], f"reference.artifact_hashes.{name}")
        for name in ("manifest_sha256", "events_sha256")
    }
    _check.finite_json(data, "reference")
    return ReferenceFacts(hidden_fault_id, final_state, bound_hashes)


def _canonical_bytes(
    manifest: Mapping[str, Any],
    events: Sequence[Event],
    reference: Mapping[str, Any],
) -> dict[str, bytes]:
    return {
        "manifest": canonical_document_bytes(dict(manifest)),
        "events": canonical_events_bytes(events),
        "reference": canonical_document_bytes(dict(reference)),
    }


def _supplied_bytes(supplied: Mapping[str, bytes]) -> dict[str, bytes]:
    if type(supplied) is not dict or set(supplied) != set(_ARTIFACT_NAMES):
        raise ReportError(
            "artifact_bytes must contain exactly manifest, events, and reference"
        )
    for name in _ARTIFACT_NAMES:
        if type(supplied[name]) is not bytes:
            raise ReportError(f"artifact_bytes.{name} must be exact bytes")
    return dict(supplied)


@dataclass(frozen=True, slots=True)
class _AppliedAction:
    """What one interaction should have cost and changed."""

    cost: RawActionCost
    selected_repair: str | None
    verification_passed: bool | None
    finished: bool


def _expected_interaction(
    action: Action,
    observation: object,
    instance: PublicInstance,
    hidden_fault_id: str,
    selected_repair: str | None,
) -> _AppliedAction:
    """Recompute the observation and cost the world must have produced."""

    if isinstance(action, Diagnose):
        test = instance.diagnostic_test(action.test_id)
        if test is None:
            raise ReportError("trace applies a diagnostic outside the public catalogue")
        if type(observation) is not DiagnosticObservation:
            raise ReportError("diagnose action has the wrong observation type")
        if observation.test_id != action.test_id:
            raise ReportError("diagnostic observation names a different test")
        if observation.positive is not test.outcome(hidden_fault_id):
            raise ReportError("diagnostic outcome contradicts the generated instance")
        return _AppliedAction(
            RawActionCost(diagnostic_observations=1, total_actions=1),
            selected_repair,
            None,
            False,
        )

    if isinstance(action, Repair):
        if action.fault_id not in instance.fault_ids:
            raise ReportError("trace applies a repair outside the public catalogue")
        if type(observation) is not RepairObservation:
            raise ReportError("repair action has the wrong observation type")
        if observation.fault_id != action.fault_id:
            raise ReportError("repair observation names a different repair")
        return _AppliedAction(
            RawActionCost(repair_actions=1, total_actions=1),
            action.fault_id,
            None,
            False,
        )

    if isinstance(action, Verify):
        if selected_repair is None:
            raise ReportError("trace verifies before selecting a repair")
        if type(observation) is not VerificationObservation:
            raise ReportError("verify action has the wrong observation type")
        # The acknowledgement carries no result, so replay derives the private
        # outcome from ground truth and the repair selected at this step.
        return _AppliedAction(
            RawActionCost(verification_actions=1, total_actions=1),
            selected_repair,
            selected_repair == hidden_fault_id,
            False,
        )

    if isinstance(action, Finish):
        if type(observation) is not FinishObservation:
            raise ReportError("finish action has the wrong observation type")
        return _AppliedAction(
            RawActionCost(total_actions=1), selected_repair, None, True
        )

    raise ReportError("trace contains an unsupported action")


def _expected_protocol_error_code(
    attempted: Any, instance: PublicInstance, selected_repair: str | None
) -> str:
    """Recompute why the controller must have rejected the recorded attempt.

    The rules come from :func:`validate_action_in_state`, the same function the
    live world uses, so replay cannot drift away from what the controller
    actually enforced.
    """

    if attempted is None:
        return "invalid_action_type"
    _check.mapping(attempted, "protocol_error.attempted_action")
    try:
        action = action_from_dict(attempted)
    except EventError as exc:
        raise ReportError(
            f"protocol error has a malformed action record: {exc}"
        ) from exc
    # A protocol error never follows a finish, because the walk requires a
    # finish to be followed immediately by termination.
    validation = validate_action_in_state(
        instance, action, finished=False, selected_repair=selected_repair
    )
    if validation.valid:
        raise ReportError("protocol_error records an action valid in replayed state")
    return validation.code


def _validate_event_envelopes(
    events: Sequence[Event], facts: ManifestFacts
) -> None:
    """Check that every event is a real Event with the run's identity."""

    if type(events) not in {tuple, list} or not events:
        raise ReportError("trace must be a non-empty event sequence")
    instance = facts.instance
    expected_identity = {
        "run_id": facts.run_id,
        "world_id": instance.world_id,
        "world_version": instance.world_version,
        "instance_id": instance.instance_id,
        "instance_version": instance.instance_version,
    }
    for expected_step, event in enumerate(events):
        if type(event) is not Event:
            raise ReportError(f"trace item {expected_step} is not an exact Event")
        if type(event.step) is not int or event.step != expected_step:
            raise ReportError(
                f"event step {event.step!r} is not monotonic step {expected_step}"
            )
        for key, expected in expected_identity.items():
            if getattr(event, key) != expected:
                raise ReportError(f"event {event.step} {key} does not match manifest")


def _validate_run_started(first: Event, facts: ManifestFacts) -> None:
    if first.event_type != EVENT_RUN_STARTED:
        raise ReportError("trace must begin with run_started at step zero")
    if first.resources != RawActionCost.zero():
        raise ReportError("run_started cannot consume resources")
    start = _check.exact_keys(
        first.payload,
        {"action_budget", "artifact_set_id", "public_instance"},
        "run_started.payload",
    )
    if _check.integer(
        start["action_budget"], "run_started.action_budget", minimum=1
    ) != facts.action_budget:
        raise ReportError("run_started budget does not match manifest")
    if _check.uuid4(start["artifact_set_id"], "run_started.artifact_set_id") != (
        facts.artifact_set_id
    ):
        raise ReportError("run_started artifact_set_id does not match manifest")
    try:
        start_instance = PublicInstance.from_dict(start["public_instance"])
    except ValueError as exc:
        raise ReportError(f"invalid run_started public instance: {exc}") from exc
    if start_instance != facts.instance:
        raise ReportError("run_started public instance does not match manifest")


class _TraceWalk:
    """Accumulates replayed controller state one event at a time."""

    def __init__(self, facts: ManifestFacts, hidden_fault_id: str) -> None:
        self.facts = facts
        self.hidden_fault_id = hidden_fault_id
        self.interactions: list[ReplayedInteraction] = []
        self.actions_used = 0
        self.selected_repair: str | None = None
        self.final_repair_step: int | None = None
        self.verification_steps: list[int] = []
        self.last_verification_passed: bool | None = None
        self.finish_applied = False
        self.protocol_error_step: int | None = None
        self.termination_reason: str | None = None
        self.termination_step: int | None = None

    def interaction(self, event: Event) -> None:
        if self.actions_used >= self.facts.action_budget:
            raise ReportError("controller requested an action beyond the budget")
        payload = _check.exact_keys(
            event.payload, {"action", "observation"}, "interaction.payload"
        )
        try:
            action = action_from_dict(
                _check.mapping(payload["action"], "interaction.action")
            )
            observation = observation_from_dict(
                _check.mapping(payload["observation"], "interaction.observation")
            )
        except (EventError, ReportError, TypeError) as exc:
            raise ReportError(
                f"invalid interaction at step {event.step}: {exc}"
            ) from exc

        applied = _expected_interaction(
            action,
            observation,
            self.facts.instance,
            self.hidden_fault_id,
            self.selected_repair,
        )
        if event.resources != applied.cost:
            raise ReportError(f"incorrect raw resource counts at step {event.step}")
        self.actions_used += 1
        self.selected_repair = applied.selected_repair
        if isinstance(action, Repair):
            self.final_repair_step = event.step
        if isinstance(action, Verify):
            self.verification_steps.append(event.step)
            self.last_verification_passed = applied.verification_passed
        if applied.finished:
            self.finish_applied = True
        self.interactions.append(
            ReplayedInteraction(event.step, action, observation)
        )

    def protocol_error(self, event: Event) -> None:
        if self.actions_used >= self.facts.action_budget:
            raise ReportError("controller requested malformed output beyond the budget")
        payload = _check.exact_keys(
            event.payload,
            {"code", "message", "received_type", "attempted_action"},
            "protocol_error.payload",
        )
        code = _check.text(payload["code"], "protocol_error.code")
        _check.text(payload["message"], "protocol_error.message")
        _check.text(payload["received_type"], "protocol_error.received_type")
        expected_code = _expected_protocol_error_code(
            payload["attempted_action"], self.facts.instance, self.selected_repair
        )
        if code != expected_code:
            raise ReportError("protocol_error code contradicts replayed state")
        if event.resources != RawActionCost(total_actions=1):
            raise ReportError("a rejected action must consume one total action")
        self.actions_used += 1
        self.protocol_error_step = event.step

    def termination(self, event: Event) -> None:
        if event.resources != RawActionCost.zero():
            raise ReportError("termination event cannot consume resources")
        payload = _check.exact_keys(
            event.payload,
            {"reason", "normal", "actions_used", "action_budget"},
            "termination.payload",
        )
        reason = _check.text(payload["reason"], "termination.reason")
        if reason not in TERMINATION_REASONS:
            raise ReportError(f"unknown termination reason: {reason!r}")
        if _check.boolean(payload["normal"], "termination.normal") is not (
            reason == TERMINATION_NORMAL
        ):
            raise ReportError("termination normal flag contradicts its reason")
        if _check.integer(payload["actions_used"], "termination.actions_used") != (
            self.actions_used
        ):
            raise ReportError("termination actions_used contradicts trace")
        if _check.integer(
            payload["action_budget"], "termination.action_budget", minimum=1
        ) != self.facts.action_budget:
            raise ReportError("termination action_budget contradicts manifest")
        self._check_reason_preconditions(reason)
        self.termination_reason = reason
        self.termination_step = event.step

    def _check_reason_preconditions(self, reason: str) -> None:
        if reason == TERMINATION_NORMAL:
            if not self.finish_applied:
                raise ReportError(
                    "normal termination requires an applied finish action"
                )
        elif reason == TERMINATION_INVALID_ACTION:
            if self.protocol_error_step is None:
                raise ReportError("invalid_action termination needs protocol_error")
        elif reason == TERMINATION_BUDGET_EXHAUSTED:
            if self.actions_used != self.facts.action_budget or self.finish_applied:
                raise ReportError(
                    "budget exhaustion requires exactly the budget and no finish"
                )
        elif reason == TERMINATION_HARNESS_CRASH:
            if self.finish_applied or self.protocol_error_step is not None:
                raise ReportError(
                    "harness crash has contradictory prior terminal state"
                )
            if self.actions_used >= self.facts.action_budget:
                raise ReportError("budget exhaustion takes precedence at boundary")

    def final_world_state(self) -> dict[str, Any]:
        """Return the private final state that the world must have reached."""

        return {
            "selected_repair": self.selected_repair,
            "repair_count": sum(
                type(item.action) is Repair for item in self.interactions
            ),
            "verification_count": len(self.verification_steps),
            "last_verification_passed": self.last_verification_passed,
            "finish_applied": self.finish_applied,
            "actions_applied": len(self.interactions),
        }


def _walk_trace(
    events: Sequence[Event], facts: ManifestFacts, hidden_fault_id: str
) -> _TraceWalk:
    walk = _TraceWalk(facts, hidden_fault_id)
    last_index = len(events) - 1
    for index, event in enumerate(events[1:], start=1):
        if walk.termination_reason is not None:
            raise ReportError("trace contains an event after termination")
        if walk.finish_applied and event.event_type != EVENT_TERMINATION:
            raise ReportError("finish must be followed immediately by termination")
        if walk.protocol_error_step is not None and event.event_type != (
            EVENT_TERMINATION
        ):
            raise ReportError(
                "protocol error must be followed immediately by termination"
            )

        if event.event_type == EVENT_INTERACTION:
            walk.interaction(event)
        elif event.event_type == EVENT_PROTOCOL_ERROR:
            walk.protocol_error(event)
        elif event.event_type == EVENT_TERMINATION:
            walk.termination(event)
            if index != last_index:
                raise ReportError("termination must be the final trace event")
        else:
            raise ReportError(
                f"unknown event type at step {event.step}: {event.event_type!r}"
            )

    if walk.termination_reason is None or walk.termination_step is None:
        raise ReportError("trace has no termination event")
    return walk


def _compare_final_state(
    walk: _TraceWalk, recorded: Mapping[str, Any]
) -> None:
    for key, expected in walk.final_world_state().items():
        actual = recorded[key]
        # Schema types were checked earlier.  Comparing types as well as values
        # keeps True from being accepted where the integer 1 is expected.
        if type(actual) is not type(expected) or actual != expected:
            raise ReportError(
                f"controller-private final state field {key} contradicts replay"
            )


def replay_trace(
    manifest: Mapping[str, Any],
    events: Sequence[Event],
    reference: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> ReplayState:
    """Strictly replay and bind artifacts without executing policy or world code.

    Pass ``artifact_bytes`` when the exact bytes on disk are available, because
    that is what binds the report to the files a reader can inspect.  Without
    them, replay re-encodes the decoded values canonically, which still checks
    every semantic rule but proves nothing about the original file.
    """

    facts = _validate_manifest(manifest)
    reference_facts = _validate_reference(reference, facts)
    supplied = None if artifact_bytes is None else _supplied_bytes(artifact_bytes)

    _validate_event_envelopes(events, facts)
    _validate_run_started(events[0], facts)
    walk = _walk_trace(events, facts, reference_facts.hidden_fault_id)
    _compare_final_state(walk, reference_facts.final_state)

    # Byte comparisons come last so that a contradictory observation is reported
    # as trace corruption rather than as an unexplained hash mismatch.
    canonical = _canonical_bytes(manifest, events, reference)
    raw = canonical if supplied is None else supplied
    for name in _ARTIFACT_NAMES:
        if raw[name] != canonical[name]:
            raise ReportError(f"{name} artifact is not canonical JSON bytes")
    computed_hashes = {
        f"{name}_sha256": sha256_hex(raw[name]) for name in _ARTIFACT_NAMES
    }
    for name in ("manifest_sha256", "events_sha256"):
        if computed_hashes[name] != reference_facts.bound_hashes[name]:
            raise ReportError(
                f"{name} does not match the reference artifact binding"
            )

    assert walk.termination_reason is not None  # established by _walk_trace
    assert walk.termination_step is not None
    return ReplayState(
        public_instance=facts.instance,
        hidden_fault_id=reference_facts.hidden_fault_id,
        artifact_set_id=facts.artifact_set_id,
        artifact_hashes=computed_hashes,
        action_budget=facts.action_budget,
        interactions=tuple(walk.interactions),
        termination_reason=walk.termination_reason,
        termination_step=walk.termination_step,
        actions_used=walk.actions_used,
        final_repair=walk.selected_repair,
        final_repair_step=walk.final_repair_step,
        verification_steps=tuple(walk.verification_steps),
        last_verification_passed=walk.last_verification_passed,
        finish_applied=walk.finish_applied,
        protocol_error_step=walk.protocol_error_step,
    )
