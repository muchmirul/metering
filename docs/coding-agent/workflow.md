# Six-stage Agentvolve process

This is Agentvolve's operator-facing lifecycle. Ordinary Pi slash commands start
one streamlined detached workflow while hiding the internal harness/solution,
Controller, Population, Git, and receipt boundaries. While a detached worker is
queued or running, the compact widget lists all six stages without owning the
worker. `/progress` also inspects the latest run after completion.

## Tracker

| Stage | Meaning | Typical command or evidence |
|---|---|---|
| **[1/6] Task and runtime configured** | The pinned runtime and applicable task contracts validate. | reviewed session task, or `/goal …`, `/limit N generations`, and a discovered profile |
| **[2/6] Evolving harness** | Agentvolve proposes one-locus harness descendants and evaluates them on fixed coding workspaces. | detached worker after approved `/goal` |
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

A previously sealed harness can be reused, so later tasks commonly begin new
model work at `[4/6]` after Agentvolve revalidates the earlier stages. The
operator may activate Agentvolve conversationally, describe a clear coding goal,
and approve the human-readable task review in-session; fixed code then registers
the same canonical profile before the tracker advances. The explicit
`/limit N generations`, then `/goal …` route needs no additional start command.
A missing limit is prompted and the last limit persists for future tasks.
Discovered folder-bound contracts require direct selection; new drafts and
selected contracts both require approval in TUI and RPC. If the current folder cannot supply a reviewed executable task
contract or a valid reviewed session draft, Agentvolve remains in operator mode
and asks for clarification rather than treating prose as proof. A reviewed
`METERING_EVOLUTION_HARNESS_DESCRIPTOR` can reference an original sealed harness
when the new solution run uses an isolated registry; provenance remains bound to
that original run.

## Viewing status

Mode activation has no pre-start menu and starts no worker. A reviewed task may
open the clarification, task-summary selection, or approval interaction
needed to bind the canonical input. A blocking detached workflow first opens a
directly approved recovery/close dialog. Unmanaged legacy runs stay in history
without blocking a new task; they are never automatically resumed. `/goal` keeps Pi's current operator
model and, once a task is approved, launches a manifest-pinned evolution worker
in a separate process. Pi returns immediately. While operator mode is active,
the compact tracker polls the shared run directory every two seconds, including
work launched by another session. The widget is shown only for a genuinely
queued or running detached workflow and disappears when no worker is active;
abandoned legacy directories are not displayed as current progress.

Use `/progress` for the latest run and `/history [RUN_NAME]` for the shared
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
