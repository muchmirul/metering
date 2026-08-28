# Mutator architecture

## Purpose

The Mutator is the variation boundary in a directed-evolution-inspired software
loop. It supports two explicit state transitions:

```text
schema 1: immutable parent genome -> one legal child genome
schema 2: immutable parent artifact -> one bound challenger artifact
```

For schema version 1, the caller supplies the legal mutation catalogue, the
probability assigned to each supported mutation, and the draw used to select one
outcome. Schema version 2 either binds a direct challenger or invokes one strict
external proposer. Neither path contains hidden randomness or retention policy.

`mutator.py` owns command dispatch and schema-version-1 genome mutation.
`agent_mutation.py` owns schema-version-2 direct/proposer artifact mutation.
The split changes no command, schema, or output.

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
catalogue_id = SHA-256(canonical JSON of {
    "catalogue": normalized catalogue document,
    "genome_schema": "flat-json-atoms-v1",
    "schema_version": 1
})

candidate_id = SHA-256(canonical JSON of {
    "genome": canonical genome,
    "genome_schema": "flat-json-atoms-v1",
    "schema_version": 1
})

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

Evolution Controller returns one selected `next_parent` but does not store a
lineage. A caller may store parent links and promotion decisions separately.
Metering history is not that lineage; it stores measurement request/response
pairs.

## Dependency direction

```text
external controller -> mutator.py -> schema-specific mutation
                                  -> public Metering Python API
                                  -> optional external proposer command
```

Schema version 1 imports only `entropy`, `self_information`, and
`ProbabilityError` from the public package and performs no filesystem or network
access. Schema version 2 uses shared source-only artifact validation and may call
the explicitly supplied proposer; that subprocess owns any external effects.

## Deliberately absent

There is no model execution, prompt editing, arbitrary source rewriting,
recombination, population, mutation-policy update, selection, deployment,
persistence, stopping rule, or generation counter. Those are separate
responsibilities and must not be smuggled into this variation boundary.
