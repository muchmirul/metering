# Darwinian coding agent

`apps/coding_agent/` is the source-only Level-1 solution-evolution application.
It turns an operator-approved repository task into immutable Git descendants,
evaluates every descendant in a fresh OCI kernel, lets Population retain and
allocate candidates, performs one protected final assay, and returns a selected
commit and patch. It never modifies the source repository, installs the patch,
or changes Metering's installed API.

Level 2 is supplied by the existing typed harness application: run the harness
with the `coding-agent-v1` assay first, then give its sealed
`selected-harness.json` to this application. Level 1 verifies the complete
source Level-2 run before accepting that descriptor and retains a provenance
reference; keep that immutable run root with the Level-1 evidence. The two
levels remain distinct:

```text
Level 2: nine-locus Pi harness commits
    -> fixed coding development suites
    -> Population archive
    -> protected harness final suite
    -> selected-harness.json

Level 1: one caller repository base commit
    -> selected harness edits an archive-only workspace in Docker
    -> host validates allowed changes and creates one child commit
    -> fresh Docker evaluator executes reviewed checks
    -> Population archive and capability-first final allocation
    -> protected final checks and permanent seal
    -> selected-solution.json + selected.patch
```

This is mutation-only. Model weights, evaluator profiles, Population policy,
Docker policy, and the two evolutionary levels do not mutate together.

## Six-stage process tracker

Users see one stable end-to-end process rather than internal component names:

```text
[1/6] Task and runtime configured
[2/6] Evolving harness
[3/6] Harness sealed
[4/6] Evolving solution
[5/6] Protected final assay
[6/6] Result ready for review
```

`process-status.json` records the current stage in each new harness or solution
run root. It is canonical and monotonic but explicitly `projection-only`; it is
never recurrence, selection, or final-evidence authority. Inspect it directly or
use the status commands:

```bash
uv run python apps/harness/experiment.py status HARNESS_RUN_ROOT
uv run python apps/coding_agent/solution_experiment.py status SOLUTION_RUN_ROOT
```

## Operator workflow

Prerequisites are the same reviewed, digest-pinned Docker/cgroup-v2 profile used
by [`apps/harness`](../harness/README.md), a canonical runtime manifest, Git, and
for live runs a pinned Pi/model endpoint. Every evaluator executable and project
dependency must already exist in that immutable image or in the imported source
tree; live execution has no package-download network. A project-specific image
is allowed only after review, digest pinning, and conformance. Its new runtime
identity requires a Level-2 harness selected under that exact image.

First evolve and seal a coding harness:

```bash
rm -rf /tmp/metering-coding-harness
uv run python apps/harness/experiment.py \
  coding-fixture /tmp/metering-coding-harness
uv run python apps/harness/experiment.py \
  verify /tmp/metering-coding-harness
```

Use `coding-pi` and supply the runtime for a live run:

```bash
uv run python apps/harness/experiment.py \
  coding-pi /tmp/metering-coding-harness-live \
  /absolute/path/runtime.pi.json
```

Create and review a canonical `darwinian-coding-task-v1` profile, then evolve a
solution:

```bash
rm -rf /tmp/metering-coding-solution
uv run python apps/coding_agent/solution_experiment.py \
  fixture /absolute/path/task.json \
  /tmp/metering-coding-solution \
  apps/harness/profiles/runtime-fixture.json \
  /tmp/metering-coding-harness/selected-harness.json
uv run python apps/coding_agent/solution_experiment.py \
  verify /tmp/metering-coding-solution
```

For live Pi, replace `fixture` with `pi`, use the reviewed live runtime, and use
the descriptor from a `coding-pi` harness run. After interruption, `resume ROOT`
finishes only replay-authorized committed effects and never repeats an
indeterminate model call. If the run reports a pending intent, inspect it and
spend a predeclared retry reservation explicitly:

```bash
uv run python apps/coding_agent/solution_experiment.py resume RUN_ROOT
uv run python apps/coding_agent/solution_experiment.py \
  retry RUN_ROOT 'operator-reviewed reason'
```

A successful run leaves the
source repository untouched and writes:

- `selected-solution.json`: exact selected candidate, base, task, and patch
  identities;
- `selected.patch`: the binary-capable Git diff from the approved base commit;
- `candidate.git`: immutable seed and child commits;
- `state/`: canonical Driver and Population ledgers;
- `mutation-receipts/`, `evaluation-receipts/`, and `final-receipts/`;
- copied `task.json`, post-development `protected-final.json`, `runtime.json`,
  the identity-preserving `selected-harness.json`, localized harness Git objects,
  `harness-provenance.json`, and kernel conformance evidence;
- a convenience `experiment-report.json` that is not recurrence authority; and
- projection-only `process-status.json`, showing the current `[n/6]` stage.

The selected commit is never merged or deployed automatically. Review
`selected.patch` and its evidence, then apply it through a separate operator
choice.

## Task profile

The task profile must be one canonical JSON object followed by one newline. Its
exact schema is:

```json
{
  "allocation_draws":[{"denominator":1,"numerator":0}],
  "allowed_paths":["src/example.py"],
  "development_checks":[
    {
      "argv":["python","-m","unittest","-q","tests/test_example.py"],
      "case_id":"visible-tests",
      "timeout_ms":20000
    }
  ],
  "final_assay":{
    "path":"/absolute/operator-approved/protected-final.json",
    "sha256":"0000000000000000000000000000000000000000000000000000000000000000"
  },
  "final_draw":{"denominator":1,"numerator":0},
  "goal":"Fix src/example.py without changing its public interface.",
  "limits":{
    "max_proposal_calls":4,
    "max_rounds":2,
    "max_wall_seconds":100000
  },
  "repository":{
    "base_commit":"IMMUTABLE_GIT_COMMIT",
    "entrypoint":"src/example.py",
    "path":"/absolute/operator-approved/repository"
  },
  "schema_version":1,
  "task_schema":"darwinian-coding-task-v1"
}
```

The separately permissioned final profile is also canonical JSON plus one
newline:

```json
{"checks":[{"argv":["python","-c","from src.example import solve; assert solve(2)==4"],"case_id":"protected-edge-case","timeout_ms":20000}],"final_schema":"darwinian-coding-final-v1","schema_version":1}
```

`final_assay.sha256` binds the exact bytes of that file. The orchestrator checks
neither its existence nor its contents while accepting the development profile;
it opens, authenticates, and copies the file only after development recurrence
has stopped.

Rules enforced before execution include:

- repository and task/final-profile paths are normalized absolute paths, the
  final profile is outside the repository, profile files are at most 2 MiB, and
  the base commit resolves;
- allowed paths are unique sorted relative POSIX paths with no `.git`, `..`,
  backslash, NUL, symlink, or device-file semantics;
- check commands are reviewed non-empty argv arrays, never shell strings;
- development and final case IDs are unique within their own suites;
- each check and every global count/wall limit is finite;
- there are exactly `max_rounds - 1` recurrence draws; and
- `max_proposal_calls` is at least `max_rounds`. Calls above the round count are
  finite reservations for explicit retries; ordinary resume cannot consume them.

Before an authorized retry, fixed code seals the content-addressed mutation and
evaluation receipts already present into `state/retry-effects/` and includes
the snapshot digest in the next hash-derived attempt identity. Offline replay
treats otherwise-unbound effects as non-selecting residue and requires exact
closure over every receipt.

Protected final checks are never placed in mutation prompts, development
Controller requests, Population archives, or ancestry feedback. Fixed code
reads them only after development recurrence stops; final selection is recorded
before any protected evaluator request is made.

## Workspace and execution boundary

The host never gives Pi a Git checkout. Fixed code snapshots the approved base
commit into sorted base64 regular-file records, excluding `.git`, and sends at
most 2,000 files/8 MiB over the kernel ABI. The OCI container has no host mount,
network, Docker socket, credentials, devices, writable root, or elevated
capability. It has only its bounded `/tmp` workspace.

Inside the container, fixed helpers provide list, binary-safe read, text write,
delete, search, and shell-free argv execution. A candidate may inspect every
imported file but may persist changes only under `allowed_paths`. Command output,
time, process count, memory, CPU, storage, and total workspace size are bounded.
Symlinks and non-regular exports fail validation. A restart restores the latest
authenticated workspace snapshot.

After a model finishes, the host validates the complete returned snapshot and
changed-path set, materializes it in a disposable checkout, and creates the
child commit itself. Branch names are convenience refs only; candidate identity
binds commit, tree, portable content SHA-256, entrypoint, and parent.

Development and final checks do not run in the mutation container. Each
candidate/check pair is imported into a new container under the same immutable
runtime profile. The check argv comes only from the reviewed task profile. A
return code of zero before timeout means pass; output digests, kernel
observations, runtime, task, candidate content, and separately named resource
coordinates enter an immutable receipt.

## Retention and final selection

Controller compares parent and child on identical development cases and requires
one additional passing case with no safety regression to promote the child.
Population independently stores every authenticated replicate and retains its
bounded development Pareto archive over separately named task, reliability,
novelty, forecast, information, and resource coordinates. Exact rational draws
choose reproductive parents; no scalar fitness or softmax is introduced.

For the user-facing final result, uniform allocation across resource tradeoffs
can choose a cheaper failing candidate. Coding tasks therefore declare a narrow
`development-task-rate-reliability-v1` final policy: fixed code first filters the
last development archive to maximum task rate, then maximum reliability, and
uses the profile's exact `final_draw` only to break a canonical candidate-ID tie.
It derives and records the corresponding exact Population allocation draw.
Offline verification recomputes all three steps. This is lexicographic,
task-specific deployment selection, not a generic intelligence score.

The allocation precedes final-task execution. A one-use final experiment is then
declared, which stops recurrence. The first final run permanently seals
Population. Final failure is reported; it cannot trigger another mutation,
selection, retry, or replacement assay in the same run.

## Offline verification

`verify` does not execute a model or trust SQLite. It:

1. replays Driver and Population hash-linked ledgers and the permanent seal;
2. binds the copied task/runtime/harness profiles to Driver configuration;
3. re-clones every exact harness and solution Git candidate and checks parentage,
   trees, portable contents, manifests, dependency compatibility, and allowed
   paths;
4. closes the mutation-receipt set over every child edge;
5. validates every development and final evaluation receipt against exact
   candidate content, task, runtime, and fresh-kernel evidence;
6. recomputes capability-first final selection and its Population allocation;
7. verifies exactly one protected final run and complete final case coverage;
8. verifies kernel conformance and all content-addressed receipt names; and
9. regenerates `selected.patch` from Git and requires byte equality.

Deleting `state/population/population.sqlite` before verification is supported;
the database is only a rebuildable projection.

## Interactive Pi mode

From a trusted checkout, plain `pi` exposes:

```text
/evolve-harness                    [2/6] evolve and seal a Level-2 coding harness
/evolve-harness-status             show the latest harness process stage
/evolve-harness-resume             finish replayable Level-2 effects without a model call
/evolve-harness-retry REASON       explicitly retry one reserved Level-2 model attempt
/evolve-code /absolute/task.json  [4/6] evolve Level-1 solution commits
/evolve-code-resume               finish committed effects without a new model call
/evolve-code-retry OPERATOR_REASON explicitly retry one indeterminate model attempt
/evolve-code-status               show the selected solution and patch path
/evolve-code-verify               run offline verification
```

Set `METERING_EVOLUTION_TASK_PROFILE` to an operator-reviewed absolute profile
if `/evolve-code` is invoked without an argument. The model-facing
`darwinian_coding` tool accepts only `harness_run`, `harness_status`,
`solution_run`, `solution_status`, or `solution_verify`; it cannot authorize retry or supply
goal text, commands,
checks, candidates, output locations, or profile paths. Merely opening Pi starts
no run.

## Claims and limits

The deterministic fixture proves branching, immutable descendants, rejection,
harness selection, solution improvement on its declared cases, protected final
sealing, and offline replay. A live passing run establishes correctness only for
its exact model, harness, repository commit, runtime, checks, and receipts.
Neither establishes universal coding-agent improvement. The Level-2 harness
benchmark may saturate; a selected variant that ties the seed on development
cases is an evolved and independently retained harness, but not evidence of a
capability increase. Comparative one-shot/continual/Darwinian studies across
protected task sets remain empirical work.

Not implemented: candidate-written evaluator authority, evaluator co-evolution,
model-weight training, arbitrary Git crossover, networked workspaces, automatic
installation/deployment, concurrent generation authority, or adaptive mutation
weights.

## Modules

| Module | Responsibility |
|---|---|
| `process_tracker.py` | projection-only canonical `[n/6]` operator status |
| `protocol.py` | canonical caller-owned task profile and task identities |
| `harness_workspace_editor.py` | selected-harness materialization and isolated solution mutation |
| `candidate_runner.py` | fresh-container execution of immutable solution commits |
| `solution_evaluator.py` | authenticated receipt loading and validation |
| `evaluator.py` | independent fresh-container workspace checks for Level-2 harness assays |
| `evidence_adapter.py` | Controller execution receipts to Population evidence |
| `final_assay.py` | capability-first allocation, protected checks, and seal |
| `solution_experiment.py` | complete Level-1 sequencer and offline verifier |
| `validate_solution.py` | host-side syntax/content validation without candidate import |
| `fixtures/fixture_solution_proposer.py` | deterministic CI mutation transport |
