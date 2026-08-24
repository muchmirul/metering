# Mutator architecture

## Purpose

The Mutator is the variation boundary in a directed-evolution-inspired software
loop. Its only state transition is:

```text
one immutable parent genome -> one immutable child genome
```

The caller supplies every modeling decision: the legal mutation catalogue, the
probability assigned to each supported mutation, and the draw used to select one
outcome. The process contains no hidden randomness.

## Irreducible responsibilities

1. Decode one strict versioned request.
2. Validate a finite catalogue of loci and legal alleles.
3. Validate that the parent contains exactly those loci and legal values.
4. Validate a positive, normalized distribution over legal one-locus changes.
5. Canonicalize semantically unordered catalogue and support data.
6. Ask Metering for mutation-distribution entropy and selected-mutation
   self-information.
7. Apply exactly one selected change and return content identities.

Removing catalogue validation would permit malformed or undefined children.
Removing the explicit distribution would hide the mutation policy. Removing the
draw would add implicit process randomness. Removing identity would make
inheritance and replay ambiguous. None of these responsibilities requires an
agent runner or optimizer.

## Representation boundary

Version 1 uses `flat-json-atoms-v1`:

```json
{
  "max_steps": 8,
  "planner": "react-v1",
  "tool_policy": "evidence-first-v3"
}
```

A genome is a non-empty mapping from catalogue locus names to JSON atoms. The
allowed atoms are:

```text
non-empty UTF-8 string
safe JSON integer in [-(2^53-1), 2^53-1]
Boolean
null
```

Nested objects, arrays, and floating-point genes are absent. A future
representation should be a new explicit schema, not an unnoticed widening of
version 1.

## Mutation model

Each support entry is:

```text
(locus, replacement allele, probability)
```

The replacement must differ from the parent allele. Different support entries
therefore identify different one-step children. Support entries are sorted by
locus and canonical allele encoding before cumulative selection. The draw must
satisfy `0 <= draw < 1`.

Metering accepts normalized distributions within its documented absolute
tolerance. The Mutator still does not assign an uncovered tail to the last
mutation. If the supplied draw lies beyond the declared cumulative mass, the
request fails explicitly.

## Identity

Content identity and evolutionary history remain separate:

```text
catalogue_id = SHA-256(canonical normalized catalogue document)

candidate_id = SHA-256(
    schema version,
    genome schema,
    canonical genome
)

mutation_id = SHA-256(
    schema version,
    catalogue_id,
    parent candidate_id,
    locus,
    before,
    after
)
```

`candidate_id` identifies content. `mutation_id` identifies one declared
parent-to-child transition. Neither is a signature, author identity, lineage
record, or proof that trusted software produced the document.

A later evolution controller may store parent links and promotion decisions in
a separate candidate lineage. Metering history is not that lineage; it stores
measurement request/response pairs.

## Dependency direction

```text
external controller -> apps/mutator -> public Metering Python API
```

The Mutator imports only `entropy`, `self_information`, and `ProbabilityError`
from the public package. It performs no filesystem access and no network access.

## Deliberately absent

There is no model execution, prompt editing, arbitrary source rewriting,
recombination, population, mutation-policy update, selection, deployment,
persistence, stopping rule, or generation counter. Those are separate
responsibilities and must not be smuggled into this variation boundary.
