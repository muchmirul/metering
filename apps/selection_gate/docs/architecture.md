# Selection gate architecture

## Purpose

The Selection Gate is the differential-retention boundary between assay and
inheritance. It consumes reports; it does not run the candidates that produced
them.

```text
external controller
    |
    +--> incumbent -> environment -> forecast assay --+
    |                                                 |
    +--> challenger -> environment -> forecast assay -+-> selection gate
                                                          |
                                                          v
                                                one selected identity
```

The external controller may make the selected candidate the next parent. That
inheritance transition is intentionally outside this process.

## Irreducible responsibilities

1. Decode one strict versioned comparison request.
2. Require Forecast Assay report schema version 1, then validate and
   independently recompute both reports.
3. Align evidence by observation identifier and target label.
4. Reject incomparable reports instead of silently pooling or truncating them.
5. Apply one explicit strict improvement threshold.
6. Represent finite and infinite comparisons as valid canonical JSON.
7. Return the selected candidate identity and evidence content ID.

The gate does not merely compare two caller-supplied aggregate numbers. Doing so
would allow changed cases, forged means, or altered outcome values to control
selection.

## Candidate identity trust

Forecast Assay candidate fields are opaque labels. The gate requires the two
labels to differ and preserves the selected label, but it cannot prove which
genome produced a report. In a Mutator composition, the external controller must
set the incumbent and challenger report labels to the exact Mutator
`parent.candidate_id` and `child.candidate_id` values and must execute those
corresponding genomes. Label equality is a controller-checked binding, not a
signature or a guarantee supplied by this gate.

## Evidence identity

The gate constructs:

```text
evidence_id = SHA-256(
    schema version,
    evaluation identifier,
    sorted (observation, target) cases
)
```

This identifies the comparison evidence, not the report bytes, candidate,
environment contents, or evaluation author. Hashes are integrity-oriented
content identifiers, not signatures.

## Verification tolerance

Per-outcome and aggregate values are recomputed using Metering's public
`self_information` function. Serialized finite report values are accepted when
they match the recomputed value within a fixed absolute and relative tolerance
of `1e-12`. This tolerance verifies numerical serialization; it is not used in
the promotion decision.

## State and dependency direction

```text
external controller -> apps/selection_gate -> public Metering Python API
```

Each request is independent. There is no database, filesystem write, network
access, candidate cache, generation counter, or retained incumbent.

## Deliberately absent

There is no tournament, population, Pareto frontier, statistical test, adaptive
threshold, environment weighting, safety policy, deployment, rollback,
mutation-policy update, or lineage HEAD. A caller requiring additional gates
should compose separately named evaluators rather than hiding them in one
aggregate fitness formula.
