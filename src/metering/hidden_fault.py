"""The deterministic eight-state hidden-fault world used by Metering.

The world owns one selected fault and answers questions about it.  A policy
never sees the world object.  It receives :class:`PublicInstance`, which
describes the fault identifiers and the diagnostic catalogue without naming the
selected fault, so the only way to narrow the candidates is to spend actions on
diagnostics that the controller records.
"""

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
from .schema import (
    PUBLIC_INSTANCE_SCHEMA_VERSION,
    REFERENCE_SCHEMA_VERSION,
    SchemaError,
    StrictFields,
)

WORLD_ID = "hidden-fault"
WORLD_VERSION = "1"
INSTANCE_VERSION = "1"
DEFAULT_INSTANCE_ID = "hidden-fault-public-v1"

# Eight faults need three yes/no answers to separate, so the catalogue carries
# three balanced split tests alongside one singleton test per fault.
FAULT_COUNT = 8
SPLIT_TEST_COUNT = 3


class HiddenFaultError(SchemaError):
    """Base error for an invalid hidden-fault specification or operation."""


class InvalidActionError(HiddenFaultError):
    """Raised if ``apply`` is called with an action that validation rejects."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


_check = StrictFields(HiddenFaultError)

_TEST_FIELDS = ("test_id", "description", "positive_fault_ids")
_INSTANCE_FIELDS = (
    "schema_version",
    "world_id",
    "world_version",
    "instance_id",
    "instance_version",
    "fault_ids",
    "diagnostic_tests",
)
_SPEC_FIELDS = (
    "world_id",
    "world_version",
    "instance_version",
    "fault_ids",
    "diagnostic_tests",
)


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise HiddenFaultError(f"{name} must be a list")
    for item in value:
        _check.text(item, f"{name} entry")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class DiagnosticTest:
    """A public deterministic yes/no test.

    ``positive_fault_ids`` is the public observation model, which means the
    test is positive in exactly those candidate states.  Publishing the model
    reveals nothing about which state was selected, and it is what lets an
    offline meter recompute the same candidate set the policy could have
    computed.
    """

    test_id: str
    description: str
    positive_fault_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _check.text(self.test_id, "test_id")
        _check.text(self.description, "description")
        if type(self.positive_fault_ids) is not tuple:
            raise HiddenFaultError("positive_fault_ids must be a tuple")
        if not self.positive_fault_ids:
            raise HiddenFaultError("a diagnostic test must be positive somewhere")
        if len(set(self.positive_fault_ids)) != len(self.positive_fault_ids):
            raise HiddenFaultError("positive_fault_ids must be unique")
        for item in self.positive_fault_ids:
            _check.text(item, "positive_fault_ids entry")

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
        fields = _check.exact_keys(data, _TEST_FIELDS, "diagnostic test")
        return cls(
            fields["test_id"],
            fields["description"],
            _string_tuple(fields["positive_fault_ids"], "positive_fault_ids"),
        )


@dataclass(frozen=True, slots=True)
class PublicInstance:
    """Everything a cooperative Metering harness is allowed to receive."""

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
            _check.text(getattr(self, field_name), field_name)
        if (
            type(self.schema_version) is not int
            or self.schema_version != PUBLIC_INSTANCE_SCHEMA_VERSION
        ):
            raise HiddenFaultError(
                f"unsupported public instance schema: {self.schema_version!r}"
            )
        if not self.fault_ids or len(set(self.fault_ids)) != len(self.fault_ids):
            raise HiddenFaultError("fault_ids must be non-empty and unique")
        for item in self.fault_ids:
            _check.text(item, "fault_ids entry")
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
                # A test that is positive everywhere would cost one action and
                # remove zero bits, so the catalogue refuses to contain one.
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
        fields = _check.exact_keys(data, _INSTANCE_FIELDS, "public instance")
        return cls(
            schema_version=fields["schema_version"],
            world_id=fields["world_id"],
            world_version=fields["world_version"],
            instance_id=fields["instance_id"],
            instance_version=fields["instance_version"],
            fault_ids=_string_tuple(fields["fault_ids"], "fault_ids"),
            diagnostic_tests=_tests_from_list(fields["diagnostic_tests"]),
        )


def _tests_from_list(value: object) -> tuple[DiagnosticTest, ...]:
    if type(value) is not list:
        raise HiddenFaultError("diagnostic_tests must be a list")
    return tuple(DiagnosticTest.from_dict(item) for item in value)


@dataclass(frozen=True, slots=True)
class HiddenFaultSpec:
    """A versioned definition from which hidden-fault instances are created."""

    world_id: str
    world_version: str
    instance_version: str
    fault_ids: tuple[str, ...]
    diagnostic_tests: tuple[DiagnosticTest, ...]

    def __post_init__(self) -> None:
        # Materializing the public instance reuses all catalogue validation
        # instead of repeating it here.
        self.public_instance()

    @classmethod
    def default(cls) -> "HiddenFaultSpec":
        """Return the canonical eight-fault specification.

        The catalogue holds two families of tests.  The three split tests each
        answer one bit of the fault index, so three of them identify any of the
        eight states.  The eight singleton tests each name one state, which is
        a correct but wasteful way to search.  Having both families in one
        public catalogue is what lets calibration show a careful policy and a
        wasteful policy solving the same task at different cost.
        """

        fault_ids = tuple(f"fault-{index}" for index in range(FAULT_COUNT))
        tests: list[DiagnosticTest] = []

        # The balanced splits come first so that a policy breaking ties by
        # catalogue order gets a stable and sensible default.
        for bit in range(SPLIT_TEST_COUNT):
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
        fields = _check.exact_keys(data, _SPEC_FIELDS, "world specification")
        return cls(
            world_id=fields["world_id"],
            world_version=fields["world_version"],
            instance_version=fields["instance_version"],
            fault_ids=_string_tuple(fields["fault_ids"], "fault_ids"),
            diagnostic_tests=_tests_from_list(fields["diagnostic_tests"]),
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


def validate_action_in_state(
    instance: PublicInstance,
    action: object,
    *,
    finished: bool,
    selected_repair: str | None,
) -> ActionValidation:
    """Decide whether one action is legal, from public state alone.

    The rule set lives here, outside the world object, because two callers need
    it and they must never disagree.  A live run asks through
    :meth:`HiddenFaultWorld.validate_action`, and offline replay asks directly
    to recompute why the controller rejected a recorded attempt.  Nothing in
    these rules depends on the selected fault, so replay can apply them without
    a world and without the truth.
    """

    if not isinstance(action, ACTION_TYPES):
        return ActionValidation.reject(
            "invalid_action_type",
            "harness output must be a typed Metering action",
        )
    if finished:
        return ActionValidation.reject(
            "world_finished", "the world is already finished"
        )
    if isinstance(action, Diagnose):
        if instance.diagnostic_test(action.test_id) is None:
            return ActionValidation.reject(
                "unknown_test_id",
                "diagnostic test is not in the public catalogue",
            )
    elif isinstance(action, Repair):
        if action.fault_id not in instance.fault_ids:
            return ActionValidation.reject(
                "unknown_fault_id", "repair is not in the public fault catalogue"
            )
    elif isinstance(action, Verify):
        if selected_repair is None:
            return ActionValidation.reject(
                "verify_without_repair",
                "a repair must be selected before verification",
            )
    return ActionValidation.accept()


class HiddenFaultWorld:
    """One mutable instance with private hidden state.

    The controller gives a harness only :meth:`public_description`, never the
    world object itself.  This is a cooperative in-process boundary rather than
    a hostile-code sandbox, so it prevents accidental disclosure through the
    documented API and nothing more.
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

    @property
    def spec(self) -> HiddenFaultSpec:
        return self._spec

    def public_description(self) -> PublicInstance:
        """Return the immutable public boundary object."""

        return self._public

    def validate_action(self, action: object) -> ActionValidation:
        """Decide whether an action is legal without changing any state.

        Validation is separate from :meth:`apply` because the controller has to
        record a rejected action as a protocol failure that still costs one
        unit of budget.
        """

        return validate_action_in_state(
            self._public,
            action,
            finished=self._finished,
            selected_repair=self._selected_repair,
        )

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
            # The result is recorded privately and the harness receives only an
            # acknowledgement, so verification cannot become a free diagnostic.
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

        The runner uses this before policy execution only to build a salted
        commitment.  Neither the world object nor this value is passed to the
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

        This is called only after controller execution has ended.  The result is
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
