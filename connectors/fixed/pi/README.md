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
/progress                      inspect the most recent run
```

`/goal` activates operator mode, asks for a limit if none is saved, and offers
current-repository reviewed task contracts or a new session-derived draft. Even
a sole discovered contract requires explicit selection; its checks must fit the
new goal. Direct task approval is mandatory before launch in both TUI and RPC.
Cancel or invalid input starts no worker. A pending goal may be resubmitted with
argument-free `/goal`; successful launch clears that goal but retains the limit.
`/limit` affects future tasks only. Restoring a session starts no task.

A new draft uses only user messages and tracked filenames, never assistant
answers or tool output. The exact slash-command goal, repository, and generation
cap remain user-bound. The human-readable review includes the complete goal,
Git base, writable paths, check argv, budgets, stopping policy, and final policy.
Advanced JSON correction is optional. Fixed registration validates the clean
Git binding and canonical profile. Generated finals explicitly replay public
checks; use a separately reviewed profile for held-out coverage.

Normal conversation remains supported: ask to activate Agentvolve (no task,
model, service, or worker starts), clarify a coding goal, then explicitly ask it
to solve it. The `darwinian_coding` tool exposes only `workflow_activate`,
`workflow_from_session`, `workflow_start`, `workflow_status`, `workflow_history`,
and `workflow_verify`. The action schema accepts no task text, command, evaluator,
candidate, profile path, retry reason, or output path. Starts still require a
limit and direct operator approval. Pi keeps its current model/thinking level;
the separate worker stays bound to the reviewed runtime manifest.

### Progress and history

The compact widget is visible only while the latest detached workflow is truly
queued/running, never for an abandoned legacy directory or finished run. In
contrast, explicit `/progress` shows the latest run even after completion.
`/history` pages through runs, newest first, 50 per page; selecting one opens its
six stages, complete stage summaries, result identity/patch location, and all
recorded harness/solution generations in pages of 20. Reused harness evidence is
labelled as reused, not new Level-2 work. Trace pages show parents, children,
selection, check counts, attempts/retries, and archive counts. The underlying
Git objects and ledgers remain the full evidence; diff previews are bounded.

Dashboard keys: `[`/`]` change trace pages; arrows or PageUp/PageDown scroll;
`r` refreshes; `d` expands/collapses the bounded diff; `Esc`/`q` returns to Pi.
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
Use the explicit worker CLI documented in the
[operations guide](../../../docs/coding-agent/operations.md) for resume, reasoned
retry, stop, or offline verify. Retry still needs an authoritative pending intent
and finite reservation. No existing run files are rewritten or migrated.
Selected commits and patches are never automatically applied.

### Configuration

Defaults: runtime `~/.config/metering/harness/runtime.pi.local.json`; runs and tasks
in checkout siblings `metering-live-runs/` and `metering-live-tasks/`.
Advanced caller-reviewed absolute overrides:

- `METERING_EVOLUTION_RUNTIME_MANIFEST`;
- `METERING_EVOLUTION_RUNS_DIR`;
- `METERING_EVOLUTION_TASKS_DIR`;
- `METERING_EVOLUTION_TASK_PROFILE` (must target the current Git repository);
- `METERING_EVOLUTION_HARNESS_DESCRIPTOR` (original sealed source, never rewritten).

For a `llamacpp` worker, readiness defaults to `llama-qwen38.service`,
`http://127.0.0.1:8080/v1/models`, and key `llamacpp`. Reviewed overrides are
`METERING_EVOLUTION_LLAMACPP_SERVICE`, `METERING_EVOLUTION_LLAMACPP_HEALTH_URL`, and
`METERING_EVOLUTION_LLAMACPP_API_KEY`. Only approved start checks/starts that
service; loading, activation, and viewing never do.
