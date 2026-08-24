from __future__ import annotations

import math
from fractions import Fraction

import pytest

from metering import (
    ProbabilityError,
    entropy,
    kl_divergence,
    mutual_information,
    self_information,
)


@pytest.mark.parametrize(
    ("probability", "expected"),
    [
        (1.0, 0.0),
        (0.5, 1.0),
        (0.125, 3.0),
        (0.0, math.inf),
    ],
)
def test_self_information_known_values(probability, expected):
    assert self_information(probability) == expected


@pytest.mark.parametrize(
    ("probabilities", "expected"),
    [
        ([1.0, 0.0], 0.0),
        ([0.5, 0.5], 1.0),
        ([0.125] * 8, 3.0),
        ([0.75, 0.25], 0.8112781244591328),
    ],
)
def test_entropy_known_values(probabilities, expected):
    assert entropy(probabilities) == pytest.approx(expected)


def test_zero_probability_entropy_terms_contribute_zero():
    assert entropy([0.0, 0.5, 0.0, 0.5]) == 1.0


def test_iterables_are_materialized_once_without_mutating_containers():
    probabilities = [0.5, 0.5]
    before = list(probabilities)

    assert entropy(probabilities) == entropy(tuple(probabilities))
    assert entropy(value for value in probabilities) == 1.0
    assert probabilities == before


def test_logarithm_base_sets_the_unit():
    assert self_information(0.1, base=10) == pytest.approx(1.0)
    assert entropy([0.5, 0.5], base=math.e) == pytest.approx(math.log(2))
    assert mutual_information([[0.5, 0.0], [0.0, 0.5]], base=10) == pytest.approx(
        math.log10(2)
    )


@pytest.mark.parametrize(
    ("p", "q", "expected"),
    [
        ([0.5, 0.5], [0.5, 0.5], 0.0),
        ([0.5, 0.5], [0.75, 0.25], 0.2075187496394219),
        ([0.75, 0.25], [0.5, 0.5], 0.18872187554086717),
        ([1.0, 0.0], [0.0, 1.0], math.inf),
        ([0.0, 1.0], [0.0, 1.0], 0.0),
    ],
)
def test_kl_divergence_known_values(p, q, expected):
    assert kl_divergence(p, q) == pytest.approx(expected)


def test_kl_divergence_is_directional():
    p = [0.75, 0.25]
    q = [0.5, 0.5]

    assert kl_divergence(p, q) != pytest.approx(kl_divergence(q, p))


def test_kl_uses_log_differences_without_ratio_overflow():
    smallest_positive_float = math.ulp(0.0)

    result = kl_divergence(
        [1.0, 0.0],
        [smallest_positive_float, 1.0],
    )

    assert math.isfinite(result)
    assert result == 1074.0


def test_kl_stays_nonnegative_for_opposite_accepted_rounding_residuals():
    p = [0.5, 0.5 - 9e-13]
    q = [0.5, 0.5 + 9e-13]

    result = kl_divergence(p, q)

    assert result >= 0.0
    assert result < 1e-20


def test_kl_preserves_information_below_machine_epsilon():
    p = [0.125] * 8
    q = list(p)
    epsilon = math.ulp(0.125)
    q[0] += epsilon
    q[1] -= epsilon

    result = kl_divergence(p, q)

    assert result == pytest.approx(
        8.891294655574471e-33,
        rel=1e-14,
        abs=0.0,
    )


@pytest.mark.parametrize(
    ("p_value", "q_value", "expected"),
    [
        (1.51e-300, 1.0e-300, 1.6199383896766353e-301),
        (0.49e-300, 1.0e-300, 2.314927614802083e-301),
    ],
)
def test_kl_uses_a_stable_ratio_outside_the_series_branch(
    p_value,
    q_value,
    expected,
):
    result = kl_divergence([p_value, 1.0], [q_value, 1.0])

    assert result == pytest.approx(expected, rel=2e-15, abs=0.0)


@pytest.mark.parametrize(
    ("joint", "expected"),
    [
        ([[0.25, 0.25], [0.25, 0.25]], 0.0),
        ([[0.5, 0.0], [0.0, 0.5]], 1.0),
        ([[0.5, 0.5], [0.0, 0.0]], 0.0),
        ([[1.0]], 0.0),
        ([[0.4, 0.1], [0.2, 0.3]], 0.12451124978365305),
    ],
)
def test_mutual_information_known_values(joint, expected):
    assert mutual_information(joint) == pytest.approx(expected)


def test_transposing_the_joint_distribution_preserves_mutual_information():
    joint = [[0.4, 0.1], [0.2, 0.3]]
    transposed = [list(column) for column in zip(*joint, strict=True)]

    assert mutual_information(joint) == pytest.approx(
        mutual_information(transposed)
    )


def test_mutual_information_matches_the_shannon_entropy_identity():
    joint = [[0.4, 0.1], [0.2, 0.3]]
    rows = [math.fsum(row) for row in joint]
    columns = [math.fsum(row[index] for row in joint) for index in range(2)]
    flattened = [value for row in joint for value in row]

    expected = entropy(rows) + entropy(columns) - entropy(flattened)

    assert mutual_information(joint) == pytest.approx(expected)


def test_mutual_information_does_not_invent_infinity_after_product_underflow():
    smallest_positive_float = math.ulp(0.0)
    joint = [[smallest_positive_float, 0.0], [0.0, 1.0]]

    result = mutual_information(joint)

    assert math.isfinite(result)
    assert result > 0.0


def test_mutual_information_does_not_use_a_rounded_subnormal_product_in_its_log():
    joint = [
        [1e-300, 1.6e-162],
        [1.6e-162, 1.0],
    ]

    result = mutual_information(joint)

    assert result == pytest.approx(
        7.692743542618246e-299,
        rel=2e-14,
        abs=0.0,
    )


def test_mutual_information_preserves_tiny_dependence():
    epsilon = 1024 * math.ulp(0.25)
    joint = [
        [0.25 + epsilon, 0.25 - epsilon],
        [0.25 - epsilon, 0.25 + epsilon],
    ]

    result = mutual_information(joint)

    assert result == pytest.approx(
        3.729279273905463e-26,
        rel=1e-14,
        abs=0.0,
    )


def test_mutual_information_accepts_rectangular_joint_distributions():
    independent_joint = [
        [0.25, 0.125, 0.125],
        [0.25, 0.125, 0.125],
    ]

    assert mutual_information(independent_joint) == 0.0


@pytest.mark.parametrize(
    "joint",
    [
        [[0.5, 0.5 + 5e-13]],
        [[0.4], [0.6000000000005]],
        [[0.250000000000125] * 2, [0.250000000000125] * 2],
    ],
)
def test_mutual_information_does_not_treat_total_mass_residual_as_dependence(
    joint,
):
    assert mutual_information(joint) == 0.0


def test_zero_results_are_positive_zero():
    results = (
        self_information(1.0),
        entropy([1.0, 0.0]),
        kl_divergence([0.5, 0.5], [0.5, 0.5]),
        mutual_information([[0.25, 0.25], [0.25, 0.25]]),
    )

    assert all(value == 0.0 for value in results)
    assert all(math.copysign(1.0, value) == 1.0 for value in results)


@pytest.mark.parametrize(
    "probability",
    [
        True,
        False,
        -0.1,
        1.1,
        math.nan,
        math.inf,
        -math.inf,
        10**400,
        "0.5",
        None,
    ],
)
def test_self_information_rejects_invalid_probabilities(probability):
    with pytest.raises(ProbabilityError):
        self_information(probability)


def test_exact_reals_cannot_cross_probability_boundaries_during_conversion():
    assert self_information(Fraction(1, 2)) == 1.0

    invalid_values = (
        Fraction(-1, 10**400),
        Fraction(1, 10**400),
        Fraction(2**54 - 1, 2**54),
        Fraction(2**54 + 1, 2**54),
    )
    for value in invalid_values:
        with pytest.raises(ProbabilityError):
            self_information(value)


def test_exact_probability_support_is_not_silently_collapsed():
    tiny = Fraction(1, 10**400)

    with pytest.raises(ProbabilityError, match="double precision"):
        kl_divergence([1, 0], [1 - tiny, tiny])


def test_exact_real_logarithm_bases_must_survive_float_conversion():
    assert entropy([0.5, 0.5], base=Fraction(3, 2)) == pytest.approx(
        math.log(2, 1.5)
    )

    with pytest.raises(ProbabilityError):
        entropy([0.5, 0.5], base=Fraction(2**54 + 1, 2**54))


@pytest.mark.parametrize(
    "base",
    [
        True,
        False,
        1.0,
        0.0,
        -2.0,
        0.5,
        math.nan,
        math.inf,
        -math.inf,
        10**400,
        "2",
    ],
)
def test_measures_reject_invalid_logarithm_bases(base):
    with pytest.raises(ProbabilityError):
        entropy([0.5, 0.5], base=base)


@pytest.mark.parametrize(
    "probabilities",
    [
        [],
        [0.2, 0.2],
        [0.5, -0.5, 1.0],
        [1.1, -0.1],
        [True, False],
        [math.nan, 1.0],
        [math.inf, 0.0],
        "0.5,0.5",
        {0: 0.5, 1: 0.5},
        {0.5},
    ],
)
def test_entropy_rejects_invalid_distributions(probabilities):
    with pytest.raises(ProbabilityError):
        entropy(probabilities)


def test_normalization_uses_one_fixed_absolute_tolerance_without_rewriting_input():
    accepted = [0.5, 0.5 + 5e-13]
    rejected = [0.5, 0.5 + 2e-12]
    before = list(accepted)

    assert math.isfinite(entropy(accepted))
    assert accepted == before
    with pytest.raises(ProbabilityError, match="must sum to 1"):
        entropy(rejected)


def test_kl_requires_equal_lengths():
    with pytest.raises(ProbabilityError, match="same length"):
        kl_divergence([0.5, 0.5], [0.25, 0.25, 0.5])


@pytest.mark.parametrize(
    ("p", "q"),
    [
        ([], [1.0]),
        ([1.0], []),
        ([0.5, 0.4], [0.5, 0.5]),
        ([0.5, 0.5], [0.4, 0.4]),
        ([0.5, True], [0.5, 0.5]),
    ],
)
def test_kl_validates_each_distribution_independently(p, q):
    with pytest.raises(ProbabilityError):
        kl_divergence(p, q)


@pytest.mark.parametrize(
    "joint",
    [
        [],
        [[]],
        [[0.5, 0.25], [0.25]],
        [[0.2, 0.2], [0.2, 0.2]],
        [[0.5, -0.5], [0.5, 0.5]],
        [[True, 0.0], [0.0, False]],
        [[math.nan, 0.0], [0.0, 1.0]],
        [[math.inf, 0.0], [0.0, 0.0]],
        [0.5, 0.5],
        {0: [0.5], 1: [0.5]},
    ],
)
def test_mutual_information_rejects_invalid_joint_distributions(joint):
    with pytest.raises(ProbabilityError):
        mutual_information(joint)


def test_probability_error_is_a_value_error():
    assert issubclass(ProbabilityError, ValueError)


def test_kl_and_mutual_information_do_not_mutate_inputs():
    p = [0.5, 0.5]
    q = [0.75, 0.25]
    joint = [[0.4, 0.1], [0.2, 0.3]]
    before_p = list(p)
    before_q = list(q)
    before_joint = [list(row) for row in joint]

    kl_divergence(p, q)
    mutual_information(joint)

    assert p == before_p
    assert q == before_q
    assert joint == before_joint
