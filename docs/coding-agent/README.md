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

Agentvolve is a delegated job using isolated noninteractive Pi calls, not a
session mode. Ordinary configured tools remain available at all times; excluded
tools stay excluded. Activation/deactivation and mode restoration are removed.
Reload once: historical active-mode output is never current restriction.
See [job and migration semantics](operations.md#delegated-jobs-and-reload-migration).
Clarify a coding goal in ordinary conversation. The four commands remain `/goal`,
`/limit`, `/history`, and `/progress`. /limit saves a suggested cap; every /goal asks
for the exact directly approved cap for that job. Casual sessions need no
repository/path input. Messy
requests become organized requirements, explicit assumptions, and proposed checks
for direct review. It resolves referenced files and known project names, inspects
actual bounded source snapshots, and binds their provenance/content and read-only
permissions into the reviewed task. Source instructions are never executed.
Malformed drafting output offers correction/cancellation rather than a raw JSON
error. See [source limits](task-profile.md#source-grounded-preparation).
It proposes an existing project when available; otherwise,
approval creates a private Git seed with TASK.md and empty output files before
launching the detached workflow. Existing projects need a clean committed HEAD
and are never initialized/committed automatically. Task review selects the
destination; declining offers an optional change. The suggested limit and existing-project
selection persist; unrelated later casual tasks get fresh workspaces. Pi's cwd
does not change, and essential missing facts are clarified rather than invented. Pi can
also prepare a reviewed canonical task from user messages and inspected sources after an
explicit conversational solve request.
There is no model picker: Pi keeps its normal interactive `/model` and starts a
separate detached worker whose identity and budgets remain pinned to the
canonical runtime manifest. Review shows the distinct interactive drafting model
and worker Pi/version/provider/configuration/runtime/harness identities. An explicit
compatible verified harness, separate worker configuration and a private 0700 run
registry are required. Say “configure Agentvolve” to select existing setup in this session; `/goal` offers the
dialog when defaults are absent. No exports, second interactive Pi or restart is
needed. Selection starts no job and affects future approvals only. New jobs own
private models/auth file copies and a bound command; recovery ignores changed
session configuration. The run registry defaults to
`~/.local/share/metering/agentvolve-runs` and permission-incapable mounts fail before workflow creation. No newest-harness guess, implicit Level-2 setup or model-service restart is allowed.
See [setup and operational risks](operations.md). Launch returns after detachment.
The compact `[1/6]`–`[6/6]` widget follows only the bound queued/running job.
/progress and verification follow the exact submission, including failure to launch;
newer unrelated runs and older results never replace it. Reload/resume does not
restart work; forks do not inherit ownership. /history selection never rebinds it.
`/history` browses past runs, all recorded
generations in bounded pages, completed-stage reports, and results. Operators do not choose between internal
harness and solution levels. Say “manage the interrupted Agentvolve workflow”
for directly approved resume, reserved retry, stop, verification, or permanent
closure as incomplete. New goals offer that recovery dialog for blocking detached
workflows; unmanaged legacy history no longer blocks new startup. Closure preserves
existing evidence and does not claim success. See [recovery](operations.md#status-resume-and-retry). The worker status, tracker, graph, diff preview,
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

Applying the patch is always a separate operator action. Every candidate—not
only the selected result—has a read-only report in the [tree/loop browser](inspection.md).
Press **t** from `/progress` or a selected `/history` run to inspect H*/S* ancestry,
archive outcomes, public check results, attempts, and historical changes.
See [Pi upgrades](pi-versions.md) to keep interactive Pi updates separate from
exact, reproducible experiment versions.
For a clickable, file-aware graph, press **g** for [Trace Viewer](trace-viewer.md).
It adds S1a/S1b-style branch labels, exact Git source/byte inspection, per-file
history and comparisons, and exports while preserving the original evidence.

The implementation lives in [`apps/coding_agent/`](../../apps/coding_agent/README.md),
while Level 2 lives in [`apps/harness/`](../../apps/harness/README.md).
The implementation directory, `darwinian_coding` tool, and `darwinian-coding-*`
schema identifiers retain their names for recorded-run compatibility. Legacy
slash commands and low-level Pi tool handlers are removed, not the shared
engine or its explicit CLI recovery and verification.
