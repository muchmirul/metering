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
before workflow launch; it never starts/restarts a model service. An updated interactive Pi can use an older
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

For a live Pi run, separately approve the Level-2 setup cost and budgets first.
This is not included in a /goal generation cap. The reference coding harness
uses its fixed two-round setup; inspect its runtime/model-call and resource
limits before authorizing it. Do not bypass blocked registries to perform setup.
No compatible seal means new Pi jobs refuse with these setup instructions, not
an automatic model switch or implicit Level-2 run.


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
bounded projection document. The operator must arrange safe endpoint readiness
before calling `start`. The Pi adapter checks readiness but never starts or
restarts an existing/shared service. Failure reports the required model/service
for operator diagnosis, not permission to disrupt another Pi session. Adapters must not infer
experimental authority from either document.

## Interactive Pi commands

Load the reviewed `.pi/extensions/population-evolution.ts` entrypoint from a
trusted checkout, or register its absolute path in Pi's existing extension
settings. Loading it only registers commands; it starts no model, service, or
experiment.

### Delegated jobs and reload migration

Agentvolve is a specialized delegated workflow with its own isolated noninteractive
Pi calls, not an interactive-session mode. The session-toggle architecture is
replaced, not retained as an option. Activation/deactivation actions and mode
persistence/restoration are removed. Historical mode entries/messages (including
active/routed output) are always historical, never current restrictions. A neutral
per-turn directive says so without changing tools, model or thinking level.
Ordinary configured tools remain usable before/during/after jobs and failures;
excluded tools are never enabled. /goal activates nothing.

Reload the reviewed extension once. No run/evidence migration or automatic global
deployment is required. For bootstrap maintenance with an obsolete extension,
`pi --no-extensions` remains available; maintenance is not an evolution run.

Submission entries (`agentvolve-submission-v1`) record an attempt ID and owning
session UUID. /progress and model-facing status show that exact request:

- preparing: a review is in progress, no acknowledged worker;
- not-launched/cancelled/failed: preparation did not dispatch the task;
- uncertain-dispatch: the launch call was attempted but its acknowledgement is
  missing/invalid/interrupted; work may exist, so inspect explicit /history and
  reviewed management before any retry;
- launched: a successful validated acknowledgement bound the workflow ID/root;
  this is not a successful task result.

A new request replaces the session's displayed submission immediately, even if
it fails. Older jobs remain in /history. No view/monitor/verification selects the
latest registry run implicitly. Missing/mismatched referenced jobs report errors,
not fallback results. History selection inspects without rebinding ownership.
The latest owned submission in append order restores on reload/resume across
/tree and compaction, without restarting work; interrupted preparation restores
as not-launched. New/fork/clone sessions do not inherit ownership, even after
reload. Old sessions without submission records must inspect history explicitly;
old launch records cannot reliably identify a newer failed request.

Job changes and session shutdown invalidate in-flight monitor output and timers.
Closing Pi cancels unfinished preparation, never an acknowledged worker. Views,
ordinary task-source edits and interactive model changes do not rebind a worker
to another base commit or runtime. Host Pi keeps its configured permissions;
job artifacts, evidence and the running controller/configuration must not be edited.
The adapter requests stop/retry only through directly approved management.

The normal flow may begin entirely in conversation: describe a coding goal, answer
needed clarifications, and explicitly ask Agentvolve to solve that job.
Session task preparation uses user messages and
actual bounded source snapshots, shows a human-readable review of repository,
source provenance/digests, read-only/writable paths, checks, budgets, stopping,
and final policy, and registers canonical JSON only
after direct operator approval. Advanced JSON editing remains available when a
generated draft needs correction.

The only Agentvolve slash commands are:

```text
/limit 10
/goal Describe the independently checkable task
/history [RUN_NAME]
/progress
```

`/limit` saves a suggested 1–256 cap. Every /goal asks the operator to enter the
exact generation cap for this job; a stale suggestion cannot override a newer
request. It then prepares the task from casual user input without asking for a
repository path. It organizes requirements, labels inferred assumptions, and
requests only essential missing task meaning/data/acceptance criteria. Task review
resolves literal file/directory references and known project names first (asking
when ambiguous), then falls back to remembered/configured/current projects;
with no project, it proposes a private `TASK-DIRECTORY/workspaces/task-UUID` seed.
Only after approval, fixed setup creates TASK.md plus empty output files and a
clean Git commit, then registers the profile and starts the detached workflow.
Generated checks never run on the host, and setup does not implement a solution.

Existing projects still need a clean committed HEAD. They are never initialized,
committed, stashed, or copied automatically. An invalid project offers an explicitly
approved fresh workspace instead. Declining a draft review exposes an optional
change-destination dialog; only that optional route asks for typed paths. Pi's cwd
and ordinary tools never move; shell `cd` cannot change the session binding. Even a sole discovered contract requires selection. Direct
human-readable task approval is mandatory in both TUI and RPC before start.
Cancelling or invalid input starts no worker. Pending goals may be resubmitted
with `/goal` alone; successful launch clears the goal but retains the last limit
and existing-project selection. Later unrelated casual tasks receive fresh private
workspaces; previous files/evidence remain untouched. Cancelling before approval
creates no workspace; later preparation failures retain created files and report
their path without retrying. Reload the extension once to enable casual preparation
in an existing session; there is no run or session migration.
Session restore starts no task. Changing `/limit` never changes a running task
and is refused during task review.

Pi keeps its model and thinking level for clarification/drafting only. The
worker uses the reviewed runtime's independent provider/model/reasoning and budgets.
The task review includes exact worker Pi command/version, runtime ID, OCI kernel
bounds, per-execution model-call/time limits, separate worker configuration path
and models digest, and verified reused harness identity. One generation may make
multiple model calls; development reservations are not a total-workflow deadline.

Say **“configure Agentvolve”** to select the existing runtime, original compatible
sealed selected-harness.json, separately provisioned worker directory containing
models.json and optional auth.json, and a private run registry in the invoking session. `/goal` offers the same
dialog when defaults are absent. Environment variables are optional defaults, not
mandatory exports: no second interactive Pi or process restart is required.
Configuration starts no job and changes no interactive tools/model/environment.
Normal setup offers named existing combinations from bounded discovery, including
the conventional separately provisioned ~/.config/metering/agentvolve-worker.
It never chooses the newest seal; each selected original seal is replayed before
confirmation. Missing setup returns preparation instructions, not an unexplained
blank-path error. Advanced paths still support correction/cancellation. The conventional registry
is `~/.local/share/metering/agentvolve-runs`; create it with mode 0700 on a
permission-capable filesystem such as ext4. The selected registry and owner/mode
are part of execution review. A fuseblk/NTFS path that cannot retain 0700/0600 is
rejected before workflow creation; credential privacy is never weakened.
Per-user setup checklist:

- [ ] Keep the worker configuration and run registry outside every Git checkout.
- [ ] Run `install -d -m 700 ~/.local/share/metering/agentvolve-runs` (or choose another reviewed permission-capable local filesystem).
- [ ] Verify the mount with `findmnt -T PATH` and verify owner/mode 0700 with `stat -c '%U %a %n' PATH`.
- [ ] Provision a separate worker `models.json` and optional `auth.json`; never paste secrets into chat or copy interactive Pi state implicitly.
- [ ] Use **configure Agentvolve** to review runtime, original seal, worker configuration, and registry. Configuration itself must start no job.
- [ ] Reconfigure a version-1 session selection; do not rewrite or move its existing job/evidence.
- [ ] Before committing or pushing, inspect `git status --short` and the staged diff. Private configuration, credentials, `pi-configuration/`, run roots, and evidence must remain untracked and outside the repository.

Approved paths survive reload/resume/tree navigation in this session, not forks or
new sessions; cancellation preserves the previous selection. Changing selection
never changes existing job ownership. Version-1 session selections must be
reviewed again because they did not bind a run registry; existing jobs and evidence
need no migration. Before a new registry is used, blockers in the historical
default registry are still handled rather than bypassed. Setup/provisioning remains separately approved.

The read-only `python -m connectors.fixed.pi.runtime review-configured RUNTIME.json HARNESS.json CONFIG_DIRECTORY PRIVATE_RUNS_DIRECTORY`
checks exact runtime compatibility and offline-verifies the source seal. The
adapter and configured CLI compare the approved review again before dispatch. No newest-harness guessing
or implicit Level-2 costs are allowed. Legacy CLI start without a descriptor still
supports deliberately approved Level-2 workflows and replay, not the new Pi route.

New configured jobs bind command/version/runtime and models SHA256 in a v2 workflow
request. Dispatch copies only bounded regular models.json and optional auth.json
from the explicitly selected source into private job-owned pi-configuration/
(0700 directory, 0600 files; no symlinks or hardlinks). No ambient extensions,
settings, sessions or interactive configuration/auth files are implicitly copied. Models must
retain the approved hash; private auth can refresh. Session records hold only
paths/identity, never auth bytes. Resume/retry use this job's configuration and
command even with conflicting ambient overrides. Status and offline verification
need neither private configuration nor a live Pi executable. Failures preserve
evidence; inspect private diagnostics locally rather than copying credentials into chat.

Controller/runtime/harness paths remain operator-managed. A separate reviewed
stable controller installation is operationally required: the worker still loads
trusted code from its source paths. Do not edit its live engine checkout or runtime
provenance while a worker runs. The bounded Pi configuration copy is NOT a host Pi
sandbox or immutable controller deployment; no general deployment engine is added.
Launch returns after detachment; ordinary Pi remains usable.

`/progress` inspects only the exact submitted job, including completion or failure
to launch. Verification also targets that job. `/history` pages through every run
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
There is no startup welcome notice or idle footer badge. Status appears during
explicit job preparation; the compact widget appears only while the exact bound
job is queued/running. Inactive/terminal jobs, cancelled or failed preparation,
and session shutdown clear Agentvolve-owned status/widget entries only. Unrelated
runs cannot replace them. Completion notices and deduplicated monitor errors
remain, with details available through /progress and /history. No historical
messages, approvals or evidence are deleted. Reload once to replace an older
loaded extension and clear its stale idle UI; there is no activation mode.

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

The model-facing `darwinian_coding` tool supports only operator-reviewed
`workflow_from_session`, detached
`workflow_start`, read-only `workflow_status` and `workflow_history`,
`workflow_verify`, operator-reviewed `workflow_manage`, and session-only
`workflow_configure`. Management selects
a detached workflow from history rather than accepting a model-chosen path.
It
cannot carry task text, evaluator commands, candidates, output paths,
task-profile paths, protected checks, or retry authority as action arguments.
The current user remains the source of session task text and the direct reviewer
of the generated contract.

For Pi RPC automation, send `/limit`, then `/goal`, and service the direct task
selection, exact per-job cap input and approval UI protocol. Destination approval is included in the
full task review; ordinary casual starts require no path input. Never synthesize
approval for an unreviewed target or task.
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

Run the same full static checks as hosted CI first:

```bash
uv run --extra lint ruff check src apps connectors artifacts tests
uv run --extra test pytest -q
```

After fresh operator approval of the exact profiles/runtime/seal/configuration,
use invocation-scoped values, not standing global authorization:

```bash
METERING_REQUIRE_AGENTVOLVE_E2E=1 \
METERING_RUN_AGENTVOLVE_E2E=1 \
METERING_PI_CONFIG_DIR=/absolute/separate-reviewed-worker-config \
METERING_EVOLUTION_RUNTIME_MANIFEST=/absolute/reviewed-runtime.json \
METERING_EVOLUTION_LIVE_HARNESS=/absolute/harness-run/selected-harness.json \
METERING_EVOLUTION_LIVE_RUNS_DIR=/absolute/ext4-backed-private-0700-registry \
METERING_EVOLUTION_LIVE_TASK_PROFILES="/abs/one.task.json:/abs/two.task.json:/abs/three.task.json" \
uv run --extra test pytest -q -m live_agents tests/test_agentvolve_live_workflow.py
```

The required gate fails if approval/prerequisites are absent; it cannot pass by
skipping. Before the first task it validates **all** contracts, clean pinned bases,
full development reservations, compatible replayed seal, worker config/Pi pin,
registry blockers, cgroup-v2 Docker/image availability and the reviewed loopback
model endpoint. This inspection performs no inference and never starts services.
An unloaded requested model is a blocker, not permission to load it, evict another
model or silently change aliases.

The live RPC sessions receive no exported worker runtime/harness/config defaults:
they exercise setup selection and exact execution approval in the same Pi process
that submits each task. The operator test configuration is private and separate
from interactive Pi. Job-owned configuration, ordinary shell availability, exact
submission binding, protected checks and offline replay are asserted.

The old optional automatic-retry environment flags are now rejected. A failing
acceptance run retains its persistent registry/evidence. Inspect its exact job and
obtain directly reviewed recovery outside the gate; never retry automatically or
rerun into a fresh temporary registry. Shell availability is tested with the RPC
`bash` command and actual output, not a `!text` model prompt.

On POSIX, separate profiles with `:` (`os.pathsep`). Any retry outside this gate
requires direct job-specific operator approval, a reason, and an existing finite
reservation. The test is deliberately not part of unattended deterministic CI:
it requires Docker, cgroup v2, the
reviewed image, a running pinned local endpoint, separate reviewed worker config,
an explicitly compatible verified sealed harness, and
substantial model time. Skipping it must be reported; a source assertion is not
a substitute for a claimed live acceptance result.

### Ten-task live batches

The fixed [easy-task catalog](../../tests/fixtures/agentvolve_easy_tasks.json)
contains clamp, bracket balance, run-length encoding, interval merging, stable
uniqueness, transpose, rotation, flattening, word counts, and directed shortest
routes. These are small standard-library Python tasks expected to need few
generations, not a promise that every model will solve them. Prepare fixtures
only after choosing a cap explicitly:

```text
uv run python tests/agentvolve_live_cases.py NEW_BATCH_DIRECTORY MAX_ROUNDS
```

`MAX_ROUNDS` must be 1–256, matching normal task preparation; there is no default. This creates ten clean private
seeds with **empty** solver.py files and separately authored public/protected
contracts. It runs no model, candidate, or generated check. The original seed
registration templates are preserved unchanged. The new `review-manifest.json`
is labelled `operator-review-required`, not approved or passed. Review its ten
goals, exact profiles, budgets and runtime assignment before authorizing a live
batch. External `stdout-json-v1` checks compare actual values and recursive
Python return types; final inputs differ from public examples and are withheld
from proposal/development. Passing finite examples still does not prove general
correctness or prevent all evaluator interference.

For each approved model subset, use the acceptance command above with its exact
`METERING_EVOLUTION_LIVE_TASK_PROFILES`, reviewed
`METERING_EVOLUTION_RUNTIME_MANIFEST`, and compatible sealed
`METERING_EVOLUTION_LIVE_HARNESS`. The default expected provider is `llamacpp`;
another provider requires explicitly setting `METERING_EVOLUTION_LIVE_PROVIDER`
to the exact provider in that runtime. Changing Pi's interactive model or its
“routed” operator label does **not** change the worker. A different runtime
identity needs its own compatible sealed harness; never relabel a local seal.

Set one absolute `METERING_EVOLUTION_LIVE_RUNS_DIR` for all subsets of a batch.
The gate does not retry. Any reserved retry needs separately reviewed job-specific
recovery outside the gate.
A failure/pending intent blocks the next start and requires operator-reviewed
recovery/closure; do not select another registry to continue around it. Keep all
logs, receipts and failures. Report task/model, completed generations, proposal
calls, public/final outcomes and offline verification from recorded evidence,
not merely successful launch. Using different task subsets for different models
is a coverage test, not a controlled model-performance comparison.

### Real-model drafting smoke (no execution approval)

```bash
METERING_RUN_AGENTVOLVE_PREPARATION_LIVE=1 uv run --extra test pytest -q tests/test_agentvolve_preparation_live.py
```

This separately tests the repaired preparation path with actual inference. The
default operator model is `llamacpp/local`; optional
`METERING_PREPARATION_LIVE_PROVIDER` and `METERING_PREPARATION_LIVE_MODEL` select
an explicitly chosen drafting model. Also set the explicit compatible
METERING_EVOLUTION_RUNTIME_MANIFEST, METERING_EVOLUTION_HARNESS_DESCRIPTOR and
separate METERING_PI_CONFIG_DIR for execution review; the smoke still declines
execution and does not set these up. A clean synthetic project outside Pi's cwd
contains a fresh unpredictable token. The test requires that token in the
model-authored output check, correct source digest/commit, and read-only input
permissions. It always **declines** task execution: no task profile, workflow,
candidate mutation, final assay, or automatic retry is authorized. Its fixture
review cap is not approval of any real evolution budget.

On 2026-09-08 the local drafting smoke passed in **62.49 seconds**. Evidence is
preserved at `/mnt/Tforce/dev/agentvolve-preparation-live-HsfXkJ/`, including the
pytest log/XML and review events. This establishes one actual source-grounded
draft, not successful solution evolution or completion of the ten-task batch.
A later final-tree smoke **failed in 10.65 seconds**, before task review: budget
validation rejected model-proposed check timeout data. Its evidence is retained
at `/mnt/Tforce/dev/agentvolve-preparation-final-XqHBra/`. The original model draft
was not yet recorded, so the exact invalid value cannot be reconstructed from
that log. Follow-up code now records bounded drafts/snapshots and validates the
entire contract before approval, with explicit correction/cancellation instead
of an unrecoverable error. Deterministic regressions cover missing/string/boolean/
zero timeouts and other malformed fields. That local failed inference was not
retried; these regressions are not a passing replacement local live run. The
routed-only follow-up below is separate. The original two-model ten-task batch
and updated three-task local workflow acceptance remain unrun.

### Recorded five-task routed acceptance: 2026-09-09

The operator approved routed-only testing with **at most four generations per task** and
**at most three repair/test cycles**, with no automatic workflow retries. Cycle 1
completed all five distinct tasks under `openai-codex/gpt-6-astra`, **medium worker
reasoning**, and pinned Pi **0.85.1**. Every task used **one generation and one
proposal**, passed its public and protected external stdout/type checks with
**zero safety failures**, and passed independent offline verification and actual
candidate/trace inspection. The live pytest entry exercises all five workflows:
**1 test passed in 221.44 seconds**, excluding one-time harness setup. No further
cycle was spent after this clean five-task result.

| Task | Workflow | Protected inputs | Selected commit |
|---|---|---:|---|
| Matrix transpose | `workflow-pi-20260909T001933659Z` | 3 | `ebdf0178b61a2c93e51f0c67c7ff712813628467` |
| List rotation | `workflow-pi-20260909T002012566Z` | 4 | `1aabab071841b830525a082f72da49c692446f0b` |
| Nested-list flattening | `workflow-pi-20260909T002053454Z` | 3 | `3ec765159046152c9e1c1c2d320ee5eeabda4e4b` |
| ASCII word counts | `workflow-pi-20260909T002140378Z` | 4 | `4cd8477d5462a5f0a587bbd9b39d8cb88f362427` |
| Shortest directed route | `workflow-pi-20260909T002225294Z` | 3 | `97e7f9a9dc7da13c06baec2f3a60e4adf70cd8ce` |

Each task has **one** protected check command containing the listed distinct
inputs: **17 protected inputs total**, not 17 separately sealed commands. There
are also four public examples per task. Original seeds remain clean and
`solver.py` stays empty in every seed; all selected solutions are separate Git
artifacts. No solution patch was applied, old evidence was unchanged, and the
same `/mnt/Tforce/dev/metering-live-runs` registry was used throughout.

The new routed harness at `harness-pi-20260909T000047618Z` completed two setup
generations/two proposals, passed **3/3 protected harness checks** with zero safety
failures, and passed separate offline verification. It uses runtime ID
`2e198db2bbd3db782fd88995ec464911eb4c0e67c5922caa66a49446d388c704`.
Local runtime files/seals were not relabelled or changed. All five solution
workflows reused this newly sealed harness; they performed no additional Level-2
search. Runtime JSON is in the batch directory, not a new global default.

Before that cycle, a genuine routed drafting smoke failed in **15.25 seconds**:
the model read the source but emitted scalar `expected_stdout`. Strict validation
correctly offered correction before approval. Its evidence remains at
`/mnt/Tforce/dev/agentvolve-routed-preparation-m4a0ZQ/`. The prompt now explicitly
states the unchanged non-empty-object envelope and how a check wraps a scalar/list
return. No validator or acceptance criterion was weakened. After this fix, the
routed preparation smoke passed in **14.69 seconds**, with execution declined.
Deterministic regressions additionally cover scalar/array/empty expected roots and
direct correction without automatic model retry. Full regressions passed **605
tests, 3 skipped**. The skipped local acceptance is not replaced by routed results.

Complete evidence is at `/mnt/Tforce/dev/agentvolve-routed-five-59in4t7t/`:
`completed-cycle-1-summary.json` binds the five results, unchanged-seed checks,
per-task verification files, tested-code hashes and the original drafting failure.
It also records a corrected read-only reporting-probe field typo; no experiment
was repeated for that probe. Logs/XML, profiles and harness verification are
retained. Passing these finite cases does **not** prove universal correctness,
absence of all bugs, or a fair local-versus-routed performance comparison. This
fixture route task is not the pending `maze.html` task.

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
