"""Deterministic finite mathematics for source-only population search.

The functions in this module do not choose objectives or invent a universal
fitness score. Callers supply finite values, objective directions, weights,
contribution factors, and random draws explicitly.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


class PopulationMathError(ValueError):
    """Raised when declared population mathematics is malformed."""


@dataclass(frozen=True)
class Objective:
    """One caller-declared objective used for comparison and scalarization."""

    metric: str
    direction: str
    weight: float

    @property
    def sign(self) -> float:
        return 1.0 if self.direction == "maximize" else -1.0


def finite_number(value: object, location: str) -> float:
    """Return one finite non-Boolean double-precision value."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PopulationMathError(f"{location} must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise PopulationMathError(f"{location} must be a finite number")
    return 0.0 if converted == 0.0 else converted


def nonnegative_number(value: object, location: str) -> float:
    converted = finite_number(value, location)
    if converted < 0.0:
        raise PopulationMathError(f"{location} must be non-negative")
    return converted


def normalized_distribution(
    values: Sequence[object], location: str = "weights"
) -> list[float]:
    """Normalize finite non-negative values after requiring positive mass."""

    if not values:
        raise PopulationMathError(f"{location} must not be empty")
    converted = [
        nonnegative_number(value, f"{location}[{index}]")
        for index, value in enumerate(values)
    ]
    total = math.fsum(converted)
    if total <= 0.0 or not math.isfinite(total):
        raise PopulationMathError(f"{location} must contain positive finite mass")
    normalized = [value / total for value in converted]
    correction = 1.0 - math.fsum(normalized)
    normalized[-1] += correction
    if normalized[-1] < 0.0:
        raise PopulationMathError(f"{location} cannot be normalized safely")
    return normalized


def weighted_mean(values: Sequence[object], weights: Sequence[object]) -> float:
    if not values or len(values) != len(weights):
        raise PopulationMathError("values and weights must have the same non-zero length")
    normalized = normalized_distribution(weights)
    converted = [
        finite_number(value, f"values[{index}]")
        for index, value in enumerate(values)
    ]
    return math.fsum(weight * value for weight, value in zip(normalized, converted))


def weighted_variance(values: Sequence[object], weights: Sequence[object]) -> float:
    if not values or len(values) != len(weights):
        raise PopulationMathError("values and weights must have the same non-zero length")
    normalized = normalized_distribution(weights)
    converted = [
        finite_number(value, f"values[{index}]")
        for index, value in enumerate(values)
    ]
    mean = math.fsum(
        weight * value for weight, value in zip(normalized, converted)
    )
    return math.fsum(
        weight * (value - mean) ** 2
        for weight, value in zip(normalized, converted)
    )


def weighted_covariance(
    left: Sequence[object], right: Sequence[object], weights: Sequence[object]
) -> float:
    if not left or len(left) != len(right) or len(left) != len(weights):
        raise PopulationMathError(
            "left, right, and weights must have the same non-zero length"
        )
    normalized = normalized_distribution(weights)
    left_values = [
        finite_number(value, f"left[{index}]")
        for index, value in enumerate(left)
    ]
    right_values = [
        finite_number(value, f"right[{index}]")
        for index, value in enumerate(right)
    ]
    left_mean = math.fsum(
        weight * value for weight, value in zip(normalized, left_values)
    )
    right_mean = math.fsum(
        weight * value for weight, value in zip(normalized, right_values)
    )
    return math.fsum(
        weight * (left_value - left_mean) * (right_value - right_mean)
        for weight, left_value, right_value in zip(
            normalized, left_values, right_values
        )
    )


def decode_objectives(value: object) -> list[Objective]:
    """Decode a non-empty ordered objective declaration."""

    if type(value) is not list or not value:
        raise PopulationMathError("objectives must be a non-empty JSON array")
    objectives: list[Objective] = []
    seen: set[str] = set()
    positive_weight = False
    for index, raw in enumerate(value):
        location = f"objectives[{index}]"
        if type(raw) is not dict or set(raw) != {"direction", "metric", "weight"}:
            raise PopulationMathError(
                f"{location} must contain exactly direction, metric, and weight"
            )
        metric = raw["metric"]
        if type(metric) is not str or not metric or "\x00" in metric:
            raise PopulationMathError(f"{location}.metric must be a non-empty string")
        if metric in seen:
            raise PopulationMathError(f"objectives contains duplicate metric: {metric}")
        seen.add(metric)
        direction = raw["direction"]
        if direction not in {"maximize", "minimize"}:
            raise PopulationMathError(
                f"{location}.direction must be maximize or minimize"
            )
        weight = nonnegative_number(raw["weight"], f"{location}.weight")
        positive_weight = positive_weight or weight > 0.0
        objectives.append(Objective(metric, str(direction), weight))
    if not positive_weight:
        raise PopulationMathError("at least one objective weight must be positive")
    return objectives


def declared_score(metrics: Mapping[str, object], objectives: Sequence[Objective]) -> float:
    terms: list[float] = []
    for objective in objectives:
        if objective.metric not in metrics:
            raise PopulationMathError(f"metrics is missing objective: {objective.metric}")
        value = finite_number(metrics[objective.metric], f"metrics.{objective.metric}")
        terms.append(objective.sign * objective.weight * value)
    score = math.fsum(terms)
    if not math.isfinite(score):
        raise PopulationMathError("declared score is not finite")
    return 0.0 if score == 0.0 else score


def pareto_dominates(
    left: Mapping[str, object],
    right: Mapping[str, object],
    objectives: Sequence[Objective],
) -> bool:
    """Return whether left is no worse everywhere and better somewhere."""

    strictly_better = False
    for objective in objectives:
        if objective.metric not in left or objective.metric not in right:
            raise PopulationMathError(f"missing objective metric: {objective.metric}")
        left_value = objective.sign * finite_number(
            left[objective.metric], f"left.{objective.metric}"
        )
        right_value = objective.sign * finite_number(
            right[objective.metric], f"right.{objective.metric}"
        )
        if left_value < right_value:
            return False
        strictly_better = strictly_better or left_value > right_value
    return strictly_better


def pareto_front(
    metrics_by_id: Mapping[str, Mapping[str, object]],
    objectives: Sequence[Objective],
) -> list[str]:
    """Return deterministic candidate IDs on the non-dominated frontier."""

    candidate_ids = sorted(metrics_by_id)
    frontier: list[str] = []
    for candidate_id in candidate_ids:
        if not any(
            other_id != candidate_id
            and pareto_dominates(
                metrics_by_id[other_id], metrics_by_id[candidate_id], objectives
            )
            for other_id in candidate_ids
        ):
            frontier.append(candidate_id)
    return frontier


def softmax_distribution(scores: Sequence[object], beta: object) -> list[float]:
    """Return a stable softmax distribution for an explicit selection pressure."""

    if not scores:
        raise PopulationMathError("scores must not be empty")
    pressure = nonnegative_number(beta, "beta")
    converted = [
        finite_number(score, f"scores[{index}]")
        for index, score in enumerate(scores)
    ]
    if pressure == 0.0:
        return [1.0 / len(converted)] * len(converted)
    maximum = max(converted)
    factors = [math.exp(pressure * (score - maximum)) for score in converted]
    return normalized_distribution(factors, "softmax factors")


def replicator_update(
    prior: Sequence[object], contribution_factors: Sequence[object]
) -> list[float]:
    """Apply one finite discrete replicator update.

    p'_i = p_i q_i / sum_j p_j q_j
    """

    if not prior or len(prior) != len(contribution_factors):
        raise PopulationMathError(
            "prior and contribution_factors must have the same non-zero length"
        )
    normalized_prior = normalized_distribution(prior, "prior")
    contributions = [
        nonnegative_number(value, f"contribution_factors[{index}]")
        for index, value in enumerate(contribution_factors)
    ]
    return normalized_distribution(
        [
            probability * contribution
            for probability, contribution in zip(normalized_prior, contributions)
        ],
        "replicator mass",
    )


def draw_index(distribution: Sequence[object], draw: object) -> int:
    """Resolve one externally supplied draw in [0, 1) deterministically."""

    probabilities = normalized_distribution(distribution, "distribution")
    value = finite_number(draw, "draw")
    if not 0.0 <= value < 1.0:
        raise PopulationMathError("draw must be in [0, 1)")
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += probability
        if value < cumulative or index == len(probabilities) - 1:
            return index
    raise AssertionError("normalized distribution did not resolve a draw")


def draw_without_replacement(
    candidate_ids: Sequence[str],
    distribution: Sequence[object],
    draws: Sequence[object],
) -> list[str]:
    """Draw one or more distinct candidates with explicit draws."""

    if not candidate_ids or len(candidate_ids) != len(distribution):
        raise PopulationMathError(
            "candidate_ids and distribution must have the same non-zero length"
        )
    if len(set(candidate_ids)) != len(candidate_ids):
        raise PopulationMathError("candidate_ids must be unique")
    if len(draws) > len(candidate_ids):
        raise PopulationMathError("cannot draw more parents than candidates")
    remaining_ids = list(candidate_ids)
    remaining = normalized_distribution(distribution, "distribution")
    selected: list[str] = []
    for raw_draw in draws:
        index = draw_index(remaining, raw_draw)
        selected.append(remaining_ids.pop(index))
        remaining.pop(index)
        if remaining:
            remaining = normalized_distribution(remaining, "remaining distribution")
    return selected


def price_decomposition(
    traits: Sequence[object],
    contributions: Sequence[object],
    descendant_changes: Sequence[object],
    weights: Sequence[object],
) -> dict[str, float]:
    """Return the weighted Price-equation accounting identity."""

    length = len(traits)
    if (
        length == 0
        or len(contributions) != length
        or len(descendant_changes) != length
        or len(weights) != length
    ):
        raise PopulationMathError(
            "traits, contributions, descendant_changes, and weights must have "
            "the same non-zero length"
        )
    normalized = normalized_distribution(weights)
    trait_values = [
        finite_number(value, f"traits[{index}]")
        for index, value in enumerate(traits)
    ]
    contribution_values = [
        nonnegative_number(value, f"contributions[{index}]")
        for index, value in enumerate(contributions)
    ]
    changes = [
        finite_number(value, f"descendant_changes[{index}]")
        for index, value in enumerate(descendant_changes)
    ]
    mean_contribution = math.fsum(
        weight * contribution
        for weight, contribution in zip(normalized, contribution_values)
    )
    if mean_contribution <= 0.0:
        raise PopulationMathError("mean contribution must be positive")
    allocation_effect = (
        weighted_covariance(trait_values, contribution_values, normalized)
        / mean_contribution
    )
    change_effect = (
        math.fsum(
            weight * contribution * change
            for weight, contribution, change in zip(
                normalized, contribution_values, changes
            )
        )
        / mean_contribution
    )
    total_delta = allocation_effect + change_effect
    return {
        "allocation_effect": 0.0 if allocation_effect == 0.0 else allocation_effect,
        "change_effect": 0.0 if change_effect == 0.0 else change_effect,
        "mean_contribution": mean_contribution,
        "total_delta": 0.0 if total_delta == 0.0 else total_delta,
    }
