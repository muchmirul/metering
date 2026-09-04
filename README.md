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

Prepare the reviewed digest-pinned Docker runtime. To register Agentvolve from
any Pi working directory, add its reviewed absolute entrypoint to
`~/.pi/agent/settings.json` without removing existing settings:

```json
{"extensions":["/absolute/path/to/metering/.pi/extensions/population-evolution.ts"]}
```

Start or reload Pi, then open the primary UI:

```text
/agentvolve
```

The launcher first offers **Local model** and **Routed Pi model** modes. Local
mode activates the configured Qwen/llama.cpp service and selects the canonical
runtime model in the outer Pi session. Routed mode keeps the model Pi was
already using. Both open one streamlined UI with **Start workflow**, **Refresh
status**, **Browse workflow history**, **Resume**, **Retry**, and **Verify**.
Every Pi session polls the shared run directory, so progress started in another
session appears automatically. The status widget is always visible and
explicitly lists every stage from `[1/6]` through `[6/6]`, including completed,
current, and pending markers. `/agentvolve-history` opens the same shared history
browser directly. Starting the workflow asks once for the
task profile, reuses a sealed harness when available (or creates one when none
exists), and continues through the solution and protected final assay. Evolution
itself remains pinned to the canonical runtime manifest; routed UI mode does not
silently change experiment identity. Existing direct compatibility commands
remain available:

```text
/evolve-harness
/evolve-harness-status
/evolve-code /absolute/path/to/task.json
/evolve-code-status
/evolve-code-verify
```

If execution is interrupted, ordinary resume never repeats an indeterminate
model call:

```text
/evolve-harness-resume
/evolve-code-resume
```

Use `/evolve-harness-retry REASON` or `/evolve-code-retry REASON` only when the
run explicitly requires an operator-approved retry and reserved budget remains.

Each new run writes canonical `process-status.json`. The equivalent command-line
status checks are:

```bash
uv run python apps/harness/experiment.py status HARNESS_RUN_ROOT
uv run python apps/coding_agent/solution_experiment.py status SOLUTION_RUN_ROOT
```

A completed solution run produces:

- `selected-solution.json` — immutable selected commit identity;
- `selected.patch` — binary-capable patch from the approved base;
- `experiment-report.json` — operator-facing summary; and
- Git, Population, Driver, mutation, evaluation, and final evidence.

The source repository is never changed automatically. Applying, merging,
installing, or deploying the patch is a separate operator decision.

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

The wheel must contain only the installed `metering` package. Source-only
applications and connectors are distributed through the source archive.
