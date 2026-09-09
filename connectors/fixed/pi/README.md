# Pi fixed connector

These source-only commands translate the documented proposer and runner protocols
to the public `pi` CLI:

```text
uv run python connectors/fixed/pi/skill_proposer.py
uv run python connectors/fixed/pi/text_runner.py
uv run python connectors/fixed/pi/git_proposer.py
uv run python connectors/fixed/pi/harness_proposer.py
uv run python connectors/fixed/pi/harness_model.py
uv run python connectors/fixed/pi/harness_runner.py
uv run python connectors/fixed/pi/coding_proposer.py
```

Skill/text roles disable tools, sessions, discovered resources, and context files.
The generic Git proposer requires a reviewed external sandbox. Typed harness and
coding roles use the fixed OCI kernel boundary: Pi receives no host repository,
`.git`, evaluator profile, or protected checks. Harness policy, mutation transport,
independent evaluation, Population recurrence, receipts, and seals remain in
fixed code under [`apps/harness`](../../../apps/harness/README.md) and
[`apps/coding_agent`](../../../apps/coding_agent/README.md).

Pin the connector command with a JSON array, for example:

```bash
export METERING_PI_COMMAND='["pi","--provider","openai-codex","--model","gpt-5.6-sol","--thinking","max"]'
```

Tool-free roles copy only regular `auth.json` and `models.json` into a temporary
Pi configuration, not ambient settings, sessions, extensions, or skills.
`METERING_PI_CONFIG_DIR` may name an absolute reviewed configuration directory.

## Agentvolve in Pi

The integration separates UI, execution, and read-only evidence views:

- `population_evolution_extension.ts`: Pi commands, high-level tool, task review,
  session configuration, and active-only compact widget;
- `population_evolution_support.ts`: runtime paths, discovery, and projection decoding;
- `agentvolve_dashboard.ts`: terminal progress and paginated evolution traces;
- `runtime.py`: offline exact-version resolution and bounded CLI-contract preflight before delegating to the unchanged worker;
- `agentvolve_trace_viewer.ts`: explicit, finite-lived loopback Trace Viewer launch;
- `agentvolve_candidate_browser.ts`: branching trees, selectable child reports,
  loop/attempt steps, and paginated historical diffs;
- `apps.coding_agent.agentvolve_worker`: detached execution;
- `apps.coding_agent.operator_view` and `candidate_view`: read-only progress,
  history, ancestry, and per-candidate/loop filesystem/JSON projections.

### Installation and trust

From a trusted checkout, Pi loads `.pi/extensions/population-evolution.ts` after
its project-trust decision. To use it from other repositories, add the reviewed
absolute entrypoint to the existing `extensions` array in
`~/.pi/agent/settings.json`, without overwriting unrelated settings:

```json
{"extensions":["/absolute/path/to/metering/.pi/extensions/population-evolution.ts"]}
```

Run `/reload` after changing the extension. Top-level Pi extensions have host-user
permissions; project trust is not a sandbox. Evolutionary calls have their own
fixed isolation boundary and do not inherit the operator session.

### Exactly four Agentvolve commands

```text
/limit 10                      save a finite generation cap (1–256)
/goal Describe the problem     review the task, then start detached work
/history [RUN_NAME]            browse runs, full recorded traces, stage reports, results
/progress                      inspect this session's exact submission
```

`/goal` and conversational starts work in casual sessions without requesting a
repository path. Fixed code resolves literal input paths and known project names
before falling back to the remembered project, configured task's repository, or
current Git root; ambiguous references require a choice. With none, the task review proposes a private
`TASK-DIRECTORY/workspaces/task-UUID` workspace. After approval only, fixed setup
creates TASK.md with the reviewed request/requirements/assumptions, empty output
files, and a clean Git seed. It never generates a solution or runs checks on the
host; the detached worker still owns immutable mutation and independent assays.
Cancelled drafts create no workspace. Failed preparation retains any created
files and reports their path rather than automatically retrying or deleting them.

Existing projects must be clean and committed. An invalid target offers an
explicit fresh-workspace alternative, without copying/repairing the old project.
Declining draft review exposes an optional change-destination dialog; only that
optional flow accepts typed paths. Task approval selects the proposed destination
and remembers existing projects across goals/reloads. Private workspaces stay
bound to their task; a later unrelated casual task gets a new one. Pi's cwd is
unchanged, and old session configurations remain valid.

It offers the selected repository's reviewed task contracts or a new
session-derived draft. Even
a sole discovered contract requires explicit selection; its checks must fit the
new goal. Direct task approval is mandatory before launch in both TUI and RPC.
Cancel or invalid input starts no worker. A pending goal may be resubmitted with
argument-free `/goal`; successful launch clears that goal but retains the limit
and any existing-project selection.
`/limit` is a suggestion for future tasks only. Each new submission requires a
fresh exact 1–256 cap; stale saved values are not execution approval.
Restoring a session starts no task.

A new draft uses user messages plus actual source snapshots from bounded fixed
inspection, never assistant answers or prior tool output. Git input is commit-pinned;
explicit local UTF-8 files and public HTTP(S) text documents can also be inspected.
The drafter can request additional tracked files or literal user file/URL references, not arbitrary
host paths, commands or network destinations. Sources are untrusted data, not instructions. The exact slash-command goal, repository, and generation
cap remain user-bound. Messy requests are organized into requirements and explicit
assumptions; essential missing facts/acceptance criteria require clarification.
Existing-project entrypoints stay tracked; new output paths and self-contained
check argv are permitted without modifying input data. Existing checks must be
inspected. No draft may invent nonexistent test scripts or fabricate a solution.
Reviewed context binds requirements, assumptions, source representations/digests
and non-overlapping read-only paths into the canonical task and worker input.
Malformed/duplicate JSON and invalid task fields offer correction, destination
change or cancellation before approval, never silent coercion or a model retry.
The fixed read-only draft validator reuses canonical profile rules. Bounded raw
drafts, inspected snapshots and errors remain in diagnostic-only session entries. [Source limits and compatibility](../../../docs/coding-agent/task-profile.md#source-grounded-preparation)
apply equally to TUI and RPC. The human-readable review includes
the complete goal, brief, Git base (or new-seed notice), writable paths, check argv,
budgets, stopping policy, and final policy.
Advanced JSON correction is optional. Fixed registration validates the clean
Git binding and canonical profile. Generated finals explicitly replay public
checks; use a separately reviewed profile for held-out coverage.

Fixed code computes development timeout reservations before registration or
profile derivation. Review shows per-generation and full-cap amounts without
retries, not elapsed time or a total-workflow budget. If no generation fits,
an input dialog asks the operator for a sufficient integer-second budget or
cancellation; there is no automatic increase. A correction applies only to the
new reviewed task, never an old profile/run. A partially funded cap remains
allowed and is disclosed. Preflight rechecks affordability before worker launch.

Agentvolve is a delegated job using isolated noninteractive Pi calls, not an
interactive session mode. Activation/deactivation actions and mode restoration
are removed. Reload once; historical mode output never restricts ordinary tools,
even in old active sessions. Configured tools/model/thinking stay unchanged and
excluded tools stay excluded. See [job semantics and migration](../../../docs/coding-agent/operations.md#delegated-jobs-and-reload-migration).
Clarify a goal, then explicitly ask Agentvolve to solve that job.
The `darwinian_coding` tool exposes only
`workflow_from_session`, `workflow_start`, `workflow_status`, `workflow_history`,
`workflow_verify`, and operator-reviewed `workflow_manage`. The action schema
accepts no task text, command, evaluator,
candidate, profile path, retry reason, or output path. Starts still require a
limit and direct operator approval. Pi keeps its current model/thinking level;
the separate worker stays bound to the reviewed runtime manifest.

### Progress and history

Each submission persists a session-owned attempt: preparing, not-launched,
cancelled/failed, uncertain-dispatch or launched. Only a validated successful start
acknowledgement binds its returned workflow ID/root. The compact widget follows
that job only while queued/running. /progress and verification also follow that
exact submission, including terminal or failure-to-launch status. A newer failed
request cannot display an older result. Missing/mismatched references fail closed;
no latest-run fallback exists. Interrupted dispatch may have launched work; inspect
explicit history/reviewed management rather than automatically retrying.
Reload/resume across branches follows the owned job without restart; new/fork/clone
sessions do not inherit ownership. Old sessions lacking submission records inspect
history explicitly. History selection never rebinds the current job. Submission
changes/shutdown invalidate in-flight monitor output and timers, not workers.
`/history` pages through runs, newest first, 50 per page; selecting one opens its
six stages, complete stage summaries, result identity/patch location, and all
recorded harness/solution generations in pages of 20. Reused harness evidence is
labelled as reused, not new Level-2 work. Trace pages show parents, children,
selection, check counts, attempts/retries, and archive counts. The underlying
Git objects and ledgers remain the full evidence; diff previews are bounded.

Dashboard keys: `[`/`]` change trace pages; arrows or PageUp/PageDown scroll;
`r` refreshes; `d` expands/collapses the bounded diff; `Esc`/`q` returns to Pi.
See [Pi upgrades and experiment versions](../../../docs/coding-agent/pi-versions.md)
for the optional version cache, explicit overrides, and early compatibility checks.
Interactive Pi upgrades do not rewrite a sealed runtime; older workers resolve
their original version. New experiment versions still need a reviewed matching
runtime/harness. There is no automatic package installation or version bypass.

Press **g** for the [Trace Viewer](../../../docs/coding-agent/trace-viewer.md), a
local Cytoscape.js graph with branch labels, exact Git files, per-file history,
comparison, archive filters, and exports. Its frontend requires a one-time
`npm ci` and `npm run build` under `apps/coding_agent/trace_ui`. Loading Pi and
model-facing status/history actions never launch this service. It uses a private
loopback capability, expires on idle/lifetime limits, and cannot mutate runs.
The capability URL is not persisted as an experiment or projection record.

Press **t** for actual H*/S* candidate trees and select any child to inspect its
recorded development outcomes, identities, archive state/reason, loop steps, and
parent-relative diff. Choose loops/attempts for failed or pending proposals. Report
keys n/p page steps and ]/[ page diffs. Unselected children never get invented
protected-final results; reused H nodes keep their original source. Details and
bounds are in [candidate inspection](../../../docs/coding-agent/inspection.md).

Refresh is every two seconds. RPC clients receive progress/trace projections
and service history/trace selection dialogs. Closing Pi or the dashboard does
not stop or own the worker. The worker and operator model/PID are separately
labelled. Stage notices and all views are **projection-only**, not authority.

Equivalent read-only commands:

```bash
uv run python -m apps.coding_agent.operator_view progress RUNS [RUN_NAME]
uv run python -m apps.coding_agent.operator_view history RUNS [OFFSET]
uv run python -m apps.coding_agent.operator_view trace RUNS RUN_NAME [OFFSET]
```

### Removed UI and retained engine

All old `/evolve*`, `/agentvolve*`, `/view-progress`, and `/view-history` commands,
the reference `population_evolution` Pi tool, and low-level harness/solution Pi
tool handlers are removed. Migrate command automation to `/limit`, `/goal`, and
RPC approval. Pi's unrelated built-in commands remain available.

Shared Population/harness/solution engines, immutable candidates, Docker tests,
protected assays, fixed reference CLI, and worker recovery/verification remain.
Say “manage the interrupted Agentvolve workflow” to use the
`workflow_manage` tool's direct run/operation review, or use the explicit worker
CLI documented in the [operations guide](../../../docs/coding-agent/operations.md)
for resume, reasoned retry, stop, offline verify, or closure as incomplete.
`/goal` offers recovery for blocking detached workflows before drafting a new task.
Unmanaged legacy history no longer blocks fresh startup. Closing an inactive
workflow preserves existing evidence, records `closed.json`, and permanently
prevents its continuation without claiming success. Retry still needs an authoritative pending intent
and finite reservation. No existing run files are rewritten or migrated.
Selected commits and patches are never automatically applied.

### Configuration

Defaults: runtime `~/.config/metering/harness/runtime.pi.local.json`; runs and tasks
in checkout siblings `metering-live-runs/` and `metering-live-tasks/`.
Advanced caller-reviewed absolute overrides:

- `METERING_EVOLUTION_RUNTIME_MANIFEST`;
- `METERING_EVOLUTION_RUNS_DIR`;
- `METERING_EVOLUTION_TASKS_DIR`;
- `METERING_EVOLUTION_TASK_PROFILE` (must target the operator-selected Git repository);
- `METERING_EVOLUTION_HARNESS_DESCRIPTOR` (**required for new Pi jobs**: original
  compatible verified sealed source, never guessed from the newest run);
- `METERING_PI_CONFIG_DIR` (**required for new Pi jobs**: separate reviewed worker
  configuration with models.json and provisioned auth, not interactive Pi's directory).

Read-only `python -m connectors.fixed.pi.runtime review RUNTIME.json HARNESS.json`
verifies the seal and displays exact Pi/version/provider/model/reasoning, runtime,
OCI resources, model budgets, worker config path/models digest and harness identity.
Pi includes that review alongside the full task contract and repeats it before
dispatch, refusing changed configuration. No compatible seal means separately
approved/budgeted [Level-2 setup](../../../docs/coding-agent/operations.md#level-2-harness),
not implicit setup costs or a model substitution. The legacy worker CLI/replay is
unchanged.

Controller/config/auth paths remain operator-managed. Use a separate reviewed
stable installation, not the live engine checkout you intend to edit. Workers
still load trusted code from installed source paths; Pi version/config isolation
is not immutable control-plane deployment or a host-session sandbox. No automatic
snapshot/deployment framework is added; routing aliases do not fully bind weights.

For a `llamacpp` worker, readiness defaults to `llama-qwen38.service`,
`http://127.0.0.1:8080/v1/models`, and key `llamacpp`. Reviewed overrides are
`METERING_EVOLUTION_LLAMACPP_SERVICE`, `METERING_EVOLUTION_LLAMACPP_HEALTH_URL`, and
`METERING_EVOLUTION_LLAMACPP_API_KEY`. Approved submission only checks readiness;
it never starts/restarts the service. Failure asks the operator to diagnose and
separately arrange safe startup without disrupting existing sessions.
