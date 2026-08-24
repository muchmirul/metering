# Theory and measurement boundary

This document derives the installed package's four named measurements. The
[system foundations](foundations.md) connect them to the repository applications,
software-design rationale, and falsifiable hypotheses without changing this
measurement boundary.

Metering starts with Shannon's logarithmic measure of information. For an
outcome with declared probability `p`, its self-information is:

```text
I(x) = -log_b p(x)
```

Less probable outcomes carry more self-information. The expected
self-information of a finite discrete random variable is Shannon entropy:

```text
H(X) = -sum_x p(x) log_b p(x)
```

The base determines the unit. Base 2 gives bits; base `e` gives nats. Metering
defaults to base 2.

For a uniform distribution over `n` outcomes, entropy reduces to:

```text
H(X) = log_b n
```

Thus a fair binary variable has one bit and a uniform eight-outcome variable
has three bits. This is a special case, not the general definition.

## Relative entropy

Kullback-Leibler divergence compares two aligned probability distributions:

```text
D_KL(P || Q) = sum_x p(x) log_b(p(x) / q(x))
```

It is directional. It is zero when the distributions are identical and becomes
infinite when `P` assigns positive probability to an outcome that `Q` declares
impossible.

When `P` is a posterior and `Q` is its prior, `D_KL(P || Q)` is a precise
measure of that particular distribution update. Metering performs neither the
Bayesian update nor the choice of prior; both are caller-owned modeling work.

## Mutual information

Mutual information compares a joint distribution with the product of its
marginals:

```text
I(X;Y) = D_KL(P_XY || P_X P_Y)
       = sum_x sum_y p(x,y) log_b(p(x,y) / (p(x)p(y)))
```

It is zero when the supplied joint distribution says the variables are
independent. A perfectly correlated pair of fair binary variables carries one
bit of mutual information.

Metering accepts the joint table and derives its row and column marginals. It
does not assign meaning to either dimension.

## Why there is no generic information gain

Suppose an observation changes a distribution from a prior to a posterior.
Three quantities may be relevant:

```text
entropy change:       H(prior) - H(posterior)
outcome surprisal:   -log_b P(observation)
distribution update: D_KL(posterior || prior)
```

In a uniform prior partitioned by a deterministic observation, these can have
the same numeric value. Outside that special case they do not. In particular,
the entropy of a posterior may be greater than the entropy of its prior for a
particular observation, while KL divergence remains non-negative.

A general `information_gain` name would hide which quantity was calculated.
Metering therefore exposes the underlying measures and leaves the caller to
state the model and intended interpretation.

## What Shannon information does not say

These formulas operate on declared probability models. They do not measure
semantic meaning, usefulness, truth, understanding, intelligence, knowledge,
or whether an agent acted on the information. A caller can build such claims
only by adding assumptions and evidence outside this package.

Metering also does not estimate distributions from observations. Binning,
smoothing, priors, density estimation, and finite-sample corrections change the
answer and require explicit modeling choices. The tool accepts a distribution
only after the caller has made those choices.

## Numerical conventions

- Probability values lie in `[0, 1]` and convert to finite Python floats
  without collapsing a nonzero value to zero or a value distinct from one to
  one.
- Probability mass must sum to one within absolute tolerance `1e-12`.
- The tool does not renormalize accepted input.
- Terms with zero probability use the continuous convention `0 log 0 = 0`.
- Impossible events may produce positive infinity where the formula requires
  it.
- Calculations use double-precision floating point and `math.fsum` for sums.
- Last-place decimal output can vary across Python/libm platforms; consumers
  compare nontrivial values with a numerical tolerance.
- KL uses the equivalent non-negative form
  `sum(p ln(p/q) - p + q) / ln(base)`. The added terms total zero for normalized
  distributions and prevent tiny accepted normalization residuals from
  producing a negative floating-point result. Near-equal terms use the series
  for `(1+d) ln(1+d) - d` rather than subtracting nearly equal floats.
- Mutual information subtracts `ln p(x)` and `ln p(y)` separately instead of
  taking the logarithm of their product, which may underflow for valid
  subnormal probabilities.
- For a joint accepted with total mass `S` within normalization tolerance, the
  independent comparison uses `row_x * column_y / S`. Its total mass therefore
  matches the supplied table instead of turning the residual `S - 1` into
  spurious dependence.

## Design rationale and implementation hypothesis

The public surface keeps self-information, entropy, KL divergence, and mutual
information separate because they answer different questions outside special
models. Requiring caller-supplied finite PMFs makes every mathematical input
explicit and keeps estimation choices out of a deterministic measurement tool.
Purity and a strict one-request JSON filter make direct and subprocess results
independently reproducible from the same declared numbers.

The falsifiable implementation hypothesis is:

> Every accepted input is evaluated according to its named finite-discrete
> equation and documented floating-point extension, while every malformed or
> ambiguous model is rejected rather than repaired.

A valid counterexample to an exact identity, support rule, normalization
boundary, numerical convention, purity claim, or direct/CLI agreement falsifies
that hypothesis. Passing the tests establishes only implementation conformance;
it does not validate the caller's model or interpretation.

## Primary sources

- Claude E. Shannon, “A Mathematical Theory of Communication,” *The Bell System
  Technical Journal*, volume 27, pages 379-423 and 623-656, 1948:
  [part I](https://doi.org/10.1002/j.1538-7305.1948.tb01338.x) and
  [part II](https://doi.org/10.1002/j.1538-7305.1948.tb00917.x).
- Solomon Kullback and Richard A. Leibler, “On Information and Sufficiency,”
  *The Annals of Mathematical Statistics*, volume 22, pages 79-86, 1951:
  [DOI](https://doi.org/10.1214/aoms/1177729694).
