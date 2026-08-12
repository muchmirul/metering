"""Deterministic in-process reference policies for the calibration world."""

from __future__ import annotations

import hashlib
from typing import Any, Protocol, Sequence, runtime_checkable

from .events import (
    Action,
    Diagnose,
    DiagnosticObservation,
    Finish,
    Observation,
    Repair,
    RepairObservation,
    VerificationObservation,
    Verify,
)
from .hidden_fault import DiagnosticTest, PublicInstance


class PolicyError(RuntimeError):
    """Raised when a reference policy cannot reconcile its public history."""


@runtime_checkable
class HarnessPolicy(Protocol):
    """The intentionally small cooperative Metering harness boundary."""

    name: str
    version: str

    def next_action(
        self, instance: PublicInstance, observations: Sequence[Observation]
    ) -> Action:
        """Choose one typed action from public input and delivered observations."""

    def descriptor(self) -> dict[str, Any]:
        """Return JSON-compatible policy configuration for the manifest."""


def remaining_candidates(
    instance: PublicInstance, observations: Sequence[Observation]
) -> tuple[str, ...]:
    """Filter candidates using delivered diagnostic outcomes only.

    Choosing a test is not itself evidence.  Repair and verification outcomes
    also do not enter this diagnostic candidate calculation.
    """

    candidates = list(instance.fault_ids)
    for observation in observations:
        if not isinstance(observation, DiagnosticObservation):
            continue
        test = instance.diagnostic_test(observation.test_id)
        if test is None:
            raise PolicyError(
                f"history names unknown diagnostic test {observation.test_id!r}"
            )
        candidates = [
            fault_id
            for fault_id in candidates
            if test.outcome(fault_id) is observation.positive
        ]
        if not candidates:
            raise PolicyError("diagnostic history is impossible under the public model")
    return tuple(candidates)


def _post_repair_action(observations: Sequence[Observation]) -> Action | None:
    last_repair = -1
    last_verification = -1
    for index, observation in enumerate(observations):
        if isinstance(observation, RepairObservation):
            last_repair = index
        elif isinstance(observation, VerificationObservation):
            last_verification = index
    if last_repair < 0:
        return None
    if last_verification > last_repair:
        return Finish()
    return Verify()


def _unused_informative_tests(
    instance: PublicInstance,
    observations: Sequence[Observation],
    candidates: Sequence[str],
) -> list[tuple[int, DiagnosticTest]]:
    used = {
        observation.test_id
        for observation in observations
        if isinstance(observation, DiagnosticObservation)
    }
    candidate_set = set(candidates)
    result: list[tuple[int, DiagnosticTest]] = []
    for catalogue_index, test in enumerate(instance.diagnostic_tests):
        if test.test_id in used:
            continue
        positive_count = len(candidate_set.intersection(test.positive_fault_ids))
        if 0 < positive_count < len(candidate_set):
            result.append((catalogue_index, test))
    return result


class BalancedSearchPolicy:
    """Choose the catalogue test with the most even remaining split."""

    name = "balanced-search"
    version = "1"

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {"tie_break": "public_catalogue_order"},
            "seed_policy": {"kind": "none"},
        }

    def next_action(
        self, instance: PublicInstance, observations: Sequence[Observation]
    ) -> Action:
        post_repair = _post_repair_action(observations)
        if post_repair is not None:
            return post_repair

        candidates = remaining_candidates(instance, observations)
        if len(candidates) == 1:
            return Repair(candidates[0])

        choices = _unused_informative_tests(instance, observations, candidates)
        if not choices:
            raise PolicyError("no unused catalogue test can separate the candidates")

        candidate_set = set(candidates)
        # max(min(side sizes)) selects the most even split.  Negating the
        # catalogue index gives the first public entry the deterministic tie.
        _, selected = max(
            choices,
            key=lambda item: (
                min(
                    len(candidate_set.intersection(item[1].positive_fault_ids)),
                    len(candidate_set.difference(item[1].positive_fault_ids)),
                ),
                -item[0],
            ),
        )
        return Diagnose(selected.test_id)


class SequentialSearchPolicy:
    """Check singleton candidates in public order, inferring the final one."""

    name = "sequential-search"
    version = "1"

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {
                "candidate_order": "public_fault_order",
                "infer_last_after_negatives": True,
            },
            "seed_policy": {"kind": "none"},
        }

    def next_action(
        self, instance: PublicInstance, observations: Sequence[Observation]
    ) -> Action:
        post_repair = _post_repair_action(observations)
        if post_repair is not None:
            return post_repair

        candidates = remaining_candidates(instance, observations)
        if len(candidates) == 1:
            # In particular, the eighth state is inferred after seven negative
            # singleton observations.  It is not tested redundantly.
            return Repair(candidates[0])

        candidate = candidates[0]
        for test in instance.diagnostic_tests:
            if test.positive_fault_ids == (candidate,):
                return Diagnose(test.test_id)
        raise PolicyError(f"no singleton diagnostic exists for {candidate!r}")


class SeededRandomSearchPolicy:
    """Choose an informative unused test by a declared seeded hash ranking.

    SHA-256 ranking avoids relying on the implementation details of
    ``random.Random`` across Python releases while retaining a reproducible
    random-looking baseline.
    """

    name = "seeded-random-search"
    version = "1"

    def __init__(self, seed: int = 20260722) -> None:
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        self.seed = seed

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {"selection_algorithm": "sha256-rank-v1"},
            "seed_policy": {"kind": "fixed", "seed": self.seed},
        }

    def next_action(
        self, instance: PublicInstance, observations: Sequence[Observation]
    ) -> Action:
        post_repair = _post_repair_action(observations)
        if post_repair is not None:
            return post_repair

        candidates = remaining_candidates(instance, observations)
        if len(candidates) == 1:
            return Repair(candidates[0])

        choices = _unused_informative_tests(instance, observations, candidates)
        if not choices:
            raise PolicyError("no unused catalogue test can separate the candidates")

        diagnostic_history = ";".join(
            f"{item.test_id}:{int(item.positive)}"
            for item in observations
            if isinstance(item, DiagnosticObservation)
        )

        def rank(item: tuple[int, DiagnosticTest]) -> bytes:
            _, test = item
            material = (
                f"metering-seeded-random-v1|{self.seed}|"
                f"{diagnostic_history}|{test.test_id}"
            ).encode("utf-8")
            return hashlib.sha256(material).digest()

        _, selected = min(choices, key=rank)
        return Diagnose(selected.test_id)
