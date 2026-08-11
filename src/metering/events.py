"""Typed commands, observations, and canonical trace events for Metering v0.

The event module contains data only.  It deliberately does not interpret a run;
that work belongs to :mod:`metering.report`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, ClassVar, Mapping, TypeAlias

EVENT_SCHEMA_VERSION = 1


class EventError(ValueError):
    """Raised when an action, observation, or event cannot be decoded."""


def _strict_keys(data: Mapping[str, Any], required: set[str]) -> None:
    keys = set(data)
    missing = required - keys
    extra = keys - required
    if missing or extra:
        parts: list[str] = []
        if missing:
            parts.append(f"missing keys: {sorted(missing)!r}")
        if extra:
            parts.append(f"unexpected keys: {sorted(extra)!r}")
        raise EventError("; ".join(parts))


def _nonempty_string(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        raise EventError(f"{field} must be a non-empty string")
    return value


def _json_mapping(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EventError(f"{field} must be a mapping")
    try:
        # This both makes a defensive deep copy and rejects non-JSON facts.
        encoded = json.dumps(dict(value), allow_nan=False, sort_keys=True)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise EventError(f"{field} must contain only finite JSON values") from exc
    if type(decoded) is not dict:  # pragma: no cover - guarded by Mapping
        raise EventError(f"{field} must be a JSON object")
    return decoded


@dataclass(frozen=True, slots=True)
class Diagnose:
    """Request one test from the public diagnostic catalogue."""

    test_id: str
    kind: ClassVar[str] = "diagnose"
    type: str = field(default="diagnose", init=False)

    def __post_init__(self) -> None:
        _nonempty_string(self.test_id, "test_id")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind, "test_id": self.test_id}


@dataclass(frozen=True, slots=True)
class Repair:
    """Select a public fault identifier as the proposed repair."""

    fault_id: str
    kind: ClassVar[str] = "repair"
    type: str = field(default="repair", init=False)

    def __post_init__(self) -> None:
        _nonempty_string(self.fault_id, "fault_id")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind, "fault_id": self.fault_id}


@dataclass(frozen=True, slots=True)
class Verify:
    """Verify the currently selected repair."""

    kind: ClassVar[str] = "verify"
    type: str = field(default="verify", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind}


@dataclass(frozen=True, slots=True)
class Finish:
    """Ask the controller to terminate the run normally."""

    kind: ClassVar[str] = "finish"
    type: str = field(default="finish", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind}


Action: TypeAlias = Diagnose | Repair | Verify | Finish
ACTION_TYPES = (Diagnose, Repair, Verify, Finish)


def action_to_dict(action: Action) -> dict[str, Any]:
    """Return the canonical JSON object for a typed action.

    A plain mapping is intentionally not accepted.  The in-process v0 boundary
    is typed, and malformed harness output must reach the controller as an
    explicit protocol failure rather than being silently repaired.
    """

    if not isinstance(action, ACTION_TYPES):
        raise EventError(f"unsupported action type: {type(action).__name__}")
    return action.to_dict()


def action_from_dict(data: Mapping[str, Any]) -> Action:
    """Decode a canonical action object, rejecting unknown or extra fields."""

    if type(data) is not dict:
        raise EventError("action must be an object")
    action_type = data.get("type")
    if action_type == Diagnose.kind:
        _strict_keys(data, {"type", "test_id"})
        return Diagnose(_nonempty_string(data["test_id"], "test_id"))
    if action_type == Repair.kind:
        _strict_keys(data, {"type", "fault_id"})
        return Repair(_nonempty_string(data["fault_id"], "fault_id"))
    if action_type == Verify.kind:
        _strict_keys(data, {"type"})
        return Verify()
    if action_type == Finish.kind:
        _strict_keys(data, {"type"})
        return Finish()
    raise EventError(f"unknown action type: {action_type!r}")


@dataclass(frozen=True, slots=True)
class DiagnosticObservation:
    """The deterministic Boolean outcome of one public diagnostic test."""

    test_id: str
    positive: bool
    kind: ClassVar[str] = "diagnostic_result"

    def __post_init__(self) -> None:
        _nonempty_string(self.test_id, "test_id")
        if type(self.positive) is not bool:
            raise EventError("positive must be a bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.kind,
            "test_id": self.test_id,
            "positive": self.positive,
        }


@dataclass(frozen=True, slots=True)
class RepairObservation:
    """Acknowledgement that a repair selection was applied.

    It does not say whether the selection matches the hidden fault.
    """

    fault_id: str
    kind: ClassVar[str] = "repair_applied"

    def __post_init__(self) -> None:
        _nonempty_string(self.fault_id, "fault_id")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind, "fault_id": self.fault_id}


@dataclass(frozen=True, slots=True)
class VerificationObservation:
    """Content-free acknowledgement that verification was performed.

    Whether the repair passed remains controller-private.  A harness may not
    use verification as a hidden-state oracle in v0.
    """

    kind: ClassVar[str] = "verification_acknowledged"
    type: str = field(default="verification_acknowledged", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind}


@dataclass(frozen=True, slots=True)
class FinishObservation:
    """Acknowledgement of a valid finish action."""

    kind: ClassVar[str] = "finish_accepted"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind}


Observation: TypeAlias = (
    DiagnosticObservation
    | RepairObservation
    | VerificationObservation
    | FinishObservation
)
OBSERVATION_TYPES = (
    DiagnosticObservation,
    RepairObservation,
    VerificationObservation,
    FinishObservation,
)


def observation_to_dict(observation: Observation) -> dict[str, Any]:
    if not isinstance(observation, OBSERVATION_TYPES):
        raise EventError(
            f"unsupported observation type: {type(observation).__name__}"
        )
    return observation.to_dict()


def observation_from_dict(data: Mapping[str, Any]) -> Observation:
    """Decode one canonical observation object."""

    if type(data) is not dict:
        raise EventError("observation must be an object")
    observation_type = data.get("type")
    if observation_type == DiagnosticObservation.kind:
        _strict_keys(data, {"type", "test_id", "positive"})
        positive = data["positive"]
        if type(positive) is not bool:
            raise EventError("positive must be a bool")
        return DiagnosticObservation(
            _nonempty_string(data["test_id"], "test_id"), positive
        )
    if observation_type == RepairObservation.kind:
        _strict_keys(data, {"type", "fault_id"})
        return RepairObservation(_nonempty_string(data["fault_id"], "fault_id"))
    if observation_type == VerificationObservation.kind:
        _strict_keys(data, {"type"})
        return VerificationObservation()
    if observation_type == FinishObservation.kind:
        _strict_keys(data, {"type"})
        return FinishObservation()
    raise EventError(f"unknown observation type: {observation_type!r}")


@dataclass(frozen=True, slots=True)
class RawActionCost:
    """Uncombined resource counts produced by applying one action."""

    diagnostic_observations: int = 0
    repair_actions: int = 0
    verification_actions: int = 0
    total_actions: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "diagnostic_observations",
            "repair_actions",
            "verification_actions",
            "total_actions",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise EventError(f"{field_name} must be a non-negative integer")

    @classmethod
    def zero(cls) -> "RawActionCost":
        return cls()

    def to_dict(self) -> dict[str, int]:
        return {
            "diagnostic_observations": self.diagnostic_observations,
            "repair_actions": self.repair_actions,
            "verification_actions": self.verification_actions,
            "total_actions": self.total_actions,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RawActionCost":
        if type(data) is not dict:
            raise EventError("resources must be an object")
        required = {
            "diagnostic_observations",
            "repair_actions",
            "verification_actions",
            "total_actions",
        }
        _strict_keys(data, required)
        return cls(**{key: data[key] for key in required})

    def __add__(self, other: "RawActionCost") -> "RawActionCost":
        if type(other) is not RawActionCost:
            return NotImplemented
        return RawActionCost(
            diagnostic_observations=(
                self.diagnostic_observations + other.diagnostic_observations
            ),
            repair_actions=self.repair_actions + other.repair_actions,
            verification_actions=(
                self.verification_actions + other.verification_actions
            ),
            total_actions=self.total_actions + other.total_actions,
        )


@dataclass(frozen=True, slots=True)
class Event:
    """One canonical, interpretation-free fact in an append-only trace."""

    run_id: str
    world_id: str
    world_version: str
    instance_id: str
    instance_version: str
    step: int
    event_type: str
    payload: Mapping[str, Any]
    resources: RawActionCost = RawActionCost()
    schema_version: int = EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "world_id",
            "world_version",
            "instance_id",
            "instance_version",
            "event_type",
        ):
            _nonempty_string(getattr(self, field_name), field_name)
        if type(self.step) is not int or self.step < 0:
            raise EventError("step must be a non-negative integer")
        if type(self.schema_version) is not int or self.schema_version != EVENT_SCHEMA_VERSION:
            raise EventError(
                f"unsupported event schema version: {self.schema_version!r}"
            )
        if type(self.resources) is not RawActionCost:
            raise EventError("resources must be RawActionCost")
        object.__setattr__(self, "payload", _json_mapping(self.payload, "payload"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "world_id": self.world_id,
            "world_version": self.world_version,
            "instance_id": self.instance_id,
            "instance_version": self.instance_version,
            "step": self.step,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "resources": self.resources.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Event":
        if type(data) is not dict:
            raise EventError("event must be an object")
        required = {
            "schema_version",
            "run_id",
            "world_id",
            "world_version",
            "instance_id",
            "instance_version",
            "step",
            "event_type",
            "payload",
            "resources",
        }
        _strict_keys(data, required)
        return cls(
            schema_version=data["schema_version"],
            run_id=data["run_id"],
            world_id=data["world_id"],
            world_version=data["world_version"],
            instance_id=data["instance_id"],
            instance_version=data["instance_version"],
            step=data["step"],
            event_type=data["event_type"],
            payload=data["payload"],
            resources=RawActionCost.from_dict(data["resources"]),
        )
