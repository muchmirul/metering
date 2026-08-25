# Foundations and claim boundaries

## Three kinds of claim

The repository separates:

1. **Mathematical identities** derived from declared probability models.
2. **Implementation claims** tested against code contracts.
3. **Empirical claims** about future performance, which require external
   experiments.

A passing unit test cannot prove generalization. A biological analogy does not
make software an organism.

## Information measurement

For a finite probability mass function `p` and base `b > 1`:

```text
I_b(x)       = -log_b p(x)
H_b(X)       = -sum_x p(x) log_b p(x)
D_KL(P || Q) = sum_x p(x) log_b[p(x) / q(x)]
I(X;Y)       = D_KL(P_XY || P_X P_Y)
```

Metering evaluates those named quantities after strict validation. The caller
owns the model and interpretation.

## Pairwise evolution

For parent `c_t`, caller-owned proposer `Q`, challenger `c'_t`, and judge `J`:

```text
c'_t = Q(c_t)
v_t  = J(c_t, c'_t)
c_(t+1) = selected(v_t)
```

Evo requires only:

```text
id(c_t) != id(c'_t)
selected(v_t) in {id(c_t), id(c'_t)}
```

This is the smallest inheritance relationship. Mutation without a judge is a
random walk. A verdict without an inherited successor is only a report.

The proposer and judge are not embedded in the kernel because their meanings
change by domain.

## Fixture judge

The fixture example has four hidden versions and two deterministic probes. The
judge chooses a maximum-result-entropy probe under its remaining uniform
hypotheses, captures both candidates' complete forecasts, reveals the target,
and measures target surprisal.

For candidate `c` on evaluation cases `i = 1..n`:

```text
L(c) = -(1/n) sum_i log2 q_c(y_i)
```

The challenger is selected only when:

```text
L(parent) - L(challenger) > threshold
```

This equation belongs to that judge. It is not the definition of evolution.

## Skill adapter

The Pi skill example treats skill text as the candidate value and delegates
proposal and judging to one external command. A Pi or Prime Agent adapter may
rewrite the skill and run hidden coding tasks. Another adapter may use tests,
safety scans, or human review.

The checked-in demo adapter is deterministic and proves protocol composition,
not agent intelligence.

## Implementation hypotheses

The implementation is falsified by any accepted transition that:

```text
uses an empty candidate ID
uses identical parent and challenger IDs
selects an unrelated ID
stores a next parent inconsistent with the verdict
requires domain-specific branches in Evo
```

The fixture example is falsified if its checked-in `v3` case fails to promote
the challenger or its `v4` regression case promotes it.

## External empirical hypothesis

A real self-evolution experiment may test whether evidence-gated retention
produces lower loss or higher task success on untouched final cases than a
measurement-independent retention rule under matched budgets.

That claim requires repeated runs, predeclared evaluation design, leakage
control, fresh holdout cases, uncertainty reporting, and explicit handling of
catastrophic failures. This repository does not claim that result.
