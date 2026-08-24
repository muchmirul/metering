# Candidate Runner architecture

## Purpose

Candidate Runner is the execution boundary missing between a Mutator genome and
a Forecast Assay request. Version 1 implements one finite model over the four
Observer fixtures:

```text
Mutator candidate ID + genome + unrevealed probe
                         |
                         v
                 Candidate Runner
                         |
                         v
       complete normalized probe-result forecast
```

The runner receives no active-version argument and no observed result. A
controller must call it before asking Observer to reveal the probe result.
Version 1 is memoryless: every probe forecast is derived from the genome's same
fixed version distribution and does not condition on earlier observations.

## Genome semantics

The genome names one version hypothesis `h` and an integer confidence `c` in
basis points. It defines a probability distribution over versions:

```text
P(V = h) = c / 10000
P(V = v) = (1 - c / 10000) / 3, for every v != h
```

The lower bound `c >= 2500` ensures the named hypothesis is not less probable
than any individual alternative. The upper bound is `10000`.

For a probe `q`, the result distribution is the pushforward of that version
distribution through the fixed fixture model:

```text
P(R = r | q) = sum P(V = v) over versions where result(v, q) = r
```

The implementation passes the complete generated result distribution to
Metering's public `entropy` function. It does not normalize or repair that
distribution after construction.

## Identity binding

Candidate Runner recomputes:

```text
candidate_id = SHA-256(canonical JSON of {
    "genome": genome,
    "genome_schema": "flat-json-atoms-v1",
    "schema_version": 1
})
```

A mismatch fails before execution. This verifies content correspondence with
Mutator; it does not authenticate the caller or executable.

## Fixture-model boundary

The runner contains its own explicit mapping from `v1` through `v4` to the two
fixture file results. It does not read Observer fixtures or the active sandbox
at runtime. The deterministic listing result is also modeled.

Duplicating this small mapping is intentional. Importing Observer internals or
reading its sandbox would collapse the candidate/environment boundary. The
integration tests expose mapping drift against Observer's public JSONL
responses.

## Deliberately absent

There is no arbitrary program execution, plugin interface, model loading,
training, observation, mutation, selection, persistence, randomness, network
access, or claim that entropy measures candidate quality. Supporting another
candidate representation requires a new explicit runner model or schema.
