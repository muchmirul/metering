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

The Pi operator now performs [version resolution and CLI-contract preflight](pi-versions.md)
before service/workflow launch. An updated interactive Pi can use an older
experiment's exact worker release from a separate version cache. A missing or
incompatible executable fails before a new pending proposal is created. No
version check, old manifest, or sealed runtime is weakened.

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
that runtime dependencies or the model endpoint are available. It also rejects
a development wall budget that cannot reserve one generation, reporting the
configured and required seconds. Partial-cap funding remains allowed with a
warning. [Task review](task-profile.md#development-timeout-reservations) discloses
the existing reservation calculation; Pi prompts for an operator-entered budget
correction before approving a new task, without editing any existing profile/run.
If development has no archive, its real stop reason is reported without attempting
protected-final work. A budget stop with an archive still permits final selection.

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

In Pi, say **“manage the interrupted Agentvolve workflow”**. The
`darwinian_coding` action `workflow_manage` opens paginated workflow selection
and a direct operation review. You may resume, explicitly authorize one reserved
retry, stop a live worker, verify completed work, or close inactive work as
incomplete. Retry and closure require a reason entered by the operator, not
supplied by the model. Cancelling starts nothing. No extra slash commands are
registered; reload Pi once after upgrading the extension.

`/goal` and conversational task starts check the registry before task drafting or
model-service effects. An unfinished detached workflow opens this recovery dialog
instead of sending you to a terminal. Closing it continues the new task's normal
review; any other choice leaves the new goal pending. Existing unmanaged legacy
experiments are counted and left unchanged in `/history`, not treated as owners of
the detached registry. Their absence of a final report is not proof of a live
worker, failure, or success; new startup does not recover them automatically.
Deliberate legacy recovery still uses the compatibility entrypoints below.

**Close is not success.** `close WORKFLOW REASON` acquires the exclusive workflow
lock, refuses running or completed work, and writes `closed.json` with schema
`agentvolve-workflow-closure-v1`, the original workflow ID, timestamp, and operator
reason. It does not rewrite any existing experimental or status files, reclaim
budgets, or declare a protected assay. The workflow remains visible as
`closed-incomplete` and cannot resume/retry; a new goal requires a new reviewed
experiment. This adds orchestration metadata only, not a migration of old runs.

Compatibility commands, when deliberately operating on a legacy experiment:

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
uv run python -m apps.coding_agent.agentvolve_worker close WORKFLOW_ROOT 'operator reason'

# Read-only startup and operation-menu hints (no files are created):
uv run python -m apps.coding_agent.agentvolve_worker registry RUNS_DIRECTORY
uv run python -m apps.coding_agent.agentvolve_worker control WORKFLOW_ROOT

uv run python -m apps.coding_agent.operator_view progress RUNS_DIRECTORY [RUN_NAME]
uv run python -m apps.coding_agent.operator_view history RUNS_DIRECTORY [OFFSET]
uv run python -m apps.coding_agent.operator_view trace RUNS_DIRECTORY RUN_NAME [OFFSET]
```

Each effectful worker command returns one bounded JSON response. `close` returns
`state: closed-incomplete` and PID 0 because it launches nothing. Start responses
add `legacy_unfinished_count`, a diagnostic count rather than evidence of liveness.
`registry` returns a blocking detached workflow, if any, plus that count; `control`
returns lock/completion/closure/retry hints. These projections do not authorize
recovery; the effectful worker checks again. Progress and history return one
bounded projection document. The Pi start command readies
the fixed local service when its manifest requires one; another adapter must make
that reviewed endpoint ready before calling `start`. Adapters must not infer
experimental authority from either document.

## Interactive Pi commands

Load the reviewed `.pi/extensions/population-evolution.ts` entrypoint from a
trusted checkout, or register its absolute path in Pi's existing extension
settings. Loading it only registers commands; it starts no model, service, or
experiment.

The normal flow may begin entirely in conversation: ask Pi to activate
Agentvolve, describe the coding goal in ordinary language, answer any needed
clarifying question, and explicitly ask it to solve the task. Model-facing
activation starts no worker. Session task preparation uses only user messages
and tracked path names, shows a human-readable review of repository, paths,
checks, budgets, stopping, and final policy, and registers canonical JSON only
after direct operator approval. Advanced JSON editing remains available when a
generated draft needs correction.

The only Agentvolve slash commands are:

```text
/limit 10
/goal Describe the independently checkable task
/history [RUN_NAME]
/progress
```

`/limit` saves 1–256 generations for future tasks. `/goal` asks for a limit if
missing, then offers reviewed current-repository contracts or prepares a new
user-only draft. Even a sole discovered contract requires selection. Direct
human-readable task approval is mandatory in both TUI and RPC before start.
Cancelling or invalid input starts no worker. Pending goals may be resubmitted
with `/goal` alone; successful launch clears the goal but retains the last limit.
Session restore starts no task. Changing `/limit` never changes a running task
and is refused during task review.

Pi keeps its model and thinking level. The worker uses the canonical runtime's
independent provider/model/reasoning and budgets. Launch returns immediately;
Pi stays usable while the separate worker runs.

`/progress` inspects the most recent run, even after completion, rather than
selecting an older abandoned unfinished run. `/history` pages through every run
(50 per page) and opens stage reports, results, and every recorded harness and
solution generation (20 per page). Reused harness evidence is clearly labelled.
The dashboard refreshes every two seconds. `[`/`]` page generations;
arrows/PageUp/PageDown scroll full stage summaries and result paths; `r`
refreshes, `d` expands the bounded diff, and `Esc`/`q` returns without stopping the
worker. Press **t** to open candidate trees: stable H*/S* labels, actual parent
branches, current archive status/reasons, and selectable reports for every child.
The same browser exposes loop/attempt reports, including failed proposals without
child nodes. Within reports use n/p for steps, ]/[ for historical diff pages, and
Escape to return. Final counts appear only for candidates actually final-tested.
See [complete terminal inspection semantics and CLI](inspection.md).
Press **g** for the optional [Trace Viewer](trace-viewer.md): a local graph of
candidates and their actual Git files, with per-file tracing, comparisons, and
exports. Build the documented frontend assets before first use. The service is
explicitly opened, read-only, capability-protected, and finite-lived; it is not
an Agentvolve worker and closing it never stops evolution.
The compact widget remains active-only and clears when no worker runs.

For upgrade-safe Pi recovery, use
`python -m connectors.fixed.pi.runtime resume WORKFLOW` or
`python -m connectors.fixed.pi.runtime retry WORKFLOW 'approved reason'`.
These resolve the original runtime's executable before delegating to the same
worker; they never grant retry authority or extend budgets.

Recovery and verification use the fixed worker CLI above, either through the
operator-reviewed session management dialog or directly, not additional slash
commands. Resume cannot repeat an indeterminate model call; retry needs a
reserved pending intent and operator reason. Stop does not declare success.
Verification is a detached offline replay after completion. Inherited workflow
locks still prevent concurrent workers.

The UI files are projection-only. `workflow.json` and ordinal job records bind
orchestration identity, while `worker-status.json`, `workflow-report.json`, the
dashboard, and stage notices confer no experimental authority. Candidate Git
objects, canonical ledgers, allocations, receipts, and permanent seals remain
authoritative.

Old `/evolve*`, `/agentvolve*`, `/view-progress`, and `/view-history` registrations
and their unused UI handlers are removed. This includes the reference Pi tool
and low-level harness/solution tool actions, not the shared engine, reference
CLI, or existing evidence. Run artifacts require no migration. Reload Pi and
update command automation.

The model-facing `darwinian_coding` tool supports only no-effect
`workflow_activate`, operator-reviewed `workflow_from_session`, detached
`workflow_start`, read-only `workflow_status` and `workflow_history`,
`workflow_verify`, and operator-reviewed `workflow_manage`. Management selects
a detached workflow from history rather than accepting a model-chosen path.
It
cannot carry task text, evaluator commands, candidates, output paths,
task-profile paths, protected checks, or retry authority as action arguments.
The current user remains the source of session task text and the direct reviewer
of the generated contract.

For Pi RPC automation, send `/limit`, then `/goal`, and service the direct task
selection/approval UI protocol. Never synthesize approval for an unreviewed task.
Launch returns after detachment; wait for the bound workflow's terminal status,
not merely the command response. Progress/history/trace projections are JSON and
can be inspected without attaching to the worker.

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

### Recorded three-task local acceptance: 2026-09-08

The approved clamp, slugify, and maze-route fixtures completed under the
configured local Qwen endpoint (`pi-v1` / `llamacpp` / `local`, worker Pi
0.84.4, medium reasoning), driven by interactive Pi 0.85.1 and the existing
sealed harness. Each task used **one generation and one proposal**, passed
**1/1 protected check commands** with zero safety failures, and passed offline
verification plus candidate/trace inspection. No retry was used, no budget was
changed, and no selected patch was applied to a source repository.

| Task | Workflow | Selected commit |
|---|---|---|
| Clamp | `workflow-pi-20260908T092605156Z` | `5d187df40f76101e492cf5d51ada0c6058be5242` |
| Slugify | `workflow-pi-20260908T124648904Z` | `75268c9bdd5cd3c7987debee7b7a6b9dead2461d` |
| Maze route | `workflow-pi-20260908T124844479Z` | `91127dfe1942d23d04b035a88dce7a6e2dec83ea` |

The initial standalone pytest invocation failed **after clamp completed and
verified**, because its late inspection import could not resolve source-only
`apps`. The test now adds the checkout path and imports inspection dependencies
before any launch; an isolated, no-execution regression covers this setup.
An explicitly approved continuation reused the original per-task test statements
in the **same batch run directory**, verified clamp read-only, and launched only
the two unstarted tasks. That continuation passed **3 tests**; clamp inference
was not repeated, and the original failing log/XML were preserved.

Evidence and the continuation script are outside Git at
`/mnt/Tforce/dev/metering-agentvolve-live-20260908T092601Z-n3qbdla2/`.
`completed-batch-summary.json` distinguishes the initial test-driver failure
from the completed live batch. The separate failed `solve maze.html` workflow
remains untouched. These fixture profiles use legacy exit-status checks, not
external stdout-value contracts; passing them makes no broader correctness
claim. The runtime's model alias also does not fully bind weights or sampling.
