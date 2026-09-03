# Agentvolve

**Agentvolve** is Metering's source-only two-level coding evolution system. It
evolves immutable code candidates under finite budgets,
selects only from independently evaluated evidence, runs one protected final
assay, and returns a commit and patch for human review.

It does not modify the source repository, install dependencies from the
network, merge a branch, or deploy a result.

## How it is organized

```text
Level 2: evolve and seal a nine-locus coding harness
                         ↓
Level 1: freeze that harness and evolve repository solution commits
                         ↓
Protected final assay: seal one selected result for review
```

Harness policy and solution code never mutate in the same experiment. Model
sessions, transcripts, IPython state, and temporary files are phenotype, not
heredity. Only validated Git commits reproduce.

## Start here

1. Read the [component map](components.md) for the roles of Git, Pi, the local
   model, llama.cpp, IPython, Docker, Controller, Population, and receipts.
2. Read [how it works](how-it-works.md) for the simple architecture and one-round
   coding flow.
3. Review the [six-stage workflow](workflow.md).
4. Prepare the runtime and task using the [task-profile reference](task-profile.md).
5. Follow the [operations guide](operations.md).
6. Review the [architecture and threat model](architecture.md) before a live
   run.

## Stable user process

```text
[1/6] Task and runtime configured
[2/6] Evolving harness
[3/6] Harness sealed
[4/6] Evolving solution
[5/6] Protected final assay
[6/6] Result ready for review
```

The tracker is a convenience projection. Candidate Git objects, canonical
hash-linked JSONL, exact allocations, and content-addressed receipts remain the
authoritative evidence.

## Result

A completed Level-1 run provides:

- `selected-solution.json` — selected immutable candidate identity;
- `selected.patch` — binary-capable patch from the approved base commit;
- `experiment-report.json` — concise operator summary; and
- the Git, Population, Driver, mutation, evaluation, and final receipts needed
  for offline verification.

Applying the patch is always a separate operator action.

The implementation lives in [`apps/coding_agent/`](../../apps/coding_agent/README.md),
while Level 2 lives in [`apps/harness/`](../../apps/harness/README.md).
The implementation directory, `/evolve-*` commands, `darwinian_coding` tool, and
`darwinian-coding-*` schema identifiers retain their existing names for
compatibility with recorded runs.
