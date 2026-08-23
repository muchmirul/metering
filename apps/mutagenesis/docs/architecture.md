# Architecture

## Purpose

Mutagenesis is a one-shot measurement adapter between an external agent and
Metering. It is not an agent and does not implement evolution.

The complete boundary is:

```text
external agent
  owns observations, model, mutation, comparison, loop, and stopping
        |
        | one candidate id and target probabilities
        v
mutagenesis
  validates the envelope, measures each probability, and computes one mean
        |
        v
public Metering Python API
  validates each probability and returns self-information
```

Mutagenesis returns the measurements to the agent and exits. A later call has
no access to an earlier call.

## Irreducible responsibilities

The adapter has five responsibilities:

1. Read one strict JSON request from standard input.
2. Preserve the agent's opaque candidate identifier in the response.
3. Pass each supplied target probability to Metering's public
   `self_information` function at base 2.
4. Report every named result and their arithmetic mean without choosing a
   candidate.
5. Encode errors and positive infinity as valid canonical JSON.

Everything else remains outside the boundary. In particular, the adapter does
not know what was observed, what a target means, how a probability was
constructed, or what changed between candidates.

## Why the input is a target probability

The agent supplies the probability assigned to the outcome that actually
occurred or that the agent otherwise declares as its target. The adapter does
not accept a label and a full prediction vector because doing so would make it
responsible for aligning world-specific labels with probability coordinates.

For target probability `p`, the named Metering call is:

```text
self_information(p, base=2) = -log2(p)
```

The list position is the only alignment information retained. The external
agent must keep the corresponding observation identities.

## Aggregation boundary

For `n` finite target surprisals, the adapter reports:

```text
mean_target_surprisal_bits = sum(surprisal_i) / n
```

This arithmetic mean weights every supplied position equally. It is an
application-owned aggregate, not an additional Metering measure and not a
general score. If one target has probability zero, its self-information and
the arithmetic mean are positive infinity.

An agent that needs grouping, weighting, train/test separation, statistical
estimation, or another comparison rule must implement that policy itself.

## State and dependency direction

The process has no state beyond one request:

```text
external agent -> apps/mutagenesis -> public metering API
```

There are no application files, checkpoints, sessions, caches, network calls,
private Metering imports, or caller-container mutations.

## Deliberately absent

The adapter does not contain a neural architecture, environment, observation
function, mutation generator, optimizer, selector, acceptance threshold,
generation counter, memory, persistence, concurrency protocol, or stopping
condition. Adding any of those would move an agent-owned decision into this
measurement boundary.
