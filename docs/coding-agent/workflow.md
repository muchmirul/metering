# Six-stage Agentvolve process

This is Agentvolve's operator-facing lifecycle. The `/agentvolve` UI presents
one streamlined workflow and deliberately hides the internal harness/solution,
Controller, Population, Git, and receipt boundaries. Its widget remains visible
and lists all six stages at all times.

## Tracker

| Stage | Meaning | Typical command or evidence |
|---|---|---|
| **[1/6] Task and runtime configured** | The pinned runtime and applicable task contracts validate. | runtime/task profiles and kernel conformance |
| **[2/6] Evolving harness** | Agentvolve proposes one-locus harness descendants and evaluates them on fixed coding workspaces. | **Start Agentvolve workflow** |
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
model work at `[4/6]` after Agentvolve revalidates the earlier stages.

## Viewing status

In interactive Pi the complete tracker is always shown and polls the shared run
directory every two seconds, including work launched by another Pi session. Use
`/agentvolve` and choose **Refresh workflow status** for an explicit refresh or
**Browse workflow history** to inspect recent runs. `/agentvolve-history` opens
the history browser directly. The direct `/evolve-harness-status` and
`/evolve-code-status` commands remain compatibility interfaces.

From the command line:

```bash
uv run python apps/harness/experiment.py status HARNESS_RUN_ROOT
uv run python apps/coding_agent/solution_experiment.py status SOLUTION_RUN_ROOT
```

New runs also contain canonical `process-status.json`:

```json
{"authority":"projection-only","display":"[4/6] Evolving solution","process_schema":"darwinian-coding-process-v1","run_kind":"solution","stage":4,"stage_label":"Evolving solution","total_stages":6}
```

Pi polls this file while a command is running, so the status line and widget can
advance without exposing internal model prompts or protected-final content.

## Authority boundary

The tracker is a convenience projection, not experimental authority. It cannot:

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
