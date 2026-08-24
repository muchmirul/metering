# Architecture

## Purpose

Forecast assay is a stateless probabilistic screening adapter between an
external agent and Metering. Each schema version 1 request is one complete
assay; the optional JSONL transport can carry multiple independent requests
through one process. It is the assay step in a possible
directed-evolution-inspired external loop. It is not an agent, does not mutate
anything, and does not implement evolution. The exact analogy and theory are
documented in [Biological and mathematical foundations](foundations.md).

The complete boundary is:

```text
external agent
  owns normalized pre-reveal forecasts, observations, mutation, comparison,
  train/test separation, loop, and stopping
        |
        | one candidate, one fixed evaluation, and identified target cases
        v
forecast assay
  validates identities, measures each target probability, and computes one mean
        |
        v
public Metering Python API
  validates each probability and returns self-information
```

Forecast assay returns each measurement to the agent. Default mode then exits;
JSONL mode waits for another line. Neither mode gives a later request access to
an earlier request.

## Irreducible responsibilities

The adapter has six responsibilities:

1. Require schema version 1 and read each request as one strict JSON object,
   either to EOF or one per line.
2. Preserve the schema version and opaque candidate, evaluation, observation,
   and target identifiers in the response.
3. Reject duplicate observation identifiers inside one evaluation.
4. Pass each supplied target probability to Metering's public
   `self_information` function at base 2.
5. Report every named result and their arithmetic mean without choosing a
   candidate.
6. Encode errors, Unicode, and positive infinity as valid canonical JSON.

Everything else remains outside the boundary. The identifiers make evidence
auditable, but they are opaque: the adapter still does not know what an
environment, observation, or target means, whether the probability came from a
normalized forecast made before reveal, or what changed between candidates.

## Why the input is a target probability

The agent supplies the probability assigned to the target that occurred. It
must extract that coordinate from a normalized candidate distribution committed
before the target was revealed:

```text
p = q_candidate(target | observation, evaluation)
```

The adapter accepts the opaque target label for evidence identity, but not the
full prediction vector. Validating world-specific labels, normalization, and
forecast timing remains the caller's responsibility.

For target probability `p`, the named Metering call is:

```text
self_information(p, base=2) = -log2(p)
```

Request order is preserved, but position is no longer the only alignment
information. Unique observation identifiers and target labels are echoed so an
agent can establish that candidate reports cover the same evidence.

Separate responses are comparable only when their `evaluation` identifiers and
exact sets of `(observation, target)` pairs match. This adapter reports rather
than performs that comparison. Use one request per environment; otherwise a
pooled average can hide an environment-specific regression.

## Aggregation boundary

For `n` finite target surprisals, the adapter reports:

```text
mean_target_surprisal_bits = sum(surprisal_i) / n
```

This arithmetic mean weights every supplied observation equally, and
`sample_count` makes that denominator explicit. It is empirical mean
logarithmic loss owned by the application, not an additional Metering measure
and not a general score. If one target has probability zero, its
self-information and the arithmetic mean are positive infinity.

An agent that needs cross-environment weighting, train/test separation,
statistical estimation, or another comparison rule must implement that policy
itself. In particular, repeatedly selecting against the same evaluation cases
turns them into development data; the app cannot protect a held-out set.

## State and dependency direction

The application has no state beyond the request currently being processed:

```text
external agent -> apps/forecast_assay -> public metering API
```

There are no application files, checkpoints, persistent sessions, caches,
network calls, private Metering imports, or caller-container mutations. JSONL
transport retains only the input/output stream between requests.

## Deliberately absent

The adapter does not contain a neural architecture, environment, observation
function, mutation generator, optimizer, selector, acceptance threshold,
generation counter, memory, persistence, concurrency protocol, or stopping
condition. Adding any of those would move an agent-owned decision into this
measurement boundary.

## Numeric boundary

JSON decimal tokens are converted to the double precision consumed by
Metering. The parser rejects non-finite and out-of-range values. It also rejects
a conversion that changes exact nonzero to zero or exact not-one to one,
because those changes would turn a finite result into infinity or a positive
result into zero. Other representable inputs are passed to Metering for its
strict probability validation. No clipping or smoothing occurs.
Accepted signed zero is emitted as `0.0` so mathematically identical zero
inputs do not produce distinct response encodings.
