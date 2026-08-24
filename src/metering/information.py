"""Pure information measures for finite discrete probability distributions.

The caller supplies the probability model.  This module validates that model
and evaluates a named formula.  It does not estimate probabilities, update a
belief, select an action, or interpret what an outcome means.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Set
from numbers import Real

__all__ = [
    "ProbabilityError",
    "entropy",
    "kl_divergence",
    "mutual_information",
    "self_information",
]

_NORMALIZATION_TOLERANCE = 1e-12


class ProbabilityError(ValueError):
    """Raised when a probability model is outside the supported domain."""


def _validated_base(base: Real) -> float:
    if isinstance(base, bool) or not isinstance(base, Real):
        raise ProbabilityError("base must be a real number greater than 1")
    if base <= 1:
        raise ProbabilityError("base must be a finite real number greater than 1")
    try:
        value = float(base)
    except (OverflowError, ValueError) as exc:
        raise ProbabilityError(
            "base must be a finite real number greater than 1"
        ) from exc
    if not math.isfinite(value) or value <= 1.0:
        raise ProbabilityError("base must be a finite real number greater than 1")
    return value


def _validated_probability(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ProbabilityError(f"{name} must be a real number")
    if value < 0 or value > 1:
        raise ProbabilityError(f"{name} must be between 0 and 1")
    try:
        probability = float(value)
    except (OverflowError, ValueError) as exc:
        raise ProbabilityError(f"{name} must be finite") from exc
    if not math.isfinite(probability):
        raise ProbabilityError(f"{name} must be finite")
    if probability == 0.0 and value != 0:
        raise ProbabilityError(
            f"{name} is nonzero but too small for double-precision measurement"
        )
    if probability == 1.0 and value != 1:
        raise ProbabilityError(
            f"{name} is distinct from 1 but rounds to 1 in double precision"
        )
    return 0.0 if probability == 0.0 else probability


def _materialize(values: Iterable[Real], name: str) -> tuple[object, ...]:
    if isinstance(values, (str, bytes, bytearray, Mapping, Set)):
        raise ProbabilityError(f"{name} must be an ordered iterable of probabilities")
    try:
        result = tuple(values)
    except TypeError as exc:
        raise ProbabilityError(
            f"{name} must be an ordered iterable of probabilities"
        ) from exc
    if not result:
        raise ProbabilityError(f"{name} must not be empty")
    return result


def _probability_values(values: Iterable[Real], name: str) -> tuple[float, ...]:
    return tuple(
        _validated_probability(value, f"{name}[{index}]")
        for index, value in enumerate(_materialize(values, name))
    )


def _require_normalized(values: tuple[float, ...], name: str) -> None:
    total = math.fsum(values)
    if not math.isclose(
        total,
        1.0,
        rel_tol=0.0,
        abs_tol=_NORMALIZATION_TOLERANCE,
    ):
        raise ProbabilityError(
            f"{name} must sum to 1 within {_NORMALIZATION_TOLERANCE:g}; "
            f"got {total:.17g}"
        )


def _distribution(values: Iterable[Real], name: str) -> tuple[float, ...]:
    probabilities = _probability_values(values, name)
    _require_normalized(probabilities, name)
    return probabilities


def _joint_distribution(
    joint: Iterable[Iterable[Real]],
) -> tuple[tuple[float, ...], ...]:
    raw_rows = _materialize(joint, "joint")
    rows: list[tuple[float, ...]] = []
    width: int | None = None
    for row_index, raw_row in enumerate(raw_rows):
        row = _probability_values(raw_row, f"joint[{row_index}]")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ProbabilityError("joint must be rectangular")
        rows.append(row)
    result = tuple(rows)
    _require_normalized(tuple(value for row in result for value in row), "joint")
    return result


def _kl_from_validated(
    p: tuple[float, ...], q: tuple[float, ...], base: float
) -> float:
    terms = [
        _relative_entropy_term(p_value, q_value)
        for p_value, q_value in zip(p, q, strict=True)
    ]
    if math.inf in terms:
        return math.inf
    result = math.fsum(terms) / math.log(base)
    return 0.0 if result == 0.0 else result


def _relative_entropy_term(
    p: float,
    q: float,
    *,
    log_q: float | None = None,
    ratio: float | None = None,
) -> float:
    """Evaluate ``p ln(p/q) - p + q`` without near-equality cancellation."""

    if ratio is None and p == q:
        return 0.0
    if p == 0.0:
        return q
    if q == 0.0:
        return math.inf

    if ratio is None:
        difference = p - q
        delta = difference / q
        scale = q
    else:
        if ratio == 1.0:
            return 0.0
        delta = ratio - 1.0
        scale = p / ratio

    if abs(delta) <= 0.5:
        # (1+d) ln(1+d) - d
        #   = d^2/2 - d^3/6 + d^4/12 - ...
        # Every accepted d here has |d| <= 1/2, so the series converges fast.
        signed_power = delta * delta
        series = signed_power / 2.0
        for order in range(3, 256):
            signed_power *= -delta
            addition = signed_power / (order * (order - 1))
            updated = series + addition
            if updated == series:
                break
            series = updated
        return scale * series

    if ratio is None:
        ratio = p / q
    if 0.0 < ratio < math.inf:
        logarithm = math.log(ratio)
    else:
        q_logarithm = math.log(q) if log_q is None else log_q
        logarithm = math.log(p) - q_logarithm
    return p * logarithm - p + q


def self_information(probability: Real, *, base: Real = 2) -> float:
    """Return ``-log_base(probability)`` for one outcome.

    A zero-probability outcome has infinite self-information.
    """

    checked_base = _validated_base(base)
    checked_probability = _validated_probability(probability, "probability")
    if checked_probability == 0.0:
        return math.inf
    result = -math.log(checked_probability) / math.log(checked_base)
    return 0.0 if result == 0.0 else result


def entropy(probabilities: Iterable[Real], *, base: Real = 2) -> float:
    """Return Shannon entropy for a finite discrete distribution."""

    checked_base = _validated_base(base)
    distribution = _distribution(probabilities, "probabilities")
    natural_entropy = math.fsum(
        -probability * math.log(probability)
        for probability in distribution
        if probability > 0.0
    )
    result = natural_entropy / math.log(checked_base)
    return 0.0 if result == 0.0 else result


def kl_divergence(
    p: Iterable[Real], q: Iterable[Real], *, base: Real = 2
) -> float:
    """Return ``D_KL(p || q)`` for two aligned discrete distributions."""

    checked_base = _validated_base(base)
    p_distribution = _distribution(p, "p")
    q_distribution = _distribution(q, "q")
    if len(p_distribution) != len(q_distribution):
        raise ProbabilityError("p and q must have the same length")
    return _kl_from_validated(p_distribution, q_distribution, checked_base)


def mutual_information(
    joint: Iterable[Iterable[Real]], *, base: Real = 2
) -> float:
    """Return mutual information for a rectangular joint distribution.

    Rows identify outcomes of one variable and columns identify outcomes of the
    other.  Labels are irrelevant; only the supplied joint probabilities are
    measured.
    """

    checked_base = _validated_base(base)
    distribution = _joint_distribution(joint)
    row_marginals = tuple(math.fsum(row) for row in distribution)
    total_probability = math.fsum(row_marginals)
    column_count = len(distribution[0])
    column_marginals = tuple(
        math.fsum(row[column] for row in distribution)
        for column in range(column_count)
    )
    terms: list[float] = []
    for row_index, row in enumerate(distribution):
        row_probability = row_marginals[row_index]
        row_share = row_probability / total_probability
        for column_index, joint_probability in enumerate(row):
            column_probability = column_marginals[column_index]
            independent_probability = row_share * column_probability
            if joint_probability == 0.0:
                terms.append(independent_probability)
                continue
            marginal_logarithm = math.log(row_share) + math.log(
                column_probability
            )
            if independent_probability == 0.0 and joint_probability > 0.0:
                # The mathematical product is positive but below binary64.
                # Its omitted +q correction is itself unrepresentable.
                terms.append(
                    joint_probability
                    * (math.log(joint_probability) - marginal_logarithm)
                    - joint_probability
                )
            else:
                factor_ratio = (
                    joint_probability / row_share / column_probability
                )
                terms.append(
                    _relative_entropy_term(
                        joint_probability,
                        independent_probability,
                        log_q=marginal_logarithm,
                        ratio=factor_ratio,
                    )
                )
    result = math.fsum(terms) / math.log(checked_base)
    return 0.0 if result == 0.0 else result
