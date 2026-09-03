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
needed. The Git proposer does not copy `auth.json`; provide sandbox-scoped model
authentication through the environment or command, and never expose credentials
to candidate tools. The connector does not infer a model or retain a session. Harness commands use
`METERING_HARNESS_PROVIDER`, `METERING_HARNESS_MODEL`, and
`METERING_HARNESS_REASONING`; `experiment.py` derives these values from the
canonical runtime profile and rejects disagreement.

## Interactive Population Evolution Mode

From a trusted source checkout, plain `pi` can load the thin project entrypoint
at `.pi/extensions/population-evolution.ts` after Pi's project-trust decision.
The implementation remains owned by this connector. Trust approval permits
project code to run; it is not a sandbox or a built-in tool permission gate:

```bash
cd /path/to/metering
pi
```

Top-level Pi and all user/global extensions or packages run with the host user's
permissions. Review that ambient configuration or run the whole process in a
container/VM for untrusted work. The nested evolutionary Pi calls are separately
isolated and do not inherit those resources.

The footer shows `population: ready`. Use:

```text
/evolve          start one new fixed two-generation live experiment
/evolve-status   show the latest sealed result without a model call
/evolve-verify   replay the latest run with the offline verifier
```

The two-level coding commands are:

```text
/evolve-harness                    [2/6] evolve/final-seal the Pi harness on coding assays
/evolve-harness-status             show the latest harness process stage
/evolve-harness-resume             resume replayable harness effects without a model retry
/evolve-harness-retry REASON       explicitly authorize one reserved harness retry
/evolve-code /absolute/task.json  [4/6] evolve immutable solution commits
/evolve-code-resume               resume committed effects without a model retry
/evolve-code-retry REASON         explicitly authorize one bounded retry
/evolve-code-status               show the current stage, selected commit, and patch path
/evolve-code-verify               replay the latest coding run offline
```

The extension displays a stable `[n/6]` tracker from task configuration through
result readiness for review and polls projection-only `process-status.json` while
a run is active. The tracker cannot authorize model calls, final access, or
selection.

`/evolve-code` uses the newest completed coding-harness run. The profile path
must be absolute and operator-reviewed; alternatively set
`METERING_EVOLUTION_TASK_PROFILE`. The profile, not Pi, supplies repository/base
identity, allowed paths, development checks, the digest-bound external protected
profile, exact draws, and budgets.
The `darwinian_coding` tool exposes only `harness_run`, `harness_status`,
`solution_run`, `solution_status`, and `solution_verify`, and accepts no model-supplied task,
command, candidate, evaluator, profile path, or output path. Selected code is
written as an immutable commit and `selected.patch`; it is never applied to the
source repository.

The active `population_evolution` tool also lets an outer interactive Pi handle
an explicit request such as “run Population evolution.” It accepts only
`run`, `status`, or `verify`; it accepts no command, task, candidate, evaluator,
or output path from the model. `/evolve` is the deterministic route and does not
require an outer model turn.

The default reviewed runtime is
`~/.config/metering/harness/runtime.pi.local.json`, and completed runs are kept
under the checkout's sibling `metering-live-runs/` directory. Override those
locations only with caller-reviewed absolute paths through
`METERING_EVOLUTION_RUNTIME_MANIFEST` and `METERING_EVOLUTION_RUNS_DIR`.
Opening Pi activates the control mode but does not automatically spend model
resources or start an experiment. The extension invokes the same fixed
`apps/harness/experiment.py` composition documented elsewhere; nested Pi model
calls still receive isolated configuration roots and do not load the project
extension recursively. A selected candidate is recorded and sealed, not
silently installed or deployed as the interactive Pi agent.
