# Metering Plan

## Status

This document defines Metering's complete accepted scope. It replaces the
earlier hidden-fault harness design with a deliberately breaking reset.

Metering has one purpose:

> Measure named information-theoretic quantities from probability
> distributions supplied by the caller.

It is a tool, not an agent. It contains no policy, planner, optimizer, model,
world, controller, belief updater, or recommendation logic.

## Foundation

The fundamental quantity is the logarithmic measure introduced by Claude
Shannon in *A Mathematical Theory of Communication*:

```text
self-information:  I(x) = -log_b p(x)
entropy:            H(P) = -sum_x p(x) log_b p(x)
```

The choice of base fixes the unit. Base 2 is the default and produces bits.
Base `e` produces nats. Metering accepts a real base whose conversion to a
finite Python float remains greater than 1.

The initial implementation supports finite discrete probability models only.
That boundary is intentional. Continuous entropy, sample-based estimation, and
channel optimization require additional assumptions that this package must not
silently invent.

## Public measures

### Self-information

```text
self_information(p, base=2) = -log_b(p)
```

`p` is one probability in `[0, 1]`. A probability of zero returns positive
infinity. A probability of one returns zero.

### Shannon entropy

```text
entropy(P, base=2) = -sum_i p_i log_b(p_i)
```

`P` is a finite discrete probability mass function. Terms with `p_i = 0`
contribute zero.

### Kullback-Leibler divergence

```text
kl_divergence(P, Q, base=2) = sum_i p_i log_b(p_i / q_i)
```

`P` and `Q` are aligned finite distributions of equal length. An index with
`p_i > 0` and `q_i = 0` returns positive infinity. An index with `p_i = 0`
contributes zero. The order matters: `D_KL(P || Q)` is not generally equal to
`D_KL(Q || P)`.

### Mutual information

```text
mutual_information(P_XY, base=2)
    = sum_x sum_y p(x,y) log_b(p(x,y) / (p(x) p(y)))
```

The input is a non-empty rectangular matrix containing a finite joint
distribution. Rows represent outcomes of one variable and columns represent
outcomes of the other. Metering derives only the two marginals required by the
formula; it does not interpret the variables.

## Mathematical naming boundary

Metering does not expose a generic `information_gain` function.

In a uniform deterministic partition, these three values happen to be equal:

```text
H(prior) - H(posterior)
-log_b P(observation)
D_KL(posterior || prior)
```

They differ for general non-uniform or noisy models. Callers must use the name
that matches what they mean:

- entropy before minus entropy after is an entropy change;
- self-information is the surprisal of one declared outcome;
- `D_KL(posterior || prior)` measures a particular distribution update;
- mutual information measures expected dependence between two declared
  variables.

The package must not collapse these into one flattering number.

## Input contract

All validation is strict and visible:

- A probability is a real, non-Boolean number in `[0, 1]` whose conversion to
  a finite Python float does not collapse a nonzero value to zero or a value
  distinct from one to one.
- A distribution is a non-empty ordered iterable of probabilities.
- A distribution's sum must be within an absolute tolerance of `1e-12` from
  one. Relative tolerance is zero.
- A joint distribution is non-empty, rectangular, and normalized as one
  distribution across all cells.
- KL inputs must have equal lengths and use the same positional ordering.
- The logarithm base is a real, non-Boolean number whose conversion to a
  finite Python float remains greater than one.
- Invalid inputs raise `ProbabilityError`.

Metering never normalizes, smooths, clips, bins, samples, or estimates on the
caller's behalf. Acceptance within the fixed sum tolerance accommodates normal
floating-point roundoff. Entropy and self-information use the converted values
as supplied. KL and mutual information use the explicitly declared
non-negative relative-entropy extension below. Nothing is rescaled.

Calculations use Python's double-precision floating-point arithmetic and
`math.fsum` where sums are involved. Results should be compared with a suitable
numerical tolerance rather than by serialized decimal spelling. Metering does
not promise byte-identical last-place decimals across different Python/libm
platforms.

KL is evaluated with the non-negative form
`sum_i (p_i ln(p_i/q_i) - p_i + q_i) / ln(base)`. For normalized distributions,
the added terms sum to zero, so this is algebraically the declared KL formula.
For inputs accepted only because their sums are within tolerance, this formula
is the defined extension and remains non-negative. Close coordinates use the
convergent series for `(1+d) ln(1+d) - d` to avoid cancellation. Mutual
information uses the same form and separates the two marginal logarithms when
their product would underflow. If an accepted joint has total mass `S` that
differs from one only within tolerance, its derived comparison mass is
`row_x * column_y / S`, not the mass-`S^2` raw marginal product. This preserves
zero dependence for factorized tables without rescaling the supplied cells.
These evaluation rules do not normalize or modify either input.

## Python boundary

The complete supported public API is:

```python
from metering import (
    ProbabilityError,
    self_information,
    entropy,
    kl_divergence,
    mutual_information,
)
```

For fixed numeric inputs, the functions are deterministic. They do not read or
write files, access the network, or modify caller-owned containers. A one-shot
iterator is necessarily consumed once when its values are materialized.

## Agent and shell boundary

Other agents use the same measures through one Unix-style command. The command
reads exactly one JSON object from standard input and writes exactly one JSON
object to standard output.

Valid request shapes are:

```json
{"measure":"self_information","probability":0.125}
{"measure":"entropy","probabilities":[0.5,0.5]}
{"measure":"kl_divergence","p":[0.5,0.5],"q":[0.75,0.25]}
{"measure":"mutual_information","joint":[[0.5,0.0],[0.0,0.5]]}
```

Each request may add an optional numeric `base` key. No other keys are
accepted. Duplicate keys and non-finite numbers are rejected. A numeric token
is also rejected if double-precision conversion would produce infinity or
would change whether its value is zero or one.

A finite result has this exact shape:

```json
{"base":2.0,"infinite":false,"measure":"entropy","value":1.0}
```

Positive infinity is represented without emitting invalid JSON:

```json
{"base":2.0,"infinite":true,"measure":"self_information","value":null}
```

The command emits exactly `error.code` and `error.message` as one JSON object
on standard error:

```json
{"error":{"code":"invalid_probability","message":"..."}}
```

The only error codes are `invalid_request` for JSON, command-line, or request
envelope failures, and `invalid_probability` for a rejected probability model
or logarithm base. Exit status is zero for a successful measurement and two
for either error. `-h`/`--help` and `--version` are the only command-line
options; long options are not abbreviated. The command does not read or write
application files and does not make network requests.

This JSON boundary is intentionally not agent-specific. Any agent, shell,
programming language, or process runner that can exchange JSON over standard
streams can use it. An MCP server, plugin system, HTTP service, or model adapter
would add machinery without improving the measurement and does not belong here.

## Permanent non-goals

The Metering package does not contain:

- agents, models, prompts, memories, tools that choose other tools, or model
  adapters;
- policies, planners, search strategies, optimizers, rankings, or scores;
- worlds, tasks, repairs, verification, correctness, budgets, or resource
  accounting;
- posterior construction, Bayesian inference, probability estimation, sample
  binning, smoothing, or normalization;
- trace formats, experiment runners, manifests, commitments, artifact stores,
  replay engines, databases, or dashboards;
- continuous or differential entropy, entropy-rate estimators, channel
  capacity optimization, or learned estimators;
- claims about meaning, relevance, understanding, reasoning, knowledge, or
  intelligence.

Applications may use Metering's outputs when making decisions, but those
applications live outside this repository.

## Repository layout

```text
src/metering/
    __init__.py       exact public Python surface
    information.py    validation and four pure measures
    __main__.py       strict JSON standard-stream adapter
tests/
    test_information.py
    test_cli.py
    test_public_api.py
docs/
    theory.md
```

Add a module only when a concrete responsibility no longer fits one of these
three. Do not introduce a generic abstraction in anticipation of future work.

## Compatibility

This scope reset intentionally removes the previous hidden-fault world,
actions, policies, controller, calibration, reports, trace/replay system,
artifact schemas, and their CLI commands. Existing run artifacts remain usable
only with a checkout of the historical implementation that created them.

There is no compatibility shim. Keeping one would retain the unrelated product
inside the new one and violate the one-purpose boundary.

## Acceptance criteria

The rewrite is complete only when:

- the four formulas match known exact values and independent identities;
- uniform distributions of 2 and 8 outcomes report 1 and 3 bits;
- independent variables report zero mutual information and a perfectly
  correlated fair binary pair reports one bit;
- KL identity, asymmetry, and infinite support mismatch are tested;
- every malformed input category in this plan is rejected;
- the Python public exports contain only the four measures and
  `ProbabilityError`;
- the CLI accepts every documented request, emits valid canonical JSON,
  represents infinity explicitly, and returns documented exit statuses;
- direct calls and CLI calls agree for the same inputs;
- the core performs no filesystem or network access, does not modify input
  containers, and documents consumption of one-shot iterators;
- the package has no runtime dependency;
- no legacy world, policy, controller, agent, optimizer, benchmark, replay, or
  artifact implementation remains in the shipped tree;
- the full test suite and package build pass.

## Source

Claude E. Shannon, “A Mathematical Theory of Communication,” *The Bell System
Technical Journal*, volume 27, pages 379-423 and 623-656, 1948.

- https://doi.org/10.1002/j.1538-7305.1948.tb01338.x
- https://doi.org/10.1002/j.1538-7305.1948.tb00917.x
