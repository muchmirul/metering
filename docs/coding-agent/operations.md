# Agentvolve operations

## Prerequisites

Live runs require:

- Python 3.11+, Git, Docker, and cgroup v2;
- a reviewed digest-pinned runtime image already present locally;
- a canonical runtime manifest;
- a canonical operator-approved task profile;
- a sealed Level-2 harness selected under the same runtime identity; and
- a pinned Pi/model endpoint.

Ordinary top-level Pi is not sandboxed: its built-in tools, user/global packages,
and extensions run with the host user's permissions. Review or disable ambient
packages and skills, and use a whole-process container or VM when the checkout
itself is untrusted. Candidate isolation begins only inside the fixed Agentvolve workflow.

Candidate containers use `--pull never` and have no network. Project dependencies
and check executables must already be present in the approved image or repository
archive. See the [isolation guide](../../apps/harness/isolation/README.md).

## Level 2: harness

Run the deterministic fixture:

```bash
rm -rf /tmp/metering-coding-harness
uv run python apps/harness/experiment.py \
  coding-fixture /tmp/metering-coding-harness
uv run python apps/harness/experiment.py \
  verify /tmp/metering-coding-harness
```

For a live Pi run:

```bash
uv run python apps/harness/experiment.py \
  coding-pi /absolute/new/harness-run \
  /absolute/path/runtime.pi.json
```

The result is a permanently sealed `selected-harness.json`. Keep the complete
Level-2 run root: Level 1 verifies and records its provenance.

## Level 1: solution

Validate the task before spending model time (optional runtime/harness arguments
also check their identity binding):

```bash
uv run python -m apps.coding_agent.task_profile_tool \
  preflight TASK.json RUNTIME.json SELECTED-HARNESS.json
```

New Level-1 runs also perform this automatically, before conformance or inference.
It checks protected structure privately and exposes no protected contents.
`operator-preflight.json` records diagnostic metadata only. A legacy-check warning
means exit status is the criterion, not proof that assertions ran. Prefer the
explicit [external output contract](task-profile.md#externally-checked-output-values)
when expected answer values are available. Preflight does not run checks or prove
that runtime dependencies or the model endpoint are available.

The deterministic fixture form is:

```bash
rm -rf /tmp/metering-coding-solution
uv run python apps/coding_agent/solution_experiment.py \
  fixture /absolute/path/task.json \
  /tmp/metering-coding-solution \
  apps/harness/profiles/runtime-fixture.json \
  /tmp/metering-coding-harness/selected-harness.json
```

For live Pi, replace `fixture` with `pi`, provide the reviewed live runtime, and
use the descriptor from a `coding-pi` Level-2 run.

The task profile owns recurrence stopping. Set `limits.max_rounds` to a numeric
cap such as 100 and provide 99 allocation draws. To stop earlier on the worded
`goal`, add the versioned `stopping` policy. The [stopping-policy
guide](stopping.md) provides exact examples, statuses, replay semantics, and
game-adapter boundaries.
The wording guides proposals; fixed development checks, not a model completion
claim, determine `development_goal_reached`.

Verify without a model call or SQLite:

```bash
uv run python apps/coding_agent/solution_experiment.py \
  verify /tmp/metering-coding-solution
```

## Status, resume, and retry

```bash
uv run python apps/harness/experiment.py status HARNESS_RUN_ROOT
uv run python apps/coding_agent/solution_experiment.py status SOLUTION_RUN_ROOT

uv run python apps/harness/experiment.py resume HARNESS_RUN_ROOT
uv run python apps/coding_agent/solution_experiment.py resume SOLUTION_RUN_ROOT
```

Ordinary resume handles only replay-authorized committed effects. It never
repeats an indeterminate model call. If a run explicitly requires retry, inspect
the pending intent and use one operator-approved reservation:

```bash
uv run python apps/harness/experiment.py \
  retry HARNESS_RUN_ROOT 'operator-reviewed reason'
uv run python apps/coding_agent/solution_experiment.py \
  retry SOLUTION_RUN_ROOT 'operator-reviewed reason'
```

A retry remains within its current stage and does not reopen protected-final
search. After an interruption before protected copying, resume reuses the already
committed final allocation. After final assay declaration, an indeterminate assay
cannot be replaced by resume or retry.

Failed Controller attempts now identify `state/diagnostics/SHA256.json` in their
pending error. The content-addressed, private diagnostic binds the attempt and
intent, command digest, elapsed time, known exit status, and bounded stderr/detail
excerpts. Terminal controls and common/environment credentials are redacted on a
best-effort basis; treat these files as sensitive operator logs, not public data.
They neither authorize retry nor enter model feedback or cost totals. A timeout,
nonzero exit, and output-limit failure are distinct diagnoses; none implies that
unreceipted inference was free. Existing status/retry policies are unchanged.

## Detached worker protocol

Pi and future coding-agent adapters can use the same fixed CLI/JSON boundary:

```bash
uv run python -m apps.coding_agent.agentvolve_worker \
  start RUNS_DIRECTORY TASK.json RUNTIME.json [SELECTED-HARNESS.json]
uv run python -m apps.coding_agent.agentvolve_worker resume WORKFLOW_ROOT
uv run python -m apps.coding_agent.agentvolve_worker retry WORKFLOW_ROOT 'reviewed reason'
uv run python -m apps.coding_agent.agentvolve_worker stop WORKFLOW_ROOT
uv run python -m apps.coding_agent.agentvolve_worker verify WORKFLOW_ROOT

uv run python -m apps.coding_agent.operator_view progress RUNS_DIRECTORY [RUN_NAME]
uv run python -m apps.coding_agent.operator_view history RUNS_DIRECTORY
```

Each effectful worker command returns one bounded JSON launch response. Progress
and history return one bounded projection document. The Pi start command readies
the fixed local service when its manifest requires one; another adapter must make
that reviewed endpoint ready before calling `start`. Adapters must not infer
experimental authority from either document.

## Interactive Pi commands

Load the reviewed `.pi/extensions/population-evolution.ts` entrypoint from a
trusted checkout, or register its absolute path in Pi's existing extension
settings. Loading it only registers commands; it starts no model, service, or
experiment.

The normal flow uses ordinary slash commands and no launcher menu:

```text
/goal Describe the independently checkable task
/limit 100 generations
/agentvolve
```

The first two commands persist session configuration. With both present,
`/agentvolve` derives a canonical profile from the sole reviewed contract bound
to the current clean Git folder and starts a separate detached worker. Without a
complete pair, `/agentvolve` activates operator mode and returns to Pi with usage
guidance. It never opens a model picker. Pi keeps its current model; use Pi's
normal `/model` command to change the interactive operator.

The evolution worker independently uses the model/provider/reasoning identity
and finite budgets in the canonical runtime manifest. Launch returns
immediately, so the operator can keep chatting, inspect files, or leave the live
dashboard while work continues.

Other explicit starts are:

```text
/evolve-start /absolute/path/task.json
/evolve-start
/evolve-task
```

The argument-free `/evolve-start` requires exactly one discovered task profile
bound to the current folder. Ambiguity fails closed instead of opening a picker.
`/evolve-task` generates from user messages and tracked path names, then requires
editor review and confirmation before registration and launch.

Inspect shared state from this or another Pi session:

```text
/view-progress [RUN_NAME]
/view-history
```

`/view-progress` opens a terminal-native dashboard that refreshes every two
seconds. It labels the operator and worker models separately and shows all six
stages, worker liveness, current activity, committed rounds/attempts/archive,
bounded lineage and candidate diff views, completed-stage reports, and the final
commit/patch report. Press `r` to refresh, `d` to expand/collapse the diff, and
`Esc` or `q` to return to Pi without affecting the worker. `/view-history`
lists up to 50 shared workflow or legacy runs and opens the selected dashboard.
`/agentvolve-history` is a compatibility alias.

Recovery and verification are also explicit slash commands:

```text
/agentvolve-resume
/agentvolve-retry OPERATOR-REVIEWED-REASON
/agentvolve-stop
/agentvolve-verify
/agentvolve-off
```

Resume cannot repeat an indeterminate model call. Retry is accepted only in a
reserved retry state. Stop interrupts the worker and its owned effect rather
than declaring success. Verification runs as a detached offline replay after
completion. A workflow-scoped inherited file lock prevents concurrent workers.

The UI files are projection-only. `workflow.json` and ordinal job records bind
orchestration identity, while `worker-status.json`, `workflow-report.json`, the
dashboard, and stage notices confer no experimental authority. Candidate Git
objects, canonical ledgers, allocations, receipts, and permanent seals remain
authoritative.

The low-level compatibility commands remain available:

```text
/evolve-harness
/evolve-harness-status
/evolve-harness-resume
/evolve-harness-retry REASON
/evolve-code /absolute/path/task.json
/evolve-code-status
/evolve-code-resume
/evolve-code-retry REASON
/evolve-code-verify
```

The model-facing `darwinian_coding` tool supports detached `workflow_start`,
read-only `workflow_status`, and detached `workflow_verify`, plus the existing
harness/solution actions. It cannot choose evaluator commands, candidates,
output paths, task-profile paths, protected checks, or retry authority.

For Pi RPC automation, send `/goal`, `/limit`, and `/agentvolve`; launch still
returns after the worker is detached. The progress/history projections are JSON
and can be read without attaching to that process.

## Run output

A successful solution run contains:

- `selected-solution.json` and `selected.patch`;
- `candidate.git` with immutable seed and child commits;
- canonical Driver and Population ledgers under `state/`;
- mutation, evaluation, conformance, and final receipts;
- copied task, runtime, harness, and harness-provenance documents;
- `operator-preflight.json` (diagnostic-only, without protected contents);
- protected-final content copied only after final allocation is committed;
- `experiment-report.json`; and
- projection-only `process-status.json`.

New selected descriptors use `selected-solution-commit-v2`. Their patches preserve
raw Git bytes, including CRLF, binary content, modes, and missing final newlines.
Publication independently applies the patch to a disposable clone/index and checks
the resulting Git tree. Nothing is applied to the source repository.

The output is evidence, not deployment. Review the patch and receipts before any
separate application or merge.

## What offline verification checks

`verify`:

1. replays Driver and Population ledgers and the permanent seal;
2. binds task, runtime, and harness identities to configuration;
3. checks every harness and solution Git candidate, tree, parent, and allowed
   path;
4. closes the exact mutation/evaluation receipt sets;
5. authenticates fresh-container development and final evidence, treating
   `python`/`python3` spellings as equivalent only when they resolve to the same
   interpreter and exact evaluator script;
6. recomputes capability-first final selection and exact allocation;
7. checks protected-final case coverage and kernel conformance, and re-derives
   output-check outcomes from authenticated stdout and bound expected values; and
8. regenerates `selected.patch`, requires byte equality, and for v2 descriptors
   applies it to a disposable clone/index to require exact selected-tree equality.

V1 evaluation receipts retain exit-status-only semantics. V1 selected descriptors
retain their historical text-transport replay, without the stronger applied-tree
claim. Existing valid runs need no migration. Offline verification never executes
candidate checks/models, publishes artifacts, or updates run status.

The POSIX model transport and nested provider client now drain both streams under
the existing byte cap and deadline instead of checking size after buffering an
entire response. Timeout, excess output, malformed UTF-8, and cancellation clean
up owned processes. Kernel-command and general application transports have not
all been converted to streaming bounds; runtime labels still do not fully bind
model weights or sampling parameters.

Deleting `state/population/population.sqlite` is supported because SQLite is
only a rebuildable query projection.

## Standard local-model end-to-end acceptance

Every Agentvolve workflow or Pi-extension behavior change must run the ordinary
focused/full tests and this opt-in live test against at least three distinct,
operator-approved problems. It deploy-loads the project extension, requires the
runtime's `pi-v1`/`llamacpp` identity, performs actual local model inference,
requires every protected case to pass, and offline-verifies each sealed run.

```bash
export METERING_RUN_AGENTVOLVE_E2E=1
export METERING_EVOLUTION_LIVE_HARNESS=/absolute/harness-run/selected-harness.json
export METERING_EVOLUTION_LIVE_TASK_PROFILES="/abs/one.task.json:/abs/two.task.json:/abs/three.task.json"
# Optional, only when each profile includes explicit retry reservations:
export METERING_EVOLUTION_LIVE_MAX_RETRIES=1
export METERING_EVOLUTION_LIVE_RETRY_REASON="operator-approved local acceptance transport retry"
uv run --extra test pytest -q -m live_agents tests/test_agentvolve_live_workflow.py
```

On POSIX, separate profiles with `:` (`os.pathsep`). A retry is never implicit:
both a positive maximum and an operator-authored reason are required, and fixed
run reservations remain authoritative. The test is deliberately
not part of unattended deterministic CI: it requires Docker, cgroup v2, the
reviewed image, a running pinned local endpoint, a verified sealed harness, and
substantial model time. Skipping it must be reported; a source assertion is not
a substitute for a claimed live acceptance result.
