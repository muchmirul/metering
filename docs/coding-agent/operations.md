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

## Interactive Pi commands

For project-local use, start plain `pi` from the trusted checkout. To register
Agentvolve in every Pi session, add the reviewed absolute project entrypoint to
the existing `extensions` array in `~/.pi/agent/settings.json`:

```json
{"extensions":["/absolute/path/to/metering/.pi/extensions/population-evolution.ts"]}
```

Run `/reload` after changing settings in an existing session. Loading the
extension shows `agentvolve: available` but starts no service or experiment.
The direct goal workflow is:

```text
/goal Describe the independently checkable task
/limit 100 generations
/agentvolve
```

`/goal` records the exact operator text and `/limit` accepts 1 through 256
finite generations. Both values persist in the current Pi session. `/agentvolve`
then activates the pinned local model, discovers the sole applicable reviewed
profile, derives a new canonical profile with the repository's clean `HEAD`,
100 proposal rounds, and 99 exact allocation draws, and starts the complete
workflow. It refuses a dirty repository, a missing entrypoint, an ambiguous
profile choice, or an unfinished earlier run. Goal text never replaces an
executable evaluator.

Without a complete goal/limit pair, open the launcher with:

```text
/agentvolve
```

It first offers two outer-session modes. **Local model** starts the configured
Qwen/llama.cpp user service if needed, waits for the canonical runtime alias,
and switches outer Pi to that model/reasoning selection. **Routed Pi model**
keeps or restores the model Pi was already using and does not start llama.cpp
merely to open the menu. The next screen is a single workflow surface with
start, create-from-session, refresh status, browse history, resume, retry, and
verify actions. Start discovers profiles under `METERING_EVOLUTION_TASKS_DIR`
(default: the checkout sibling `metering-live-tasks`) and prioritizes profiles
whose repository is the current folder. Manual absolute-path entry remains a
compatibility option. Create-from-session sends only user messages from the
active branch plus the tracked Git path list to the selected outer model,
opens the returned task draft in an editor, and requires confirmation before
fixed code binds and registers it. Assistant messages and tool output are not
inputs, so a prior assistant answer is not copied into the task. The generated
protected profile explicitly replays the reviewed development checks and offers
no hidden-case claim.

The UI does not expose the internal Level-1/Level-2 split. While Agentvolve is active, the
widget keeps all six stages visible as `[1/6]` through `[6/6]`, marking completed,
current, failed, and pending stages. Every activated Agentvolve session polls the
shared run directory every two seconds, including runs launched in other
sessions. Deactivation hides the tracker and stops monitoring. Use
`/agentvolve-history` to browse the latest 50 shared runs directly. Start
requests the task profile once and runs or reuses the
sealed harness before continuing into solution evolution and the final assay.
For headless operator automation, Pi RPC mode accepts the complete `/goal`,
`/limit`, `/agentvolve` sequence and direct resume/retry commands without a
synthetic model turn; incomplete `/agentvolve` configuration remains rejected.
Evolution actions in both modes remain bound to the canonical runtime manifest;
changing the actual experiment model requires a separately reviewed manifest.
Direct compatibility commands are:

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

If `/evolve-code` has no argument,
`METERING_EVOLUTION_TASK_PROFILE` must name an operator-reviewed absolute task
profile. It takes priority over folder discovery for a configured goal run.
`METERING_EVOLUTION_TASKS_DIR` must be absolute when set. An isolated run
registry may reuse an existing sealed harness by setting the reviewed absolute
`METERING_EVOLUTION_HARNESS_DESCRIPTOR`; copying a sealed run would invalidate
its repository-bound provenance and is not supported. Merely starting Pi does
not start an experiment.

The model-facing `darwinian_coding` compatibility tool may request only harness
run/status or solution run/status/verification. It cannot choose evaluator commands,
candidates, output paths, task profiles, protected checks, or retry authority.

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
