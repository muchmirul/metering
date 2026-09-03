# Coding-agent operations

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
itself is untrusted. Candidate isolation begins only inside the fixed Darwinian
workflow.

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
search.

## Interactive Pi commands

Start plain `pi` from the trusted checkout:

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
profile. Merely starting Pi does not start an experiment.

The model-facing `darwinian_coding` tool may request only harness run/status or
solution run/status/verification. It cannot choose evaluator commands,
candidates, output paths, task profiles, protected checks, or retry authority.

## Run output

A successful solution run contains:

- `selected-solution.json` and `selected.patch`;
- `candidate.git` with immutable seed and child commits;
- canonical Driver and Population ledgers under `state/`;
- mutation, evaluation, conformance, and final receipts;
- copied task, runtime, harness, and harness-provenance documents;
- protected-final content copied only after development stops;
- `experiment-report.json`; and
- projection-only `process-status.json`.

The output is evidence, not deployment. Review the patch and receipts before any
separate application or merge.

## What offline verification checks

`verify`:

1. replays Driver and Population ledgers and the permanent seal;
2. binds task, runtime, and harness identities to configuration;
3. checks every harness and solution Git candidate, tree, parent, and allowed
   path;
4. closes the exact mutation/evaluation receipt sets;
5. authenticates fresh-container development and final evidence;
6. recomputes capability-first final selection and exact allocation;
7. checks protected-final case coverage and kernel conformance; and
8. regenerates `selected.patch` and requires byte equality.

Deleting `state/population/population.sqlite` is supported because SQLite is
only a rebuildable query projection.
