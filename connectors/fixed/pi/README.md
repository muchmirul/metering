# Pi fixed connector

These commands translate Metering's documented proposer and runner protocols to
the public `pi` CLI.

```text
uv run python connectors/fixed/pi/skill_proposer.py
uv run python connectors/fixed/pi/text_runner.py
uv run python connectors/fixed/pi/git_proposer.py
uv run python connectors/fixed/pi/harness_proposer.py
uv run python connectors/fixed/pi/harness_model.py
uv run python connectors/fixed/pi/harness_runner.py
uv run python connectors/fixed/pi/coding_proposer.py
```

The skill proposer and text runner disable tools, sessions, discovered resources,
and context files. They inject the complete verified `SKILL.md` because normal
Pi progressive disclosure needs a read tool. The generic Git proposer leaves
Pi's normal workspace tools enabled inside a file-only candidate workspace; it
must run in a reviewed external sandbox.

The typed harness path is stricter. `harness_proposer.py` supplies bounded
candidate locus text to a tool-free Pi call and applies only declared whole-file
edits. `harness_model.py` translates one provider-neutral turn with every Pi tool
and ambient resource disabled. `harness_runner.py` verifies Pi `--version` and
the runtime's provider/model/reasoning pins, then delegates recurrence, IPython,
subagents, snapshots, compaction, and receipts to fixed code under
[`apps/harness`](../../../apps/harness/README.md). Candidate Python runs only in
the required OCI kernel. `coding_proposer.py` is the fixed Level-1 mutation
transport: it materializes the exact selected harness, keeps the Pi call
tool-free, and lets only the Docker kernel expose bounded workspace tools. It
never gives Pi the host repository, `.git`, evaluator profile, or protected
checks.

Pin the command with a JSON array, for example:

```bash
export METERING_PI_COMMAND='["pi","--provider","openai-codex","--model","gpt-5.6-sol","--thinking","max"]'
```

By default the connector creates a temporary Pi configuration directory and
copies only regular `auth.json` and `models.json` files for tool-free roles; it
does not copy settings, sessions, packages, or other ambient resources. Set
`METERING_PI_CONFIG_DIR` to an existing absolute caller-reviewed directory when
needed. The connector does not infer a model or retain a nested session.

## Interactive Agentvolve mode

The integration is split at a filesystem/JSON boundary:

- `population_evolution_extension.ts` owns Pi commands, tools, lifecycle, and the
  compact always-visible widget;
- `agentvolve_dashboard.ts` owns the live terminal dashboard;
- `population_evolution_support.ts` owns paths, discovery, and strict projection
  decoding;
- `apps.coding_agent.agentvolve_worker` owns detached workflow orchestration; and
- `apps.coding_agent.operator_view` creates read-only progress/history
  projections from workflow state, ledgers, receipts, reports, and Git objects.

The worker status, dashboard, graphs, and reports are projections only. Git
commits, canonical Driver/Population ledgers, allocations, receipts, and seals
remain the experiment authorities.

### Installation and trust

From a trusted checkout, plain `pi` loads the thin project entrypoint at
`.pi/extensions/population-evolution.ts` after Pi's project-trust decision. To
make the commands available in every working directory, add that reviewed
absolute path to the existing `extensions` array in
`~/.pi/agent/settings.json`:

```json
{"extensions":["/absolute/path/to/metering/.pi/extensions/population-evolution.ts"]}
```

Do not overwrite unrelated settings or packages. Run `/reload` after changing
settings. Top-level Pi and its extensions run with the host user's permissions;
project trust is not a sandbox. Nested evolutionary calls use their separate
fixed isolation boundary and do not inherit the operator session.

### Ordinary slash-command flow

Loading the extension performs no model, service, or experiment effect. It shows
`agentvolve: available`. There is no pre-start model picker or action menu.

```text
/goal Describe the independently checked task
/limit 100 generations
/agentvolve
```

`/goal` and `/limit` persist in the Pi session. With both present,
`/agentvolve` derives a canonical task from the sole reviewed profile bound to
the current Git folder and launches a detached worker. Without both values,
`/agentvolve` only activates operator mode and explains the available slash
commands. It does not switch the operator model. Use Pi's normal `/model` command
if a different interactive model is desired.

The worker always uses the provider/model/reasoning identity and finite budgets
from the reviewed runtime manifest. The operator model may therefore be the same
model, another routed model, or a local model without changing experiment
evidence. Pi returns immediately after launch and remains usable while evolution
continues.

Alternative starts are:

```text
/evolve-start /absolute/reviewed.task.json   start an explicit profile
/evolve-start                               use the sole profile bound to this folder
/evolve-task                                draft from user messages, then edit/confirm and start
```

`/evolve-task` is the only start path with an editor/confirmation surface. It
sends the outer model only user messages and tracked path names; assistant
answers and tool output are excluded. Ambiguous profile discovery fails with an
instruction to pass an explicit path rather than opening a picker.

### Progress and history

```text
/view-progress [RUN_NAME]   open the live six-stage dashboard
/view-history               choose a prior shared run and inspect it
/agentvolve-history         compatibility alias for /view-history
```

The dashboard refreshes every two seconds and clearly labels the interactive
operator model and detached worker model/PID/liveness. It shows all six stages,
current activity, committed generation/attempt/archive evidence, a bounded
lineage graph, the latest immutable candidate diff when one exists, each
completed-stage report, and the final selected commit/patch report. Press `r` to
refresh, `d` to expand or collapse the bounded diff, and `Esc` or `q` to return
to ordinary Pi. Closing the dashboard does not stop the worker.

The compact widget also polls the shared runs directory every two seconds. Stage
completion reports are added to the Pi transcript. Any Pi session using the same
runs directory can inspect the worker; neither dashboard nor monitor attaches to
or owns its process.

```text
[1/6] Task and runtime configured
[2/6] Evolving harness
[3/6] Harness sealed
[4/6] Evolving solution
[5/6] Protected final assay
[6/6] Result ready for review
```

A reused sealed harness marks stages 2 and 3 as reused instead of pretending
that new Level-2 work occurred.

### Recovery and verification

```text
/agentvolve-resume
/agentvolve-retry OPERATOR-REVIEWED-REASON
/agentvolve-stop
/agentvolve-verify
/agentvolve-off
```

Resume permits only replay-authorized effects. Retry is accepted only for a
reserved indeterminate attempt and requires an explicit reason. Stop signals the
detached worker and its owned effect process; it does not manufacture a clean
checkpoint. Verification is a detached offline replay and is available only
after completion. Worker jobs are canonical and ordinal, and a per-workflow
inherited file lock prevents concurrent workers.

### Compatibility surfaces

The existing reference Population commands remain:

```text
/evolve
/evolve-status
/evolve-verify
```

The low-level harness/solution compatibility commands also remain for existing
operators and scripts:

```text
/evolve-harness
/evolve-harness-status
/evolve-harness-resume
/evolve-harness-retry REASON
/evolve-code /absolute/task.json
/evolve-code-status
/evolve-code-resume
/evolve-code-retry REASON
/evolve-code-verify
```

The model-facing `darwinian_coding` tool adds `workflow_start`,
`workflow_status`, and `workflow_verify`; its earlier harness/solution actions
remain. It accepts no model-supplied task text, command, candidate, evaluator,
profile path, retry reason, or output path. `population_evolution` remains the
fixed reference-assay tool with only `run`, `status`, and `verify`.

Selected code is written as an immutable commit and `selected.patch`; it is never
applied to the source repository.

### Configuration

The default reviewed runtime is
`~/.config/metering/harness/runtime.pi.local.json`. Runs are stored under the
checkout sibling `metering-live-runs/`, and discovered tasks under
`metering-live-tasks/`. Override only with caller-reviewed absolute paths:

- `METERING_EVOLUTION_RUNTIME_MANIFEST`;
- `METERING_EVOLUTION_RUNS_DIR`;
- `METERING_EVOLUTION_TASKS_DIR`;
- `METERING_EVOLUTION_TASK_PROFILE`; and
- `METERING_EVOLUTION_HARNESS_DESCRIPTOR` for an external sealed harness.

For a `llamacpp` worker runtime, local readiness defaults to
`llama-qwen38.service`, `http://127.0.0.1:8080/v1/models`, and API key
`llamacpp`. Operators may override
`METERING_EVOLUTION_LLAMACPP_SERVICE`,
`METERING_EVOLUTION_LLAMACPP_HEALTH_URL`, and
`METERING_EVOLUTION_LLAMACPP_API_KEY`. Starting Pi never starts the service;
Agentvolve checks it only when launching or resuming a worker that requires it.
