# Mutator agent protocol

This page specifies flat-genome schema version 1. Agent artifact schema version
2, including direct challenger binding and strict proposer invocation, is
specified in the repository-wide
[agent-skill evolution protocol](../../../docs/agent-evolution.md) and uses the
same one-shot and JSONL transports.

## Transport

Default mode reads exactly one UTF-8 JSON object from standard input, writes one
canonical JSON object to standard output, and exits. Errors are canonical JSON
on standard error with exit status 2.

`--jsonl` reads one independent request per line and flushes one response or
error per line. Recoverable line errors do not terminate the stream. The process
retains no candidate state between requests. Per-line errors are returned on
standard output to preserve alignment; end-of-file, including an empty stream,
exits with status 0. Blank lines, multi-line requests, multiple objects on one
line, and invalid UTF-8 lines are recoverable request errors. A fatal input
stream failure writes one canonical error to standard error and exits with
status 2.

`--jsonl` is the only supported argument. Any other argument is an
`invalid_request` error on standard error with exit status 2.

## Version 1 request

```json
{
  "schema_version": 1,
  "catalogue": {
    "loci": [
      {
        "locus": "planner",
        "alleles": ["react-v1", "plan-execute-v1", "reflect-v1"]
      },
      {
        "locus": "max_steps",
        "alleles": [4, 8, 12]
      }
    ]
  },
  "parent_genome": {
    "planner": "react-v1",
    "max_steps": 8
  },
  "mutation_distribution": [
    {
      "locus": "planner",
      "allele": "plan-execute-v1",
      "probability": 0.5
    },
    {
      "locus": "planner",
      "allele": "reflect-v1",
      "probability": 0.25
    },
    {
      "locus": "max_steps",
      "allele": 12,
      "probability": 0.25
    }
  ],
  "draw": 0.6
}
```

Every object uses exact keys. Duplicate and extra keys are rejected.

### Catalogue

- `loci` is non-empty.
- Each locus name is a unique non-empty string.
- Each locus contains at least two unique legal atoms.
- Atom values are non-empty strings, exact safe integers, Booleans, or null.
- Locus and allele array order has no semantic effect.

### Parent

The parent genome must contain exactly one value for every catalogue locus and
no other key. Every value must be a legal allele for that locus.

### Mutation distribution

Each entry identifies one legal replacement different from the parent value.
Duplicate transitions are rejected. Every probability is strictly positive and
the complete list must satisfy Metering's distribution validation.

The support is canonically sorted by `(locus, canonical allele)` before applying
the draw. The first cumulative interval strictly greater than `draw` is
selected. The app does not normalize the probabilities. A draw outside supplied
cumulative mass fails even if the sum was close enough for Metering's numerical
normalization tolerance.

### Draw

`draw` is a finite JSON number in `[0, 1)`. Conversion may not round a value
below one up to one.

## Response

```json
{
  "schema_version": 1,
  "catalogue_id": "HEX_SHA256",
  "draw": 0.6,
  "parent": {
    "candidate_id": "HEX_SHA256",
    "genome": {
      "max_steps": 8,
      "planner": "react-v1"
    }
  },
  "child": {
    "candidate_id": "HEX_SHA256",
    "genome": {
      "max_steps": 8,
      "planner": "plan-execute-v1"
    }
  },
  "mutation": {
    "mutation_id": "HEX_SHA256",
    "locus": "planner",
    "before": "react-v1",
    "after": "plan-execute-v1",
    "probability": 0.5,
    "surprisal": {
      "base": 2.0,
      "infinite": false,
      "measure": "self_information",
      "value": 1.0
    }
  },
  "mutation_distribution": {
    "support_count": 3,
    "support": ["CANONICALLY_ORDERED_ENTRIES"],
    "entropy": {
      "base": 2.0,
      "infinite": false,
      "measure": "entropy",
      "value": 1.5
    }
  }
}
```

## Errors

```json
{"error":{"code":"invalid_request","message":"..."}}
```

`invalid_request` covers JSON, schema, catalogue, genome, transition, draw, and
transport errors. `invalid_probability` covers a probability model rejected by
Metering. The Mutator does not repair an invalid request. In one-shot mode an
error is written to standard error and exits with status 2. In JSONL mode a
recoverable line error is written to standard output and later lines remain
usable.
