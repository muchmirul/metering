# Metering

Metering is a small deterministic Python package for information measures over
finite discrete probability distributions.

The installed package exposes exactly:

- self-information;
- Shannon entropy;
- Kullback–Leibler divergence;
- mutual information;
- strict JSON access to those measures; and
- optional Git-backed measurement history.

It does **not** infer probabilities, assign a generic fitness or intelligence
score, run agents, or deploy code. Population evolution, sandboxing, and
**Agentvolve** are repository-local source applications kept outside the wheel.

## Install

Metering requires Python 3.11 or newer and has no Python runtime dependencies.
From a checkout using [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync --extra test
```

## Measure information

```python
from metering import entropy, kl_divergence, mutual_information, self_information

print(self_information(0.125))
print(entropy([0.5, 0.5]))
print(kl_divergence([0.5, 0.5], [0.75, 0.25]))
print(mutual_information([[0.5, 0.0], [0.0, 0.5]]))
```

```text
3.0
1.0
0.2075187496394219
1.0
```

Base 2 is the default. Inputs must already be normalized probability models;
invalid distributions, booleans, NaN, infinity, and unsupported bases are
rejected rather than corrected silently. See the
[measurement theory](docs/theory.md) for equations and numerical conventions.

### Strict JSON command

```bash
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering
```

```json
{"base":2.0,"infinite":false,"measure":"entropy","value":1.0}
```

The command accepts one request on standard input and emits one JSON response.
It rejects unknown fields, duplicate keys, command-line payloads, and malformed
probability models.

## Optional measurement history

`metering-history` records successful requests and exact results in a dedicated
first-parent Git history:

```bash
history_dir="$(mktemp -d)"
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering-history record "$history_dir"

uv run metering-history log "$history_dir"
uv run metering-history verify "$history_dir"
```

History is opt-in and requires Git. See the
[measurement-history contract](docs/history.md).

## Agentvolve

**Agentvolve** is the source checkout's bounded two-level coding evolution
system:

```text
Level 2 evolves and seals the coding harness
              ↓
Level 1 uses that frozen harness to evolve solution commits
              ↓
Independent protected checks produce a reviewable commit and patch
```

Its operator-facing tracker is:

```text
[1/6] Task and runtime configured
[2/6] Evolving harness
[3/6] Harness sealed
[4/6] Evolving solution
[5/6] Protected final assay
[6/6] Result ready for review
```

The tracker is only a status projection. Git candidates, hash-linked JSONL,
exact allocations, and content-addressed receipts remain authoritative.
Level-1 task profiles can use a numeric round limit alone or stop earlier when
independent development evidence proves a worded goal; the finite round limit
always remains mandatory.

### Use from Pi

Register the reviewed `.pi/extensions/population-evolution.ts` entrypoint. The
extension exposes exactly four Agentvolve commands:

```text
/limit 10
/goal Fix the behavior described here and satisfy the reviewed checks
/history [RUN_NAME]
/progress
```

`/goal` asks for a limit if none is saved, offers a reviewed current-repository
contract or a new user-message-only draft, and requires direct task approval
before launching. Review includes paths, checks, budgets, stopping, and final
policy; JSON is only an optional advanced correction surface. Cancelling starts
nothing. The last `/limit` (1–256 generations) persists for later tasks and session
restores; it never changes an already running task. A successful launch clears
the pending goal, not the limit.

Task review shows development timeout reservations, not elapsed runtime: one
120-second check currently requires **3,680 reserved seconds per generation**
(**7,360 for two**, without retries). An insufficient budget prompts for an
operator-entered correction before approval; cancellation starts nothing. Fixed
preflight rejects budgets that cannot fund even one generation. Partially funded
caps are allowed and disclosed. Existing budgets are never increased in place.

Conversation still works: ask to activate Agentvolve (starts no task), clarify a
coding goal, and explicitly ask it to solve it. Pi keeps its current model while
a separate detached worker uses the canonical runtime's provider/model/reasoning
and finite budgets. Pi remains usable while evolution continues.

You can also say **“manage the interrupted Agentvolve workflow”** to resume,
authorize a reserved retry, stop, or close an inactive workflow as incomplete.
The session asks you to select the run and approve the operation; no terminal
command is required. `/goal` offers the same recovery when a current workflow
blocks startup. Closing preserves all evidence and history but permanently ends
that workflow without claiming success. Old unmanaged legacy runs remain visible
in `/history` and no longer block a separately reviewed new goal; no directory
switching, deletion, automatic retry, or evidence migration is needed.

`/progress` inspects the latest run, including a completed run. `/history` browses
all runs in pages of 50 and every recorded harness/solution generation in pages
of 20, with stage reports and results. Reused harness evidence is labelled, not
counted as new work. The dashboard refreshes every two seconds; `[`/`]` page
traces, arrows/PageUp/PageDown scroll, `d` expands the bounded diff, and `Esc`/`q`
returns without stopping the worker. Press **t** to browse actual H*/S* candidate
trees and select **any child**, not just the winner: inspect identities, archive
status/reasons, recorded loop steps and public checks, resources, and its paged
historical diff. A loops/attempts view includes failed and pending proposals
without inventing child nodes. Unselected candidates do not receive fabricated
protected-final results. See [candidate inspection](docs/coding-agent/inspection.md).
[Pi upgrades](docs/coding-agent/pi-versions.md) no longer require your interactive
Pi to equal the experiment's release: the launcher resolves its exact worker pin
from PATH or an explicitly prepared version cache before starting work. It does
not rewrite old runtimes or promise compatibility with unknown breaking releases.

Press **g** for the optional local [Trace Viewer](docs/coding-agent/trace-viewer.md):
a clickable graph with stable depth/branch labels, real file nodes, exact source
and byte downloads, per-file history/comparisons, archive snapshots, and exports.
Build its local assets once with `npm ci --prefix apps/coding_agent/trace_ui` and
`npm run build --prefix apps/coding_agent/trace_ui`. Git/evidence stay authoritative;
no existing run is migrated or modified. The terminal view remains available.
The compact widget appears only for a
currently queued/running detached workflow and disappears when none is active.

Old `/evolve*`, `/agentvolve*`, and `/view-*` slash commands, the reference Pi
tool, and low-level compatibility tool handlers are removed. Reload Pi with
`/reload` and migrate scripts to the four-command flow and RPC approval. Shared
engines, existing evidence, and explicit worker CLI recovery/verification remain
available; the additive session management and `close` operation are documented
in the [operations guide](docs/coding-agent/operations.md). Reload once to expose
`workflow_manage` to the session model. No run migration is required.

The dashboard and worker status are projections only. Candidate Git objects,
hash-linked ledgers, exact allocations, receipts, and seals remain authoritative.
Equivalent read-only command-line projections are:

```bash
uv run python -m apps.coding_agent.operator_view progress RUNS_DIRECTORY [RUN_NAME]
uv run python -m apps.coding_agent.operator_view history RUNS_DIRECTORY [OFFSET]
uv run python -m apps.coding_agent.operator_view trace RUNS_DIRECTORY RUN_NAME [OFFSET]
```

A completed solution run produces:

- `selected-solution.json` — immutable selected commit identity;
- `selected.patch` — byte-preserving patch verified to reconstruct the selected tree (v2);
- `experiment-report.json` — operator-facing summary; and
- Git, Population, Driver, mutation, evaluation, and final evidence.

The source repository is never changed automatically. Applying, merging,
installing, or deploying the patch is a separate operator decision.

New Level-1 runs preflight public/protected profile structure before inference,
without exposing protected contents. Optional `stdout-json-v1` checks compare
actual output with operator-supplied expected values outside the sandbox;
**legacy argv checks still use exit status, which cannot prove assertions ran**.
Old runs retain legacy replay semantics. Failed Controller attempts now retain
bounded operator diagnostics; ordinary resume still never repeats indeterminate
model calls. See [task contracts](docs/coding-agent/task-profile.md) and
[recovery/compatibility](docs/coding-agent/operations.md). Retention, stopping,
search-budget accounting, and the installed Metering API are unchanged. If
budget stopping leaves no development archive, no final assay is attempted and
the actual stop reason is reported. A usable archive still permits final selection.
Progress also explains historical zero-round budget failures without modifying
their evidence; resuming cannot enlarge a frozen budget.

Read the dedicated [Agentvolve guide](docs/coding-agent/README.md), including
the [component map](docs/coding-agent/components.md),
[simple architecture](docs/coding-agent/how-it-works.md),
[six-stage workflow](docs/coding-agent/workflow.md),
[operations](docs/coding-agent/operations.md),
[goal-or-limit stopping](docs/coding-agent/stopping.md),
[task-profile reference](docs/coding-agent/task-profile.md), and
[architecture and threat model](docs/coding-agent/architecture.md).

## Architecture boundary

| Area | Responsibility |
|---|---|
| `src/metering/` | Installed four-measure API, strict JSON CLI, and opt-in history |
| `apps/` | Source-only Controller, Population, harness, evaluators, and Agentvolve |
| `connectors/` | Fixed Pi and Prime Agent translation |
| `artifacts/` | Generic immutable Git-candidate mechanics |
| Operator | Task meaning, approved checks, final evidence, review, and deployment |

Candidate code runs only in the reviewed container boundary. Live containers
have no network, host checkout, `.git`, Docker socket, credentials, or writable
root. Mutation and authoritative evaluation use separate fresh containers.
SQLite is only a rebuildable query projection; it never controls recurrence or
selection.

Start with the [documentation index](docs/README.md),
[current capability map](docs/capabilities.md), or
[source architecture](docs/source-architecture.md). [`PLAN.md`](PLAN.md) is the
normative implementation contract.

## Development

```bash
uv run --extra lint ruff check .
uv run --extra test pytest -q
uv build
```

For Agentvolve internals, see the [maintenance guide](docs/coding-agent/maintenance.md).
The experiment entrypoints are compatibility dispatchers; configuration, runtime
effects, and independent replay have separate owners. Internal refactoring does
not change command paths, recorded schemas, or require run migration.

Agentvolve workflow changes additionally use the opt-in, three-task local-model
acceptance test documented in `docs/coding-agent/operations.md`; it deploy-loads
the Pi extension, runs each approved task, and offline-verifies every result.
It supports standalone invocation and imports its source-only inspection
modules before launching work, so dependency errors do not waste model calls.

The wheel must contain only the installed `metering` package. Source-only
applications and connectors are distributed through the source archive.
