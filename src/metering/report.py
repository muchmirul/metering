"""Strict offline trace replay, verification, and v0 meter calculations."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .binding import (
    REFERENCE_COMMITMENT_ALGORITHM,
    BindingError,
    compute_reference_commitment,
)
from .events import (
    Diagnose,
    DiagnosticObservation,
    Event,
    EventError,
    Finish,
    FinishObservation,
    RawActionCost,
    Repair,
    RepairObservation,
    VerificationObservation,
    Verify,
    action_from_dict,
    observation_from_dict,
)
from .hidden_fault import (
    REFERENCE_SCHEMA_VERSION,
    HiddenFaultSpec,
    PublicInstance,
)
from .provenance import METER_VERSION, implementation_provenance
from .trace import (
    RunPaths,
    canonical_document_bytes,
    canonical_events_bytes,
    read_events,
    read_json_bytes,
    sha256_hex,
    write_json_atomic,
)

MANIFEST_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1

EVENT_RUN_STARTED = "run_started"
EVENT_INTERACTION = "interaction"
EVENT_PROTOCOL_ERROR = "protocol_error"
EVENT_TERMINATION = "termination"

TERMINATION_NORMAL = "normal_finish"
TERMINATION_INVALID_ACTION = "invalid_action"
TERMINATION_HARNESS_CRASH = "harness_crash"
TERMINATION_BUDGET_EXHAUSTED = "budget_exhausted"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ReportError(ValueError):
    """Raised when raw artifacts are inconsistent or a trace is corrupt."""


@dataclass(frozen=True, slots=True)
class ReplayedInteraction:
    event_step: int
    action: Diagnose | Repair | Verify | Finish
    observation: (
        DiagnosticObservation
        | RepairObservation
        | VerificationObservation
        | FinishObservation
    )


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


def _exact_keys(value: object, expected: set[str], name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ReportError(f"{name} must be an object")
    data = value
    keys = set(data)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ReportError(
            f"{name} has invalid schema; missing={missing!r}, extra={extra!r}"
        )
    return data


def _string(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise ReportError(f"{name} must be a non-empty string")
    return value


def _integer(
    value: object, name: str, *, minimum: int | None = 0
) -> int:
    if type(value) is not int:
        raise ReportError(f"{name} must be an exact integer")
    if minimum is not None and value < minimum:
        raise ReportError(f"{name} must be an exact integer >= {minimum}")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ReportError(f"{name} must be an exact bool")
    return value


def _sha256(value: object, name: str) -> str:
    digest = _string(value, name)
    if _SHA256_RE.fullmatch(digest) is None:
        raise ReportError(f"{name} must be a lowercase SHA-256 hex digest")
    return digest


def _uuid4(value: object, name: str) -> str:
    text = _string(value, name)
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError) as exc:
        raise ReportError(f"{name} must be a canonical UUID4 string") from exc
    if parsed.version != 4 or str(parsed) != text:
        raise ReportError(f"{name} must be a canonical UUID4 string")
    return text


def _finite_json(value: object, name: str) -> None:
    """Validate exact JSON data types and reject non-finite numbers."""

    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ReportError(f"{name} contains a non-finite number")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _finite_json(item, f"{name}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ReportError(f"{name} contains a non-string object key")
            _finite_json(item, f"{name}.{key}")
        return
    raise ReportError(f"{name} contains a non-JSON value of type {type(value).__name__}")


def _validate_seed_policy(value: object) -> None:
    if type(value) is not dict:
        raise ReportError("manifest.policy.seed_policy must be an object")
    kind = value.get("kind")
    if type(kind) is not str or not kind:
        raise ReportError("manifest.policy.seed_policy.kind must be a string")
    if kind == "none":
        _exact_keys(value, {"kind"}, "manifest.policy.seed_policy")
        _string(kind, "manifest.policy.seed_policy.kind")
        return
    if kind == "fixed":
        seed_policy = _exact_keys(
            value, {"kind", "seed"}, "manifest.policy.seed_policy"
        )
        _integer(
            seed_policy["seed"],
            "manifest.policy.seed_policy.seed",
            minimum=None,
        )
        return
    raise ReportError("manifest.policy.seed_policy.kind is not declared by v0")


def _validate_manifest(
    manifest: Mapping[str, Any],
) -> tuple[PublicInstance, int, str, str, str]:
    data = _exact_keys(
        manifest,
        {
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
        },
        "manifest",
    )
    schema = _integer(data["schema_version"], "manifest.schema_version")
    if schema != MANIFEST_SCHEMA_VERSION:
        raise ReportError("unsupported manifest schema version")
    artifact_set_id = _uuid4(data["artifact_set_id"], "manifest.artifact_set_id")
    commitment = _exact_keys(
        data["reference_commitment"],
        {"algorithm", "digest"},
        "manifest.reference_commitment",
    )
    if (
        _string(
            commitment["algorithm"],
            "manifest.reference_commitment.algorithm",
        )
        != REFERENCE_COMMITMENT_ALGORITHM
    ):
        raise ReportError("reference commitment algorithm must be sha256")
    reference_commitment = _sha256(
        commitment["digest"],
        "manifest.reference_commitment.digest",
    )
    run_id = _string(data["run_id"], "manifest.run_id")

    try:
        instance_data = _exact_keys(
            data["instance"],
            {
                "schema_version",
                "world_id",
                "world_version",
                "instance_id",
                "instance_version",
                "fault_ids",
                "diagnostic_tests",
            },
            "manifest.instance",
        )
        instance = PublicInstance.from_dict(instance_data)
        specification_data = _exact_keys(
            data["world_specification"],
            {
                "world_id",
                "world_version",
                "instance_version",
                "fault_ids",
                "diagnostic_tests",
            },
            "manifest.world_specification",
        )
        specification = HiddenFaultSpec.from_dict(specification_data)
    except ValueError as exc:
        raise ReportError(f"invalid manifest world definition: {exc}") from exc
    if specification.public_instance(instance.instance_id) != instance:
        raise ReportError("materialized instance contradicts its world specification")

    world = _exact_keys(
        data["world"], {"world_id", "world_version"}, "manifest.world"
    )
    if _string(world["world_id"], "manifest.world.world_id") != instance.world_id:
        raise ReportError("manifest world_id contradicts its instance")
    if (
        _string(world["world_version"], "manifest.world.world_version")
        != instance.world_version
    ):
        raise ReportError("manifest world_version contradicts its instance")

    controller = _exact_keys(
        data["controller"], {"action_budget"}, "manifest.controller"
    )
    budget = _integer(
        controller["action_budget"], "manifest.controller.action_budget", minimum=1
    )

    policy = _exact_keys(
        data["policy"],
        {"name", "version", "configuration", "seed_policy"},
        "manifest.policy",
    )
    _string(policy["name"], "manifest.policy.name")
    _string(policy["version"], "manifest.policy.version")
    if type(policy["configuration"]) is not dict:
        raise ReportError("manifest.policy.configuration must be an object")
    _finite_json(policy["configuration"], "manifest.policy.configuration")
    _validate_seed_policy(policy["seed_policy"])

    execution = _exact_keys(
        data["execution_boundary"],
        {"kind", "hostile_code_sandbox_enforced"},
        "manifest.execution_boundary",
    )
    if _string(execution["kind"], "manifest.execution_boundary.kind") != (
        "cooperative_in_process"
    ):
        raise ReportError("v0 execution boundary must be cooperative_in_process")
    if _boolean(
        execution["hostile_code_sandbox_enforced"],
        "manifest.execution_boundary.hostile_code_sandbox_enforced",
    ):
        raise ReportError("v0 must not claim hostile-code sandbox enforcement")

    reproducibility = _exact_keys(
        data["reproducibility"],
        {
            "generated_instance_materialized",
            "event_timestamps_in_deterministic_comparison",
            "artifact_binding",
        },
        "manifest.reproducibility",
    )
    if not _boolean(
        reproducibility["generated_instance_materialized"],
        "manifest.reproducibility.generated_instance_materialized",
    ):
        raise ReportError("manifest must declare that the instance was materialized")
    if _boolean(
        reproducibility["event_timestamps_in_deterministic_comparison"],
        "manifest.reproducibility.event_timestamps_in_deterministic_comparison",
    ):
        raise ReportError("v0 deterministic comparison must exclude event timestamps")
    if (
        _string(
            reproducibility["artifact_binding"],
            "manifest.reproducibility.artifact_binding",
        )
        != "sha256"
    ):
        raise ReportError("v0 artifact binding must be sha256")

    implementation = _exact_keys(
        data["implementation"],
        {
            "package",
            "package_version",
            "controller_version",
            "verifier_version",
            "meter_version",
        },
        "manifest.implementation",
    )
    for key in implementation:
        _string(implementation[key], f"manifest.implementation.{key}")
    if implementation != implementation_provenance():
        raise ReportError("manifest implementation provenance is incompatible")

    _finite_json(data, "manifest")
    return instance, budget, artifact_set_id, run_id, reference_commitment


def _validate_reference(
    reference: Mapping[str, Any],
    instance: PublicInstance,
    artifact_set_id: str,
    run_id: str,
    expected_reference_commitment: str,
) -> tuple[str, dict[str, Any], dict[str, str]]:
    data = _exact_keys(
        reference,
        {
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
        },
        "reference",
    )
    schema = _integer(data["schema_version"], "reference.schema_version")
    if schema != REFERENCE_SCHEMA_VERSION:
        raise ReportError("unsupported reference schema version")
    if _uuid4(data["artifact_set_id"], "reference.artifact_set_id") != artifact_set_id:
        raise ReportError("reference artifact_set_id does not match manifest")
    binding_nonce = _uuid4(data["binding_nonce"], "reference.binding_nonce")

    expected_identity = {
        "run_id": run_id,
        "world_id": instance.world_id,
        "world_version": instance.world_version,
        "instance_id": instance.instance_id,
        "instance_version": instance.instance_version,
    }
    for key, expected in expected_identity.items():
        if _string(data[key], f"reference.{key}") != expected:
            raise ReportError(f"reference {key} does not match manifest")

    generated = _exact_keys(
        data["generated_instance"],
        {
            "world_id",
            "world_version",
            "instance_id",
            "instance_version",
            "hidden_fault_id",
        },
        "reference.generated_instance",
    )
    for key in ("world_id", "world_version", "instance_id", "instance_version"):
        if _string(generated[key], f"reference.generated_instance.{key}") != (
            expected_identity[key]
        ):
            raise ReportError(f"generated instance {key} does not match manifest")
    hidden_fault_id = _string(
        generated["hidden_fault_id"],
        "reference.generated_instance.hidden_fault_id",
    )
    try:
        computed_commitment = compute_reference_commitment(
            artifact_set_id,
            binding_nonce,
            generated,
        )
    except BindingError as exc:
        raise ReportError(f"invalid reference commitment input: {exc}") from exc
    if computed_commitment != expected_reference_commitment:
        raise ReportError(
            "reference ground truth does not match the pre-run manifest commitment"
        )
    if hidden_fault_id not in instance.fault_ids:
        raise ReportError("reference contains an unknown hidden fault")

    final_state = _exact_keys(
        data["final_world_state"],
        {
            "selected_repair",
            "repair_count",
            "verification_count",
            "last_verification_passed",
            "finish_applied",
            "actions_applied",
        },
        "reference.final_world_state",
    )
    selected = final_state["selected_repair"]
    if selected is not None:
        selected = _string(selected, "reference.final_world_state.selected_repair")
        if selected not in instance.fault_ids:
            raise ReportError("reference final repair is outside the public catalogue")
    _integer(final_state["repair_count"], "reference.final_world_state.repair_count")
    _integer(
        final_state["verification_count"],
        "reference.final_world_state.verification_count",
    )
    last_passed = final_state["last_verification_passed"]
    if last_passed is not None:
        _boolean(
            last_passed,
            "reference.final_world_state.last_verification_passed",
        )
    _boolean(final_state["finish_applied"], "reference.final_world_state.finish_applied")
    _integer(final_state["actions_applied"], "reference.final_world_state.actions_applied")

    hashes = _exact_keys(
        data["artifact_hashes"],
        {"algorithm", "manifest_sha256", "events_sha256"},
        "reference.artifact_hashes",
    )
    if (
        _string(hashes["algorithm"], "reference.artifact_hashes.algorithm")
        != REFERENCE_COMMITMENT_ALGORITHM
    ):
        raise ReportError("reference artifact hash algorithm must be sha256")
    bound_hashes = {
        "manifest_sha256": _sha256(
            hashes["manifest_sha256"],
            "reference.artifact_hashes.manifest_sha256",
        ),
        "events_sha256": _sha256(
            hashes["events_sha256"],
            "reference.artifact_hashes.events_sha256",
        ),
    }
    _finite_json(data, "reference")
    return hidden_fault_id, final_state, bound_hashes


def _artifact_bytes(
    manifest: Mapping[str, Any],
    events: Sequence[Event],
    reference: Mapping[str, Any],
    supplied: Mapping[str, bytes] | None,
) -> dict[str, bytes]:
    if supplied is None:
        return {
            "manifest": canonical_document_bytes(dict(manifest)),
            "events": canonical_events_bytes(events),
            "reference": canonical_document_bytes(dict(reference)),
        }
    if type(supplied) is not dict or set(supplied) != {
        "manifest",
        "events",
        "reference",
    }:
        raise ReportError(
            "artifact_bytes must contain exactly manifest, events, and reference"
        )
    result: dict[str, bytes] = {}
    for key in ("manifest", "events", "reference"):
        value = supplied[key]
        if type(value) is not bytes:
            raise ReportError(f"artifact_bytes.{key} must be exact bytes")
        result[key] = value
    return result


def _zero_cost(cost: RawActionCost) -> bool:
    return cost == RawActionCost.zero()


def _expected_interaction(
    action: Diagnose | Repair | Verify | Finish,
    observation: object,
    instance: PublicInstance,
    hidden_fault_id: str,
    selected_repair: str | None,
) -> tuple[RawActionCost, str | None, bool | None, bool]:
    if isinstance(action, Diagnose):
        test = instance.diagnostic_test(action.test_id)
        if test is None:
            raise ReportError("trace applies a diagnostic outside the public catalogue")
        if type(observation) is not DiagnosticObservation:
            raise ReportError("diagnose action has the wrong observation type")
        if observation.test_id != action.test_id:
            raise ReportError("diagnostic observation names a different test")
        expected_outcome = test.outcome(hidden_fault_id)
        if type(observation.positive) is not bool or observation.positive is not expected_outcome:
            raise ReportError("diagnostic outcome contradicts the generated instance")
        return (
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
        return (
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
        # The acknowledgement carries no result.  Replay derives this private
        # fact from ground truth and the repair selected at this step.
        expected_passed = selected_repair == hidden_fault_id
        return (
            RawActionCost(verification_actions=1, total_actions=1),
            selected_repair,
            expected_passed,
            False,
        )

    if isinstance(action, Finish):
        if type(observation) is not FinishObservation:
            raise ReportError("finish action has the wrong observation type")
        return RawActionCost(total_actions=1), selected_repair, None, True

    raise ReportError("trace contains an unsupported action")


def _expected_protocol_error_code(
    attempted: Any,
    instance: PublicInstance,
    selected_repair: str | None,
) -> str:
    if attempted is None:
        return "invalid_action_type"
    if type(attempted) is not dict:
        raise ReportError("protocol_error.attempted_action must be null or an object")
    try:
        action = action_from_dict(attempted)
    except EventError as exc:
        raise ReportError(f"protocol error has a malformed action record: {exc}") from exc
    if isinstance(action, Diagnose) and instance.diagnostic_test(action.test_id) is None:
        return "unknown_test_id"
    if isinstance(action, Repair) and action.fault_id not in instance.fault_ids:
        return "unknown_fault_id"
    if isinstance(action, Verify) and selected_repair is None:
        return "verify_without_repair"
    raise ReportError("protocol_error records an action valid in replayed state")


def replay_trace(
    manifest: Mapping[str, Any],
    events: Sequence[Event],
    reference: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> ReplayState:
    """Strictly replay and bind artifacts without executing policy or world code."""

    (
        instance,
        budget,
        artifact_set_id,
        run_id,
        expected_reference_commitment,
    ) = _validate_manifest(manifest)
    hidden_fault_id, final_state, bound_hashes = _validate_reference(
        reference,
        instance,
        artifact_set_id,
        run_id,
        expected_reference_commitment,
    )
    raw = _artifact_bytes(manifest, events, reference, artifact_bytes)
    computed_hashes = {
        "manifest_sha256": sha256_hex(raw["manifest"]),
        "events_sha256": sha256_hex(raw["events"]),
        "reference_sha256": sha256_hex(raw["reference"]),
    }

    if type(events) not in {tuple, list} or not events:
        raise ReportError("trace must be a non-empty event sequence")
    expected_identity = {
        "run_id": run_id,
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
            actual = getattr(event, key)
            if type(actual) is not str or actual != expected:
                raise ReportError(f"event {event.step} {key} does not match manifest")

    first = events[0]
    if first.event_type != EVENT_RUN_STARTED:
        raise ReportError("trace must begin with run_started at step zero")
    if not _zero_cost(first.resources):
        raise ReportError("run_started cannot consume resources")
    start = _exact_keys(
        first.payload,
        {"action_budget", "artifact_set_id", "public_instance"},
        "run_started.payload",
    )
    if _integer(start["action_budget"], "run_started.action_budget", minimum=1) != budget:
        raise ReportError("run_started budget does not match manifest")
    if _uuid4(start["artifact_set_id"], "run_started.artifact_set_id") != artifact_set_id:
        raise ReportError("run_started artifact_set_id does not match manifest")
    try:
        start_instance = PublicInstance.from_dict(
            _exact_keys(
                start["public_instance"],
                {
                    "schema_version",
                    "world_id",
                    "world_version",
                    "instance_id",
                    "instance_version",
                    "fault_ids",
                    "diagnostic_tests",
                },
                "run_started.public_instance",
            )
        )
    except ValueError as exc:
        raise ReportError(f"invalid run_started public instance: {exc}") from exc
    if start_instance != instance:
        raise ReportError("run_started public instance does not match manifest")

    interactions: list[ReplayedInteraction] = []
    actions_used = 0
    selected_repair: str | None = None
    final_repair_step: int | None = None
    verification_steps: list[int] = []
    last_verification_passed: bool | None = None
    finish_applied = False
    protocol_error_step: int | None = None
    termination_reason: str | None = None
    termination_step: int | None = None

    for event_index, event in enumerate(events[1:], start=1):
        if termination_reason is not None:
            raise ReportError("trace contains an event after termination")
        if finish_applied and event.event_type != EVENT_TERMINATION:
            raise ReportError("finish must be followed immediately by termination")
        if protocol_error_step is not None and event.event_type != EVENT_TERMINATION:
            raise ReportError("protocol error must be followed immediately by termination")

        if event.event_type == EVENT_INTERACTION:
            if actions_used >= budget:
                raise ReportError("controller requested an action beyond the budget")
            payload = _exact_keys(
                event.payload, {"action", "observation"}, "interaction.payload"
            )
            try:
                action_data = _exact_keys(
                    payload["action"], set(payload["action"]), "interaction.action"
                )
                observation_data = _exact_keys(
                    payload["observation"],
                    set(payload["observation"]),
                    "interaction.observation",
                )
                action = action_from_dict(action_data)
                observation = observation_from_dict(observation_data)
            except (EventError, ReportError, TypeError) as exc:
                raise ReportError(f"invalid interaction at step {event.step}: {exc}") from exc

            expected_cost, new_repair, verification_passed, did_finish = (
                _expected_interaction(
                    action,
                    observation,
                    instance,
                    hidden_fault_id,
                    selected_repair,
                )
            )
            if event.resources != expected_cost:
                raise ReportError(f"incorrect raw resource counts at step {event.step}")
            actions_used += 1
            selected_repair = new_repair
            if isinstance(action, Repair):
                final_repair_step = event.step
            if isinstance(action, Verify):
                verification_steps.append(event.step)
                last_verification_passed = verification_passed
            if did_finish:
                finish_applied = True
            interactions.append(ReplayedInteraction(event.step, action, observation))
            continue

        if event.event_type == EVENT_PROTOCOL_ERROR:
            if actions_used >= budget:
                raise ReportError("controller requested malformed output beyond the budget")
            payload = _exact_keys(
                event.payload,
                {"code", "message", "received_type", "attempted_action"},
                "protocol_error.payload",
            )
            code = _string(payload["code"], "protocol_error.code")
            _string(payload["message"], "protocol_error.message")
            _string(payload["received_type"], "protocol_error.received_type")
            expected_code = _expected_protocol_error_code(
                payload["attempted_action"], instance, selected_repair
            )
            if code != expected_code:
                raise ReportError("protocol_error code contradicts replayed state")
            if event.resources != RawActionCost(total_actions=1):
                raise ReportError("a rejected action must consume one total action")
            actions_used += 1
            protocol_error_step = event.step
            continue

        if event.event_type == EVENT_TERMINATION:
            if not _zero_cost(event.resources):
                raise ReportError("termination event cannot consume resources")
            payload = _exact_keys(
                event.payload,
                {"reason", "normal", "actions_used", "action_budget"},
                "termination.payload",
            )
            reason = _string(payload["reason"], "termination.reason")
            if reason not in {
                TERMINATION_NORMAL,
                TERMINATION_INVALID_ACTION,
                TERMINATION_HARNESS_CRASH,
                TERMINATION_BUDGET_EXHAUSTED,
            }:
                raise ReportError(f"unknown termination reason: {reason!r}")
            normal = _boolean(payload["normal"], "termination.normal")
            if normal is not (reason == TERMINATION_NORMAL):
                raise ReportError("termination normal flag contradicts its reason")
            if _integer(payload["actions_used"], "termination.actions_used") != actions_used:
                raise ReportError("termination actions_used contradicts trace")
            if (
                _integer(payload["action_budget"], "termination.action_budget", minimum=1)
                != budget
            ):
                raise ReportError("termination action_budget contradicts manifest")

            if reason == TERMINATION_NORMAL:
                if not finish_applied:
                    raise ReportError("normal termination requires an applied finish action")
            elif reason == TERMINATION_INVALID_ACTION:
                if protocol_error_step is None:
                    raise ReportError("invalid_action termination needs protocol_error")
            elif reason == TERMINATION_BUDGET_EXHAUSTED:
                if actions_used != budget or finish_applied:
                    raise ReportError(
                        "budget exhaustion requires exactly the budget and no finish"
                    )
            elif reason == TERMINATION_HARNESS_CRASH:
                if finish_applied or protocol_error_step is not None:
                    raise ReportError("harness crash has contradictory prior terminal state")
                if actions_used >= budget:
                    raise ReportError("budget exhaustion takes precedence at boundary")

            termination_reason = reason
            termination_step = event.step
            if event_index != len(events) - 1:
                raise ReportError("termination must be the final trace event")
            continue

        raise ReportError(f"unknown event type at step {event.step}: {event.event_type!r}")

    if termination_reason is None or termination_step is None:
        raise ReportError("trace has no termination event")

    repair_count = sum(type(item.action) is Repair for item in interactions)
    expected_final = {
        "selected_repair": selected_repair,
        "repair_count": repair_count,
        "verification_count": len(verification_steps),
        "last_verification_passed": last_verification_passed,
        "finish_applied": finish_applied,
        "actions_applied": len(interactions),
    }
    for key, expected in expected_final.items():
        actual = final_state[key]
        # Schema types were checked above; identity comparison for bool/None
        # prevents True from being accepted as integer 1.
        if type(actual) is not type(expected) or actual != expected:
            raise ReportError(
                f"controller-private final state field {key} contradicts replay"
            )

    # Semantic replay runs before encoding and binding comparisons so a
    # contradictory observation is reported as trace corruption rather than
    # merely a hash mismatch.  Completed v0 raw artifacts have one canonical
    # byte representation.
    canonical_inputs = {
        "manifest": canonical_document_bytes(dict(manifest)),
        "events": canonical_events_bytes(events),
        "reference": canonical_document_bytes(dict(reference)),
    }
    for artifact_name in ("manifest", "events", "reference"):
        if raw[artifact_name] != canonical_inputs[artifact_name]:
            raise ReportError(f"{artifact_name} artifact is not canonical JSON bytes")

    if computed_hashes["manifest_sha256"] != bound_hashes["manifest_sha256"]:
        raise ReportError("manifest SHA-256 does not match reference artifact binding")
    if computed_hashes["events_sha256"] != bound_hashes["events_sha256"]:
        raise ReportError("events trace SHA-256 does not match reference artifact binding")

    return ReplayState(
        public_instance=instance,
        hidden_fault_id=hidden_fault_id,
        artifact_set_id=artifact_set_id,
        artifact_hashes=computed_hashes,
        action_budget=budget,
        interactions=tuple(interactions),
        termination_reason=termination_reason,
        termination_step=termination_step,
        actions_used=actions_used,
        final_repair=selected_repair,
        final_repair_step=final_repair_step,
        verification_steps=tuple(verification_steps),
        last_verification_passed=last_verification_passed,
        finish_applied=finish_applied,
        protocol_error_step=protocol_error_step,
    )


def _correctness_report(state: ReplayState) -> dict[str, Any]:
    repair_matches = state.final_repair == state.hidden_fault_id
    verified_after_final_repair = (
        state.final_repair_step is not None
        and any(step > state.final_repair_step for step in state.verification_steps)
    )
    terminated_normally = state.termination_reason == TERMINATION_NORMAL
    budget_respected = state.actions_used <= state.action_budget
    conditions = {
        "selected_repair_matches_hidden_fault": repair_matches,
        "verification_occurred_after_final_repair": verified_after_final_repair,
        "harness_terminated_normally": terminated_normally,
        "action_budget_was_respected": budget_respected,
    }
    return {**conditions, "overall_task_success": all(conditions.values())}


def _resource_report(state: ReplayState, events: Sequence[Event]) -> dict[str, Any]:
    total = RawActionCost.zero()
    for event in events:
        total = total + event.resources
    if total.total_actions != state.actions_used:
        raise ReportError("summed total action cost contradicts replay state")
    return {
        **total.to_dict(),
        "action_budget": state.action_budget,
        "budget_exhaustion": state.termination_reason == TERMINATION_BUDGET_EXHAUSTED,
    }


def _entropy(candidate_count: int) -> float:
    if type(candidate_count) is not int or candidate_count < 1:
        raise ReportError("an impossible diagnostic result eliminated every state")
    return math.log2(candidate_count)


def _information_report(state: ReplayState) -> dict[str, Any]:
    candidates = list(state.public_instance.fault_ids)
    initial_uncertainty = _entropy(len(candidates))
    progression: list[dict[str, Any]] = []

    for item in state.interactions:
        if not isinstance(item.action, Diagnose):
            continue
        if type(item.observation) is not DiagnosticObservation:
            raise ReportError("replay lost the typed diagnostic observation")
        test = state.public_instance.diagnostic_test(item.action.test_id)
        if test is None:
            raise ReportError("diagnostic test is absent from public model")
        before_count = len(candidates)
        before_uncertainty = _entropy(before_count)
        candidates = [
            fault_id
            for fault_id in candidates
            if test.outcome(fault_id) is item.observation.positive
        ]
        if not candidates:
            raise ReportError("diagnostic result is impossible under trace history")
        after_count = len(candidates)
        after_uncertainty = _entropy(after_count)
        progression.append(
            {
                "diagnostic_index": len(progression) + 1,
                "event_step": item.event_step,
                "test_id": item.action.test_id,
                "positive": item.observation.positive,
                "candidate_count_before": before_count,
                "candidate_count_after": after_count,
                "uncertainty_before_bits": before_uncertainty,
                "uncertainty_after_bits": after_uncertainty,
                "uncertainty_removed_bits": before_uncertainty - after_uncertainty,
            }
        )

    remaining_uncertainty = _entropy(len(candidates))
    removed = initial_uncertainty - remaining_uncertainty
    count = len(progression)
    return {
        "name": "diagnostic_information_exposure",
        "unit": "bits",
        "prior": "uniform_over_declared_hidden_states",
        "initial_uncertainty_bits": initial_uncertainty,
        "remaining_uncertainty_bits": remaining_uncertainty,
        "total_uncertainty_removed_bits": removed,
        "diagnostic_observations": count,
        "uncertainty_removed_per_diagnostic_observation_bits": (
            removed / count if count else None
        ),
        "progression": progression,
    }


def build_report(
    manifest: Mapping[str, Any],
    events: Sequence[Event],
    reference: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """Build a canonical report as a pure calculation over bound artifacts."""

    state = replay_trace(
        manifest,
        events,
        reference,
        artifact_bytes=artifact_bytes,
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "meter_version": METER_VERSION,
        "artifact_set_id": state.artifact_set_id,
        "artifact_hashes": {
            "algorithm": "sha256",
            **dict(state.artifact_hashes),
        },
        "run_id": manifest["run_id"],
        "world_id": state.public_instance.world_id,
        "world_version": state.public_instance.world_version,
        "instance_id": state.public_instance.instance_id,
        "instance_version": state.public_instance.instance_version,
        "termination_reason": state.termination_reason,
        "correctness": _correctness_report(state),
        "resources": _resource_report(state, events),
        "diagnostic_information": _information_report(state),
        "scope": {
            "conditional_on": [
                "declared_hidden_fault_world",
                "uniform_prior",
                "deterministic_public_observation_model",
                "declared_policy_configuration",
                "declared_action_budget",
            ],
            "does_not_claim": [
                "that_a_model_understood_the_observations",
                "universal_harness_quality",
                "hostile_code_sandbox_enforcement",
                "survival_of_nonreturning_or_hard_exit_callbacks",
                "an_overall_agent_score",
            ],
        },
    }


def aggregate_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate raw units; information efficiency is a ratio of sums."""

    diagnostic_total = 0
    repair_total = 0
    verification_total = 0
    action_total = 0
    information_total = 0.0
    successful_runs = 0
    budget_exhausted_runs = 0
    for index, report in enumerate(reports):
        if type(report) is not dict:
            raise ReportError(f"report {index} must be an object")
        resources = _exact_keys(
            report.get("resources"),
            {
                "diagnostic_observations",
                "repair_actions",
                "verification_actions",
                "total_actions",
                "action_budget",
                "budget_exhaustion",
            },
            f"report {index}.resources",
        )
        information = report.get("diagnostic_information")
        if type(information) is not dict:
            raise ReportError(f"report {index}.diagnostic_information must be object")
        correctness = report.get("correctness")
        if type(correctness) is not dict:
            raise ReportError(f"report {index}.correctness must be object")
        diagnostic_total += _integer(
            resources["diagnostic_observations"],
            f"report {index} diagnostic_observations",
        )
        repair_total += _integer(
            resources["repair_actions"], f"report {index} repair_actions"
        )
        verification_total += _integer(
            resources["verification_actions"],
            f"report {index} verification_actions",
        )
        action_total += _integer(
            resources["total_actions"], f"report {index} total_actions"
        )
        removed = information.get("total_uncertainty_removed_bits")
        if type(removed) not in {int, float}:
            raise ReportError(f"report {index} information removed must be numeric")
        removed_float = float(removed)
        if not math.isfinite(removed_float) or removed_float < 0:
            raise ReportError(f"report {index} information removed is invalid")
        information_total += removed_float
        if correctness.get("overall_task_success") is True:
            successful_runs += 1
        exhausted = _boolean(
            resources["budget_exhaustion"], f"report {index} budget_exhaustion"
        )
        budget_exhausted_runs += int(exhausted)

    return {
        "run_count": len(reports),
        "successful_runs": successful_runs,
        "resources": {
            "diagnostic_observations": diagnostic_total,
            "repair_actions": repair_total,
            "verification_actions": verification_total,
            "total_actions": action_total,
            "budget_exhausted_runs": budget_exhausted_runs,
        },
        "diagnostic_information": {
            "total_uncertainty_removed_bits": information_total,
            "bits_per_diagnostic_observation": (
                information_total / diagnostic_total if diagnostic_total else None
            ),
            "aggregation": "ratio_of_sums",
        },
    }


def regenerate_report(run_dir: str | Path) -> dict[str, Any]:
    """Rebuild report.json from strict, bound raw artifact bytes."""

    paths = RunPaths.at(run_dir)
    manifest, manifest_bytes = read_json_bytes(paths.manifest)
    reference, reference_bytes = read_json_bytes(paths.reference)
    try:
        events_bytes = paths.events.read_bytes()
    except OSError as exc:
        raise ReportError(f"cannot read events artifact: {exc}") from exc
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
    return report
