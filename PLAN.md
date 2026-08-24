# Metering Plan

## Status

This document defines Metering's complete accepted scope. It replaces the
earlier hidden-fault harness design with a deliberately breaking reset.

The installed Metering package has one measurement purpose:

> Measure named information-theoretic quantities from probability
> distributions supplied by the caller.

It is a tool, not an agent. The package contains no policy, planner, optimizer,
model, world, controller, belief updater, or recommendation logic. A separate,
explicit history command may retain accepted measurement requests and responses;
it does not change or interpret them.

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

## Measurement history boundary

`metering-history` is an explicit, filesystem-writing wrapper around the public
`metering` command. The ordinary Python functions and `metering` command never
enable it implicitly. Recording one request is deliberate:

```bash
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | metering-history record PATH
```

The wrapper first asks `metering` to validate and measure the request. A rejected
request leaves the history untouched. An accepted request and its exact response
form a pair with these two identities:

```text
pair_id   = SHA-256(canonical JSON of request and response)
record_id = SHA-256(canonical JSON of pair, Metering version, and parent record)
```

`pair_id` is content identity: the same normalized request and response have the
same pair ID. `record_id` is history identity: appending the same pair at a new
place in the lineage produces a new record ID. Each immutable object contains
exactly `schema_version`, `metering_version`, `pair_id`, `parent_record_id`,
`request`, and `response`. `HEAD` points to the latest record. Objects and `HEAD`
are canonical UTF-8 JSON or lowercase SHA-256 text, respectively.

The complete command surface is:

```text
metering-history record PATH   read one Metering request and append its pair
metering-history log PATH      emit HEAD and reachable records, newest first
metering-history verify PATH   verify hashes, links, canonical form, and reachability
```

Successful commands emit one canonical JSON object. Storage or integrity failures
emit `invalid_history` through the same `error.code` and `error.message` envelope
and exit with status two. Measurement request failures preserve the error produced
by `metering` and do not create storage.

This is a linear local ledger, not a general version-control system. It has no
branches, merges, remotes, tags, checkout, signing, wall-clock metadata, or
automatic replay. Hash verification detects accidental modification and broken
lineage; it does not authenticate who created a record or prove that a stored
response was produced by trusted software. A stale `LOCK` directory after an
interrupted writer must be inspected and removed by the caller.

## Application boundary

Small, non-packaged applications may live under `apps/` to demonstrate how a
caller constructs a probability model and invokes Metering through its public
boundary. Application code may observe a world, update caller-owned state, and
use a measurement when choosing an action. Those responsibilities remain in
the application and are not re-exported from `metering`.

Every application must state:

- what the outcomes in each supplied distribution mean;
- how the probabilities were constructed;
- which named Metering result is being reported; and
- what the result does not establish.

The `apps/forecast_assay` example is a stateless screening adapter. Each
request and successful report carries application schema version 1. A request
identifies one candidate, one fixed evaluation, and unique observed cases. The
caller supplies the probability that a normalized candidate forecast assigned
to each named target before that target was revealed. The adapter reports the
target self-information and an explicitly application-owned, equally weighted
arithmetic mean. Default transport handles one request and exits; `--jsonl`
processes independent requests one per line without retaining candidate state.
It does not generate mutations, compare or retain candidates, implement an
environment, or run an evolution loop.

The `apps/observer` example owns a finite versioned sandbox, a uniform candidate
belief, and an immutable probe catalogue. Its default deterministic demo chooses
the maximum-result-entropy probe. Its `--jsonl` transport instead accepts
external-agent `state`, `observe`, and `finish` actions sequentially, returning
one flushed response per input line while keeping the active sandbox private.
The application constructs and conditions the probability model; Metering only
measures its declared distributions. The protocol does not add agent policy,
nonuniform priors, persistence, or application behavior to the installed
package.

The `apps/mutator` example applies exactly one legal one-locus change. The
caller supplies the immutable parent, finite legal catalogue, complete positive
mutation distribution, and explicit draw. The app canonicalizes unordered
support, asks Metering for distribution entropy and selected-outcome
self-information, and returns content-derived catalogue, parent, child, and
transition identifiers. It contains no hidden randomness, assay, selection,
lineage, repetition, or mutation-policy update.

The `apps/selection_gate` example verifies two complete Forecast Assay reports
on the same identified evidence, recomputes their target self-information and
means, and applies one caller-supplied strict improvement threshold. The
retention decision belongs to that application, not to Metering. Candidate
labels remain opaque assay identifiers: an external controller must bind them
to the exact incumbent and challenger content identities that it executed.
The gate does not prove model execution, forecast precommitment, inheritance,
or future improvement.

Application JSONL transports use standard input and output only. Recoverable
line errors produce an aligned JSON response and leave later requests usable.
They do not change Metering's installed one-request JSON command.

Applications must not add a generic score or describe a measured quantity as
meaning, usefulness, correctness, understanding, or universal harness quality.
They use the same public Python or JSON interface as any external caller. A
demonstration must not rely on private package modules.

## Permanent package non-goals

The installed Metering package does not contain:

- agents, models, prompts, memories, tools that choose other tools, or model
  adapters;
- policies, planners, search strategies, optimizers, rankings, or scores;
- worlds, tasks, repairs, verification, correctness, budgets, or resource
  accounting;
- posterior construction, Bayesian inference, probability estimation, sample
  binning, smoothing, or normalization;
- generic traces, experiment runners, manifests, commitments, replay engines,
  databases, dashboards, or artifact stores beyond the fixed measurement-pair
  ledger;
- continuous or differential entropy, entropy-rate estimators, channel
  capacity optimization, or learned estimators;
- claims about meaning, relevance, understanding, reasoning, knowledge, or
  intelligence.

Repository-local applications are examples, not additional Metering features.
They are excluded from the public API and wheel package.

## Repository layout

```text
src/metering/
    __init__.py       exact public Python surface
    information.py    validation and four pure measures
    __main__.py       strict JSON standard-stream adapter
    history.py        explicit content-addressed measurement ledger
tests/
    test_information.py
    test_cli.py
    test_history.py
    test_public_api.py
    test_observer.py
    test_forecast_assay.py
    test_mutator.py
    test_selection_gate.py
    test_evolution_kernel.py
docs/
    theory.md
    evolution-kernel.md
apps/
    README.md         application index and composition boundary
    observer/         non-packaged versioned-sandbox demonstration
    forecast_assay/   non-packaged agent candidate-measurement adapter
    mutator/          non-packaged one-locus variation operator
    selection_gate/   non-packaged verified pairwise retention decision
```

Add a module only when a concrete responsibility no longer fits one of these
three. Do not introduce a generic abstraction in anticipation of future work.

## Compatibility

This scope reset intentionally removes the previous hidden-fault world,
actions, policies, controller, calibration, reports, general trace/replay
system, artifact schemas, and their CLI commands. Existing run artifacts remain
usable only with a checkout of the historical implementation that created them.

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
- the history CLI records only accepted pairs, distinguishes pair identity from
  lineage identity, and detects corrupt or unreachable objects;
- direct calls and CLI calls agree for the same inputs;
- the core performs no filesystem or network access, does not modify input
  containers, and documents consumption of one-shot iterators;
- the package has no runtime dependency;
- no legacy world, policy, controller, agent, optimizer, benchmark, replay, or
  artifact implementation remains in the installed `metering` package;
- repository-local applications use only public Metering boundaries, make
  their caller-owned probability model explicit, and keep JSONL requests
  sequential with one flushed response per input line;
- the Mutator changes exactly one legal locus, uses an explicit caller-owned
  draw, and reports Metering entropy and selected-mutation self-information;
- Forecast Assay rejects unsupported schema versions and Selection Gate requires
  that same report version before recomputing both reports, rejecting mismatched
  evidence, and applying its documented strict threshold and infinity ordering;
- the composed evolution-kernel example carries Mutator content IDs through
  Forecast Assay and Selection Gate without treating an opaque label as proof
  of candidate execution;
- the full test suite and package build pass.

## Source

Claude E. Shannon, “A Mathematical Theory of Communication,” *The Bell System
Technical Journal*, volume 27, pages 379-423 and 623-656, 1948.

- https://doi.org/10.1002/j.1538-7305.1948.tb01338.x
- https://doi.org/10.1002/j.1538-7305.1948.tb00917.x
