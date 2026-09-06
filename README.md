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

Register the reviewed `.pi/extensions/population-evolution.ts` entrypoint, then
activate Agentvolve from normal conversation (for example, “activate
Agentvolve”) or with `/agentvolve`. Activation starts no task. Continue talking
to Pi normally, clarify the coding goal when needed, and ask Agentvolve to solve
it. The model-facing adapter prepares a task only from user messages and opens a
direct operator review before registration and launch; canonical JSON remains an
internal advanced-edit surface rather than required conversational input.

The explicit three-command route remains:

```text
/goal Fix the behavior described here and satisfy the registered checks
/limit 100 generations
/agentvolve
```

Pi remains the interactive operator and keeps its current `/model`. With a
complete goal/limit pair, `/agentvolve` derives a canonical profile from a
reviewed task contract and launches a separate detached evolution worker. A
single profile bound to the current folder is automatic; when interactive
selection is required, Pi presents reviewed task summaries instead of requiring
a copied path. That worker uses the canonical runtime's
provider/model/reasoning identity and finite budgets. Launch returns immediately,
so Pi stays usable while evolution continues. Without both values,
`/agentvolve` only activates operator mode and explains both conversational and
slash-command routes.

Advanced explicit starts remain available:

```text
/evolve-start [/absolute/path/to/task.json]
/evolve-task
```

Inspect the current or previous shared workflows from any Pi session:

```text
/view-progress [RUN_NAME]
/view-history
```

The terminal dashboard refreshes every two seconds and distinguishes the
operator model from the detached worker model. It shows all six stages, worker
liveness, committed rounds/attempts/archive, bounded lineage and candidate diff
views, completed-stage reports, and the final commit/patch report. `Esc` or `q`
returns to Pi without stopping the worker.

Recovery and verification remain explicit:

```text
/agentvolve-resume
/agentvolve-retry OPERATOR-REVIEWED-REASON
/agentvolve-stop
/agentvolve-verify
```

Resume never repeats an indeterminate model call; retry is accepted only for a
reserved pending attempt. Existing low-level `/evolve-harness*` and
`/evolve-code*` compatibility commands remain documented in the
[operations guide](docs/coding-agent/operations.md).

The dashboard and worker status are projections only. Candidate Git objects,
hash-linked ledgers, exact allocations, receipts, and seals remain authoritative.
Equivalent read-only command-line projections are:

```bash
uv run python -m apps.coding_agent.operator_view progress RUNS_DIRECTORY [RUN_NAME]
uv run python -m apps.coding_agent.operator_view history RUNS_DIRECTORY
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
search-budget accounting, and the installed Metering API are unchanged.

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

The wheel must contain only the installed `metering` package. Source-only
applications and connectors are distributed through the source archive.
