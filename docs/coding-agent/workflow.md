# Six-stage Agentvolve process

This is Agentvolve's operator-facing lifecycle. Ordinary Pi slash commands start
one streamlined detached workflow while hiding the internal harness/solution,
Controller, Population, Git, and receipt boundaries. While a detached worker is
queued or running, the compact widget lists all six stages without owning the
worker. `/progress` inspects this session's exact submission, including completion
or failure to launch, never the newest registry run.

## Tracker

| Stage | Meaning | Typical command or evidence |
|---|---|---|
| **[1/6] Task and runtime configured** | The pinned runtime and applicable task contracts validate. | reviewed session task, or `/goal …`, `/limit N generations`, and a discovered profile |
| **[2/6] Evolving harness** | Separately approved Level-2 setup; new Pi solution jobs reuse a compatible verified seal. | explicit Level-2 CLI setup, not implicit `/goal` cost |
| **[3/6] Harness sealed** | One harness has been allocated, protected-final tested, and permanently sealed. | `selected-harness.json` |
| **[4/6] Evolving solution** | The frozen harness creates and independently tests immutable solution commits until a verified goal or finite limit stops recurrence. | automatic workflow continuation |
| **[5/6] Protected final assay** | Development has stopped, final allocation is committed, and protected checks are running. | final-role Population records |
| **[6/6] Result ready for review** | The selected commit, patch, and replayable evidence are ready for operator verification. | `selected-solution.json` and `selected.patch` |

The normal transition is:

```text
[1/6] configure
   → [2/6] evolve harness
   → [3/6] seal harness
   → [4/6] evolve solution
   → [5/6] protected final
   → [6/6] review result
```

New Pi solution jobs require an explicitly selected compatible verified sealed
harness, so new model work begins at `[4/6]`; earlier stages are labelled reused.
No newest-harness guess or implicit Level-2 setup cost is accepted. Describe the
goal, review worker runtime/configuration/harness identity separately from Pi's
interactive drafting model, and approve the task contract. /limit saves only a
suggestion: every /goal asks for the exact per-job generation cap. Discovered
contracts require selection; all starts require direct TUI/RPC approval. Missing
facts, configuration or valid checks produce a job-scoped failure/clarification,
never restrictions on ordinary Pi tools. A reviewed
`METERING_EVOLUTION_HARNESS_DESCRIPTOR` can reference an original sealed harness
when the new solution run uses an isolated registry; provenance remains bound to
that original run.

## Viewing status

Agentvolve is a delegated job, not a mode of interactive Pi. Activation and
restoration are removed; historical mode output never restricts normal tools.
See [job ownership and migration](operations.md#delegated-jobs-and-reload-migration).
A reviewed task may
open the clarification, task-summary selection, or approval interaction
needed to bind the canonical input. A blocking detached workflow first opens a
directly approved recovery/close dialog. Unmanaged legacy runs stay in history
without blocking a new task; they are never automatically resumed. `/goal` keeps Pi's current operator
model and, once a task is approved, launches a manifest-pinned evolution worker
in a separate process. Pi returns after detachment. The compact tracker polls only
the exact bound workflow every two seconds. Its widget appears only while that
job is queued/running; other sessions' work cannot replace it. Job changes and
shutdown invalidate in-flight output without stopping workers. Reload/resume
follows the owned job without restarting; forks do not inherit ownership.

Use `/progress` for this submission and `/history [RUN_NAME]` for the shared
history browser. Runs page in groups of 50; every recorded harness/solution
generation is accessible in pages of 20 with `[`/`]`. Reused harness evidence is
labelled. The dashboard separates operator/worker identities, shows committed
rounds, attempts, retries, archive evidence, completed-stage summaries, and the
final commit/patch report. Diff previews remain bounded. Scroll with arrows or
PageUp/PageDown; `Esc`/`q` returns to Pi without stopping the worker. Old slash
commands are removed; conversational `workflow_manage` supplies reviewed recovery,
stop, verification, and closure as incomplete through the fixed worker CLI.
Press **t** for [candidate trees and per-child reports](inspection.md), including
recorded loop steps, excluded candidates, historical diffs, and failed/pending
attempts. Archive membership and final testing remain distinct from pairwise
selection; no unrecorded assay outcomes are invented. The optional graphical
[Trace Viewer](trace-viewer.md), opened with **g**, adds real file nodes and exact
file-version tracing. It is a separate read-only viewer, not an evolution action.

Read the same projection without Pi:

```bash
uv run python -m apps.coding_agent.operator_view progress RUNS_DIRECTORY [RUN_NAME]
uv run python -m apps.coding_agent.operator_view history RUNS_DIRECTORY [OFFSET]
uv run python -m apps.coding_agent.operator_view trace RUNS_DIRECTORY RUN_NAME [OFFSET]
```

Detached workflows contain canonical `workflow.json`, ordinal jobs, and a held
`worker.lock`. An explicitly closed inactive workflow adds `closed.json`, an
orchestration-only closure that prevents reopening without pretending it completed.
Existing experimental files remain untouched. `worker-status.json` and
`workflow-report.json` are projection/orchestration records. Each underlying run also contains canonical
`process-status.json`:

```json
{"authority":"projection-only","display":"[4/6] Evolving solution","process_schema":"darwinian-coding-process-v1","run_kind":"solution","stage":4,"stage_label":"Evolving solution","total_stages":6}
```

The worker and operator view combine these projections with authoritative
ledgers and receipts, so status can advance without exposing internal model
prompts or protected-final content.

## Authority boundary

The tracker, worker status, graph, diff preview, and reports are convenience
projections, not experimental authority. They cannot:

- authorize a model call or retry;
- select or allocate a candidate;
- open protected-final content;
- seal or resume Population;
- prove that a result is correct.

Those decisions remain in immutable Git candidates, hash-linked Driver and
Population JSONL, exact allocations, and content-addressed receipts. Deleting
`process-status.json` does not affect offline verification; status for an older
or tracker-free run is derived from existing run markers.

## Interruption states

- A development interruption remains at `[2/6]` or `[4/6]`.
- Ordinary `resume` completes only replayable committed effects and does not
  repeat an indeterminate model call.
- An explicit operator-approved retry remains in the same stage.
- Once `[5/6]` begins, protected evidence cannot restart development.
- `[6/6]` means output is ready for review, not that it was automatically
  applied, merged, installed, or deployed.

For configuration and commands, see the [task-profile reference](task-profile.md),
[stopping-policy guide](stopping.md), and [operations guide](operations.md). For
trust and evidence semantics, see the
[architecture and threat model](architecture.md).
