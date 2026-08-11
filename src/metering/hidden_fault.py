"""The deterministic eight-state hidden-fault world used by Metering v0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .events import (
    ACTION_TYPES,
    Action,
    Diagnose,
    DiagnosticObservation,
    Finish,
    FinishObservation,
    Observation,
    RawActionCost,
    Repair,
    RepairObservation,
    VerificationObservation,
    Verify,
)

WORLD_ID = "hidden-fault"
WORLD_VERSION = "1"
INSTANCE_VERSION = "1"
DEFAULT_INSTANCE_ID = "hidden-fault-public-v1"
PUBLIC_INSTANCE_SCHEMA_VERSION = 1
REFERENCE_SCHEMA_VERSION = 1


class HiddenFaultError(ValueError):
    """Base error for an invalid hidden-fault specification or operation."""


class InvalidActionError(HiddenFaultError):
    """Raised if ``apply`` is called with an action that validation rejects."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class DiagnosticTest:
    """A public deterministic yes/no test.

    ``positive_fault_ids`` is the public observation model: the test is positive
    exactly in those candidate states.  It reveals no selected hidden state.
    """

    test_id: str
    description: str
    positive_fault_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.test_id) is not str or not self.test_id:
            raise HiddenFaultError("test_id must be a non-empty string")
        if type(self.description) is not str or not self.description:
            raise HiddenFaultError("description must be a non-empty string")
        if type(self.positive_fault_ids) is not tuple:
            raise HiddenFaultError("positive_fault_ids must be a tuple")
        if not self.positive_fault_ids:
            raise HiddenFaultError("a diagnostic test must be positive somewhere")
        if len(set(self.positive_fault_ids)) != len(self.positive_fault_ids):
            raise HiddenFaultError("positive_fault_ids must be unique")
        if any(type(item) is not str or not item for item in self.positive_fault_ids):
            raise HiddenFaultError("positive_fault_ids must contain non-empty strings")

    def outcome(self, fault_id: str) -> bool:
        return fault_id in self.positive_fault_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "description": self.description,
            "positive_fault_ids": list(self.positive_fault_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiagnosticTest":
        if type(data) is not dict:
            raise HiddenFaultError("diagnostic test must be an object")
        expected = {"test_id", "description", "positive_fault_ids"}
        if set(data) != expected:
            raise HiddenFaultError("diagnostic test has missing or unexpected fields")
        positive = data["positive_fault_ids"]
        if type(positive) is not list:
            raise HiddenFaultError("positive_fault_ids must be a list")
        return cls(data["test_id"], data["description"], tuple(positive))


@dataclass(frozen=True, slots=True)
class PublicInstance:
    """Everything a cooperative v0 harness is allowed to receive."""

    world_id: str
    world_version: str
    instance_id: str
    instance_version: str
    fault_ids: tuple[str, ...]
    diagnostic_tests: tuple[DiagnosticTest, ...]
    schema_version: int = PUBLIC_INSTANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "world_id",
            "world_version",
            "instance_id",
            "instance_version",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value:
                raise HiddenFaultError(f"{field_name} must be a non-empty string")
        if type(self.schema_version) is not int or self.schema_version != PUBLIC_INSTANCE_SCHEMA_VERSION:
            raise HiddenFaultError(
                f"unsupported public instance schema: {self.schema_version!r}"
            )
        if not self.fault_ids or len(set(self.fault_ids)) != len(self.fault_ids):
            raise HiddenFaultError("fault_ids must be non-empty and unique")
        if any(type(item) is not str or not item for item in self.fault_ids):
            raise HiddenFaultError("fault_ids must contain non-empty strings")
        if not self.diagnostic_tests:
            raise HiddenFaultError("diagnostic_tests must not be empty")
        test_ids = [test.test_id for test in self.diagnostic_tests]
        if len(test_ids) != len(set(test_ids)):
            raise HiddenFaultError("diagnostic test identifiers must be unique")
        known = set(self.fault_ids)
        for test in self.diagnostic_tests:
            if type(test) is not DiagnosticTest:
                raise HiddenFaultError("diagnostic_tests must contain DiagnosticTest")
            positives = set(test.positive_fault_ids)
            if not positives <= known:
                raise HiddenFaultError(
                    f"test {test.test_id!r} refers to an unknown fault"
                )
            if positives == known:
                raise HiddenFaultError(
                    f"test {test.test_id!r} must distinguish at least one state"
                )

    def diagnostic_test(self, test_id: str) -> DiagnosticTest | None:
        for test in self.diagnostic_tests:
            if test.test_id == test_id:
                return test
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "world_id": self.world_id,
            "world_version": self.world_version,
            "instance_id": self.instance_id,
            "instance_version": self.instance_version,
            "fault_ids": list(self.fault_ids),
            "diagnostic_tests": [test.to_dict() for test in self.diagnostic_tests],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PublicInstance":
        if type(data) is not dict:
            raise HiddenFaultError("public instance must be an object")
        expected = {
            "schema_version",
            "world_id",
            "world_version",
            "instance_id",
            "instance_version",
            "fault_ids",
            "diagnostic_tests",
        }
        if set(data) != expected:
            raise HiddenFaultError("public instance has missing or unexpected fields")
        fault_ids = data["fault_ids"]
        tests = data["diagnostic_tests"]
        if type(fault_ids) is not list or type(tests) is not list:
            raise HiddenFaultError("fault_ids and diagnostic_tests must be lists")
        return cls(
            schema_version=data["schema_version"],
            world_id=data["world_id"],
            world_version=data["world_version"],
            instance_id=data["instance_id"],
            instance_version=data["instance_version"],
            fault_ids=tuple(fault_ids),
            diagnostic_tests=tuple(DiagnosticTest.from_dict(item) for item in tests),
        )


@dataclass(frozen=True, slots=True)
class HiddenFaultSpec:
    """A versioned definition from which hidden-fault instances are created."""

    world_id: str
    world_version: str
    instance_version: str
    fault_ids: tuple[str, ...]
    diagnostic_tests: tuple[DiagnosticTest, ...]

    def __post_init__(self) -> None:
        # Reuse all catalogue validation in the public boundary type.
        self.public_instance()

    @classmethod
    def v0(cls) -> "HiddenFaultSpec":
        """Return the canonical eight-fault v0 specification."""

        fault_ids = tuple(f"fault-{index}" for index in range(8))
        tests: list[DiagnosticTest] = []

        # These three catalogue entries form a balanced decision tree.  They
        # come first so the reference policy has a stable tie break.
        for bit in range(3):
            positives = tuple(
                fault_id
                for index, fault_id in enumerate(fault_ids)
                if (index >> bit) & 1
            )
            tests.append(
                DiagnosticTest(
                    test_id=f"split-{bit + 1}",
                    description=f"Balanced catalogue split {bit + 1}",
                    positive_fault_ids=positives,
                )
            )

        # Singleton tests support the deliberately wasteful sequential policy.
        for index, fault_id in enumerate(fault_ids):
            tests.append(
                DiagnosticTest(
                    test_id=f"check-{fault_id}",
                    description=f"Check candidate {index + 1}",
                    positive_fault_ids=(fault_id,),
                )
            )

        return cls(
            world_id=WORLD_ID,
            world_version=WORLD_VERSION,
            instance_version=INSTANCE_VERSION,
            fault_ids=fault_ids,
            diagnostic_tests=tuple(tests),
        )

    def public_instance(self, instance_id: str = DEFAULT_INSTANCE_ID) -> PublicInstance:
        return PublicInstance(
            world_id=self.world_id,
            world_version=self.world_version,
            instance_id=instance_id,
            instance_version=self.instance_version,
            fault_ids=self.fault_ids,
            diagnostic_tests=self.diagnostic_tests,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "world_version": self.world_version,
            "instance_version": self.instance_version,
            "fault_ids": list(self.fault_ids),
            "diagnostic_tests": [test.to_dict() for test in self.diagnostic_tests],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HiddenFaultSpec":
        if type(data) is not dict:
            raise HiddenFaultError("world specification must be an object")
        expected = {
            "world_id",
            "world_version",
            "instance_version",
            "fault_ids",
            "diagnostic_tests",
        }
        if set(data) != expected:
            raise HiddenFaultError("world specification has missing or unexpected fields")
        faults = data["fault_ids"]
        tests = data["diagnostic_tests"]
        if type(faults) is not list or type(tests) is not list:
            raise HiddenFaultError("fault_ids and diagnostic_tests must be lists")
        return cls(
            world_id=data["world_id"],
            world_version=data["world_version"],
            instance_version=data["instance_version"],
            fault_ids=tuple(faults),
            diagnostic_tests=tuple(DiagnosticTest.from_dict(item) for item in tests),
        )


@dataclass(frozen=True, slots=True)
class ActionValidation:
    """Structured result of world-side action validation."""

    valid: bool
    code: str
    message: str

    @classmethod
    def accept(cls) -> "ActionValidation":
        return cls(True, "ok", "action accepted")

    @classmethod
    def reject(cls, code: str, message: str) -> "ActionValidation":
        return cls(False, code, message)


class HiddenFaultWorld:
    """One mutable instance with private hidden state.

    The controller gives a harness only :meth:`public_description`; it never
    gives the world object itself.  v0 is an in-process cooperative boundary,
    not a hostile-code sandbox.
    """

    def __init__(
        self,
        spec: HiddenFaultSpec,
        hidden_fault_id: str,
        *,
        instance_id: str = DEFAULT_INSTANCE_ID,
    ) -> None:
        if type(spec) is not HiddenFaultSpec:
            raise HiddenFaultError("spec must be HiddenFaultSpec")
        if hidden_fault_id not in spec.fault_ids:
            raise HiddenFaultError(f"unknown hidden fault: {hidden_fault_id!r}")
        self._spec = spec
        self._hidden_fault_id = hidden_fault_id
        self._public = spec.public_instance(instance_id)
        self._selected_repair: str | None = None
        self._repair_count = 0
        self._verification_results: list[bool] = []
        self._finished = False
        self._actions_applied = 0

    @classmethod
    def from_spec(
        cls,
        spec: HiddenFaultSpec,
        hidden_fault_id: str,
        *,
        instance_id: str = DEFAULT_INSTANCE_ID,
    ) -> "HiddenFaultWorld":
        return cls(spec, hidden_fault_id, instance_id=instance_id)

    @property
    def spec(self) -> HiddenFaultSpec:
        return self._spec

    @property
    def public_instance(self) -> PublicInstance:
        return self._public

    def public_description(self) -> PublicInstance:
        """Return the immutable public boundary object."""

        return self._public

    def validate_action(self, action: object) -> ActionValidation:
        if not isinstance(action, ACTION_TYPES):
            return ActionValidation.reject(
                "invalid_action_type",
                "harness output must be a typed Metering action",
            )
        if self._finished:
            return ActionValidation.reject("world_finished", "the world is already finished")
        if isinstance(action, Diagnose):
            if self._public.diagnostic_test(action.test_id) is None:
                return ActionValidation.reject(
                    "unknown_test_id",
                    "diagnostic test is not in the public catalogue",
                )
        elif isinstance(action, Repair):
            if action.fault_id not in self._public.fault_ids:
                return ActionValidation.reject(
                    "unknown_fault_id", "repair is not in the public fault catalogue"
                )
        elif isinstance(action, Verify):
            if self._selected_repair is None:
                return ActionValidation.reject(
                    "verify_without_repair", "a repair must be selected before verification"
                )
        return ActionValidation.accept()

    def apply(self, action: Action) -> tuple[Observation, RawActionCost]:
        """Apply one validated action and return its observation and raw cost."""

        validation = self.validate_action(action)
        if not validation.valid:
            raise InvalidActionError(validation.code, validation.message)

        self._actions_applied += 1
        if isinstance(action, Diagnose):
            test = self._public.diagnostic_test(action.test_id)
            assert test is not None  # established by validation
            return (
                DiagnosticObservation(
                    test_id=action.test_id,
                    positive=test.outcome(self._hidden_fault_id),
                ),
                RawActionCost(diagnostic_observations=1, total_actions=1),
            )

        if isinstance(action, Repair):
            self._selected_repair = action.fault_id
            self._repair_count += 1
            return (
                RepairObservation(action.fault_id),
                RawActionCost(repair_actions=1, total_actions=1),
            )

        if isinstance(action, Verify):
            passed = self._selected_repair == self._hidden_fault_id
            self._verification_results.append(passed)
            return (
                VerificationObservation(),
                RawActionCost(verification_actions=1, total_actions=1),
            )

        if isinstance(action, Finish):
            self._finished = True
            return FinishObservation(), RawActionCost(total_actions=1)

        raise AssertionError("validated action was not handled")  # pragma: no cover

    def generated_instance_reference(self) -> dict[str, str]:
        """Return the complete controller-private generated-instance identity.

        The runner uses this before policy execution only to create a salted
        commitment.  The world object and this value are never passed to the
        cooperative harness.
        """

        return {
            "world_id": self._public.world_id,
            "world_version": self._public.world_version,
            "instance_id": self._public.instance_id,
            "instance_version": self._public.instance_version,
            "hidden_fault_id": self._hidden_fault_id,
        }

    def final_reference_state(self) -> dict[str, Any]:
        """Return controller-private truth for the offline verifier.

        This method is called only after controller execution.  Its result is
        written to ``reference.json`` and is never passed to the harness.
        """

        return {
            "schema_version": REFERENCE_SCHEMA_VERSION,
            "generated_instance": self.generated_instance_reference(),
            "final_world_state": {
                "selected_repair": self._selected_repair,
                "repair_count": self._repair_count,
                "verification_count": len(self._verification_results),
                "last_verification_passed": (
                    self._verification_results[-1]
                    if self._verification_results
                    else None
                ),
                "finish_applied": self._finished,
                "actions_applied": self._actions_applied,
            },
        }
