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
4. Choose numeric or evaluator-backed goal stopping in the [stopping-policy
   guide](stopping.md).
5. Prepare the runtime and task using the [task-profile reference](task-profile.md).
6. Follow the [operations guide](operations.md).
7. Review the [architecture and threat model](architecture.md) before a live
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

In an extension-enabled Pi session, the operator may say “activate Agentvolve”,
then describe and clarify a coding goal in ordinary conversation. Activation
starts no task. The four commands are `/goal`, `/limit`, `/history`, and
`/progress`. Set `/limit N`, then submit `/goal PROBLEM`; `/goal` asks for a limit
if missing and requires direct approval of the task's paths, checks, budgets,
and policies before launching. The last limit persists for future tasks. Pi can
also prepare a reviewed canonical task from user-only session messages after an
explicit conversational solve request.
There is no model picker: Pi keeps its normal interactive `/model` and starts a
separate detached worker whose identity and budgets remain pinned to the
canonical runtime manifest. Launch returns immediately. While operator mode is
active, the monitor polls the shared run directory across sessions; its compact
`[1/6]`–`[6/6]` widget appears only while a detached workflow is queued or
running and clears when no worker is active. `/progress` inspects the latest
run, including a finished run; `/history` browses past runs, all recorded
generations in bounded pages, completed-stage reports, and results. Operators do not choose between internal
harness and solution levels. The worker status, tracker, graph, diff preview,
and reports are convenience projections. Candidate Git objects, canonical
hash-linked JSONL, exact allocations, and content-addressed receipts remain the
authoritative evidence. Level-1 recurrence can stop at a numeric round cap or at
an independently evaluated development goal with that cap as a mandatory
fallback.

## Empirical evidence

The [2026-09-05 Qwen3.8 maze study](maze-study-2026-09-05.md) records six
correctly configured, independently checked Level-1 runs under an existing
verified harness. Three rounds did not improve accuracy over one round. The
report also preserves the failed fresh Level-2 attempt and the initial
benchmark configuration errors; it does not establish equal-compute superiority.

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
The implementation directory, `darwinian_coding` tool, and `darwinian-coding-*`
schema identifiers retain their names for recorded-run compatibility. Legacy
slash commands and low-level Pi tool handlers are removed, not the shared
engine or its explicit CLI recovery and verification.
