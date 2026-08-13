"""Typed commands, observations, and canonical trace events for Metering.

This module carries data only.  It deliberately does not interpret a run,
because interpretation belongs to :mod:`metering.report` and must be able to
change without changing any recorded trace.

The four actions and four observations below are the complete protocol
vocabulary.  A policy returns one action, the world returns one observation,
and the controller records both as one canonical event.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, ClassVar, Mapping, TypeAlias

from .schema import EVENT_SCHEMA_VERSION, SchemaError, StrictFields


class EventError(SchemaError):
    """Raised when an action, observation, or event cannot be decoded."""


_check = StrictFields(EventError)


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

    def __post_init__(self) -> None:
        _check.text(self.test_id, "test_id")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind, "test_id": self.test_id}


@dataclass(frozen=True, slots=True)
class Repair:
    """Select a public fault identifier as the proposed repair."""

    fault_id: str
    kind: ClassVar[str] = "repair"

    def __post_init__(self) -> None:
        _check.text(self.fault_id, "fault_id")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind, "fault_id": self.fault_id}


@dataclass(frozen=True, slots=True)
class Verify:
    """Verify the currently selected repair."""

    kind: ClassVar[str] = "verify"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind}


@dataclass(frozen=True, slots=True)
class Finish:
    """Ask the controller to terminate the run normally."""

    kind: ClassVar[str] = "finish"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind}


Action: TypeAlias = Diagnose | Repair | Verify | Finish
ACTION_TYPES: tuple[type, ...] = (Diagnose, Repair, Verify, Finish)


def action_to_dict(action: Action) -> dict[str, Any]:
    """Return the canonical JSON object for a typed action.

    A plain mapping is intentionally not accepted.  The in-process Metering
    boundary is typed, so malformed harness output must reach the controller as
    an explicit protocol failure rather than being silently repaired.
    """

    if not isinstance(action, ACTION_TYPES):
        raise EventError(f"unsupported action type: {type(action).__name__}")
    return action.to_dict()


def action_from_dict(data: Mapping[str, Any]) -> Action:
    """Decode a canonical action object, rejecting unknown or extra fields."""

    _check.mapping(data, "action")
    action_type = data.get("type")
    if action_type == Diagnose.kind:
        _check.exact_keys(data, {"type", "test_id"}, "diagnose action")
        return Diagnose(data["test_id"])
    if action_type == Repair.kind:
        _check.exact_keys(data, {"type", "fault_id"}, "repair action")
        return Repair(data["fault_id"])
    if action_type == Verify.kind:
        _check.exact_keys(data, {"type"}, "verify action")
        return Verify()
    if action_type == Finish.kind:
        _check.exact_keys(data, {"type"}, "finish action")
        return Finish()
    raise EventError(f"unknown action type: {action_type!r}")


@dataclass(frozen=True, slots=True)
class DiagnosticObservation:
    """The deterministic Boolean outcome of one public diagnostic test."""

    test_id: str
    positive: bool
    kind: ClassVar[str] = "diagnostic_result"

    def __post_init__(self) -> None:
        _check.text(self.test_id, "test_id")
        _check.boolean(self.positive, "positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.kind,
            "test_id": self.test_id,
            "positive": self.positive,
        }


@dataclass(frozen=True, slots=True)
class RepairObservation:
    """Acknowledgement that a repair selection was applied.

    The acknowledgement does not say whether the selection matches the hidden
    fault, because that fact stays with the controller until offline reporting.
    """

    fault_id: str
    kind: ClassVar[str] = "repair_applied"

    def __post_init__(self) -> None:
        _check.text(self.fault_id, "fault_id")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind, "fault_id": self.fault_id}


@dataclass(frozen=True, slots=True)
class VerificationObservation:
    """Content-free acknowledgement that verification was performed.

    Because the acknowledgement carries no result, a harness cannot use
    verification as a second diagnostic oracle that no meter would count.
    """

    kind: ClassVar[str] = "verification_acknowledged"

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
OBSERVATION_TYPES: tuple[type, ...] = (
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

    _check.mapping(data, "observation")
    observation_type = data.get("type")
    if observation_type == DiagnosticObservation.kind:
        _check.exact_keys(
            data, {"type", "test_id", "positive"}, "diagnostic observation"
        )
        return DiagnosticObservation(data["test_id"], data["positive"])
    if observation_type == RepairObservation.kind:
        _check.exact_keys(data, {"type", "fault_id"}, "repair observation")
        return RepairObservation(data["fault_id"])
    if observation_type == VerificationObservation.kind:
        _check.exact_keys(data, {"type"}, "verification observation")
        return VerificationObservation()
    if observation_type == FinishObservation.kind:
        _check.exact_keys(data, {"type"}, "finish observation")
        return FinishObservation()
    raise EventError(f"unknown observation type: {observation_type!r}")


_COST_FIELDS = (
    "diagnostic_observations",
    "repair_actions",
    "verification_actions",
    "total_actions",
)


@dataclass(frozen=True, slots=True)
class RawActionCost:
    """Uncombined resource counts produced by applying one action.

    The counts stay separate at every layer.  Metering never folds them into a
    single score, because a diagnostic observation and a repair are different
    kinds of expense and only the caller knows how to trade them off.
    """

    diagnostic_observations: int = 0
    repair_actions: int = 0
    verification_actions: int = 0
    total_actions: int = 0

    def __post_init__(self) -> None:
        for field_name in _COST_FIELDS:
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise EventError(f"{field_name} must be a non-negative integer")

    @classmethod
    def zero(cls) -> "RawActionCost":
        return cls()

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in _COST_FIELDS}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RawActionCost":
        _check.exact_keys(data, _COST_FIELDS, "resources")
        return cls(**{name: data[name] for name in _COST_FIELDS})

    def __add__(self, other: "RawActionCost") -> "RawActionCost":
        if type(other) is not RawActionCost:
            return NotImplemented
        return RawActionCost(
            **{
                name: getattr(self, name) + getattr(other, name)
                for name in _COST_FIELDS
            }
        )


_EVENT_FIELDS = (
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
            _check.text(getattr(self, field_name), field_name)
        _check.integer(self.step, "step")
        if (
            type(self.schema_version) is not int
            or self.schema_version != EVENT_SCHEMA_VERSION
        ):
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
        fields = _check.exact_keys(data, _EVENT_FIELDS, "event")
        return cls(
            **{
                name: fields[name]
                for name in _EVENT_FIELDS
                if name != "resources"
            },
            resources=RawActionCost.from_dict(fields["resources"]),
        )
