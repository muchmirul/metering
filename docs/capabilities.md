# Current capability map

This page is the short operational guide for users and coding agents. It
describes implemented behavior on `main`; it is not a roadmap. [`PLAN.md`](../PLAN.md)
remains normative when this summary and another document disagree.

## Installed package

| Capability | Status | Boundary |
|---|---|---|
| Self-information | Implemented | One caller-supplied probability |
| Shannon entropy | Implemented | One finite discrete distribution |
| KL divergence | Implemented | Two aligned finite distributions |
| Mutual information | Implemented | One finite rectangular joint distribution |
| Strict JSON command | Implemented | One request on stdin, one canonical result on stdout |
| Git measurement history | Implemented, opt-in | Separate `metering-history` command |
| Probability estimation or normalization | Not implemented | Caller responsibility |
| Generic information, fitness, or intelligence score | Not implemented | Deliberately absent |

The public Python API remains exactly:

```python
from metering import (
    ProbabilityError,
    entropy,
    kl_divergence,
    mutual_information,
    self_information,
)
```

The functions and ordinary `metering` command have no filesystem or network
effects and no runtime dependencies. `metering-history` is separate and requires
Git.

## Git-backed measurement history

Record one accepted configuration and exact named result:

```bash
history="$(mktemp -d)"
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | metering-history record "$history"
metering-history verify "$history"
```

The dedicated repository tracks only:

```text
measurement/pair/configuration.json
measurement/pair/result.json
measurement/provenance.json
```

Git supplies blob, tree, commit, parent, diff, checkout, and optional remote
mechanics. Metering does not copy its source code into the history. `verify`
runs `git fsck`, rejects dirty or malformed histories, and recomputes every
stored result with the current executable.

This proves committed byte identity and current replay agreement. It does not
prove authorship, protect against an authorized force-push, validate the caller's
probability model, or make a named measurement a universal score. Legacy
schema-version-1 `objects/` histories require the historical implementation.

## Source-only evolution applications

The currently implemented agent-artifact path is:

```text
one parent
    -> one proposed child
    -> matched parent/child execution
    -> independent task and safety evaluation
    -> named forecast measurements
    -> explicit pairwise retention
    -> one selected next parent
```

The optional Evolution Driver repeats this transition with generation,
consecutive-rejection, and wall-clock limits. It follows one selected head and
stores a separate canonical JSONL run ledger. It does not use the measurement
history as candidate lineage.

The separate source-only Population Archive can record multiple normalized
candidates, identified experiments and replicates, named development evidence,
a bounded Pareto archive, and exact uniform parent allocations. Its SQLite index
is derived from a canonical hash-linked ledger and is never selection authority.
Typed recombination is implemented only for complete `agent-skill-v1` file loci.
A declared final experiment stops Population Driver recurrence before reveal;
the first final run seals every later Population search transition.

The bounded Population Driver now connects this archive to Controller for
ordinary Git-code candidates. It evaluates the seed, uses each exact Population
allocation as the next Controller parent, records matched parent/child reports as
replicates, refreshes the archive, and stops at an optional evaluator-backed
development goal or global round, proposal-call, timeout-reservation, resource,
empty-archive, or final-evidence limit. A finite round fallback remains required;
a pending
model call requires explicit retry approval; durable Controller evidence resumes
without another model call. Its driver and Population ledgers plus immutable
receipts are authoritative, and it never reads SQLite for recurrence. Its
implementation now separates read-only replay, pure planning, effects, durable
stores, and a thin runtime while preserving schema version 1. A deterministic
executable-Git test demonstrates subtraction -> retained addition -> rejected
multiplication for one arithmetic fixture; this is mechanism validation, not a
claim of general model improvement.

The source-only [Evolutionary Harness](../apps/harness/README.md) now closes the
generic executor gap for one mutation-only profile. It validates nine immutable
typed loci, runs a model-call/output/timeout-bounded provider-neutral
execute/delegate/finish loop, starts independent persistent IPython kernels in a reviewed no-network OCI profile,
restores JSON-safe snapshots after interrupt/timeout, observes procfs/cgroup-v2
resources, emits content-addressed receipts, and composes development recurrence
with one protected final assay and Population's permanent seal. Pi and Prime
Agent are concrete tool-free model transports. Deterministic CI uses the same
wire contract through an explicitly unsafe host-process fixture.

The source-only [Agentvolve](../apps/coding_agent/README.md) workflow is also
implemented through Level 2. Its [component map](coding-agent/components.md)
separates Git, Pi, local model/llama.cpp, IPython, Docker, control-plane, and
evidence responsibilities. The harness can receive bounded coding archives
inside the OCI kernel; a fixed coding assay evolves and seals the nine-locus Pi
harness. A separate Level-1 run then imports one operator-approved repository
commit without `.git`, lets the exact selected harness produce immutable
solution descendants, evaluates every candidate/check pair in a fresh
container, uses Population recurrence, chooses a final candidate by development
task rate then reliability with an exact tie draw, runs protected checks after
allocation, permanently seals search, and emits a replay-checked patch without
changing the source repository. Its strict `darwinian-coding-task-v1` profile
owns allowed paths, argv checks, draws, budgets, and optional goal-or-limit
stopping. Plain Pi exposes delegated jobs, not session activation, through exactly
`/goal`, `/limit`, `/history`, and `/progress`. /limit is a saved suggestion;
every /goal requires a fresh exact cap plus direct task/execution review. Starts can
work in casual extension-enabled sessions without repository/path setup. Messy
requests are organized into requirements, explicit assumptions, and reviewed
checks. Literal file/project references are resolved before remembered defaults;
bounded fixed inspection supplies actual Git/local/public-URL text snapshots.
Sources and the reviewed brief are task-ID-bound proposal input, not permission
to execute source instructions. Read-only inputs cannot overlap writable paths;
malformed drafting JSON offers correction/cancellation without automatic retries.
See [source grounding limits](coding-agent/task-profile.md#source-grounded-preparation).
Task approval selects an existing project or, with none, prepares a
private Git seed containing TASK.md and empty output files. No solution/checks
execute during setup. Existing projects must be clean and committed and are
never initialized/committed automatically; Pi's cwd is unchanged. Ordinary
configured tools/model/thinking remain unchanged throughout jobs; historical mode
records never restore restrictions. New jobs require explicit compatible verified
harness and separate reviewed worker configuration, with no newest-harness guess,
implicit Level-2 costs or shared-service restart. Controller paths remain
operator-managed; a stable separate installation is operationally required, not
automatically snapshotted or sandboxed by Pi version isolation. Fixed code can discover reviewed profiles,
derive the exact goal, clean `HEAD`, finite generations, and draws, and start
without a copied profile path. TUI and RPC require explicit contract selection
and approval. A
user-message/source-grounded session task path asks conversational clarifications when
needed, displays a complete human-readable contract for mandatory review, and
keeps JSON as an optional advanced correction surface. It does not invent
evaluator authority from prose. Session-owned submission attempts distinguish
preparation/failure/uncertain dispatch from acknowledged launch. The monitor,
progress and verification bind only the returned validated job ID/root, never
the latest registry run. A failed newer request cannot inherit old results.
Reload/resume does not restart; forks inherit no job ownership. History selection
does not rebind. The `[1/6]`–`[6/6]` widget appears only for the bound queued/running
job. New submissions/shutdown invalidate pending output without stopping workers.
`/history` pages through all runs and recorded harness/solution generations,
with stage reports and results. Its tree browser adds stable experiment-local
H*/S* labels, actual ancestry, archive status/reasons, per-child evidence reports,
recorded loop steps and failed/pending attempts, and paginated historical diffs.
The optional [Trace Viewer](coding-agent/trace-viewer.md) adds a local clickable
graph, stable depth/branch labels, real Git file nodes, exact source/downloads,
file history/comparison, archive filters, and projection exports. Its bounded
loopback service starts only on explicit opening; it changes no evidence or
Population SQLite schema. It never claims protected-final results for untested children. `/progress`
inspects the exact submitted job, never a latest-run fallback. Nested assay calls remain pinned to the canonical runtime.
Old slash commands and compatibility Pi tool actions are removed; shared engines,
worker CLI recovery/verification, and existing experimental artifacts remain.
Conversational `workflow_manage` adds direct operator-reviewed resume, reserved
retry, stop, verify, and closure as incomplete. `/goal` offers recovery for an
unfinished detached workflow before preparing a new task. Unmanaged legacy history
no longer blocks startup or requires directory switching. Explicitly closing an
inactive workflow adds only `closed.json`, preserves all existing evidence, and
prevents reopening without claiming success; budgets and final seals are unchanged.

Implemented candidate forms are:

- default-agent configuration;
- one complete `SKILL.md` artifact; and
- immutable `git-candidate-v1` trees with optional external-output receipts,
  including typed harness and operator-approved solution commits.

A Git candidate may be configuration-only when its fixed external executor
interprets the configured entrypoint. Candidate identity must bind configuration
independently of evaluation evidence. Do not include mutable scores in a
candidate tree and then treat the resulting commit as the same candidate.

## Not implemented

Do not claim or infer these capabilities from the current repository:

- unbounded autonomous execution or unbounded recursive agent trees (only the
  finite typed harness policy is implemented);
- weighted reproductive scores or learned parent-allocation policy;
- behavior-bucket retention beyond the implemented Pareto archive;
- Price-equation attribution or proposal-yield evaluation;
- arbitrary Git recombination or evaluator/test coevolution;
- automatic candidate installation, deployment, or rollback;
- a sandbox in the installed Metering package or for arbitrary legacy Git
  executors (the source-only typed harness has one reviewed Docker/cgroup-v2
  profile);
- model training, arbitrary external benchmark integration, or a claim that the
  fixed coding suites establish universal improvement;
- full-context host adoption, ambient agent memory, or inheritance of Pi/IPython
  session state outside an explicit genome.

Only the bounded mutation-only Population Driver, typed-harness composition,
and profile-bound two-level coding composition documented above are current
automatic population behavior. Adaptive mutation,
code recombination, evaluator co-evolution, installation, deployment, and other
sandbox/transport profiles remain parked unless `PLAN.md`, tests, and
implementation are updated together.

## Agent and trust checklist

Before running an application workflow:

1. Read `PLAN.md` and the relevant app protocol.
2. Identify the exact Metering executable/version and current source state.
3. Declare the probability meaning and construction.
4. Keep candidate configuration separate from evaluation results.
5. Pin candidate, task suite, evaluator, runner, budget, and connector identities.
6. Keep protected evaluator material and credentials outside candidate access.
7. Use a reviewed container or VM for untrusted executable candidates.
8. Treat Git hashes as identity/integrity, not authorship or correctness.
9. Recompute measurements; never trust a committed result merely because Git
   accepts it.
10. Report task, safety, cost, and forecast measurements separately.

## Documentation order

- [`PLAN.md`](../PLAN.md): normative scope and acceptance behavior.
- [`theory.md`](theory.md): four measurement definitions and numerical rules.
- [`history.md`](history.md): Git history schema and replay verification.
- [`source-architecture.md`](source-architecture.md): source-only dependency and
  load/plan/effect/store architecture.
- [`agent-evolution.md`](agent-evolution.md): current one-generation artifact
  protocol.
- [`../apps/evolution_driver/README.md`](../apps/evolution_driver/README.md):
  bounded single-head recurrence.
- [`../apps/population_driver/README.md`](../apps/population_driver/README.md):
  bounded archive-allocation-mutation/evaluation recurrence.
- [`../apps/harness/README.md`](../apps/harness/README.md): typed recursive
  phenotype, coding workspace, kernel isolation, receipts, final assay, and
  reference command.
- [Dedicated Agentvolve documentation](coding-agent/README.md): component map,
  simple architecture, workflow, task profiles, operations, verification, and
  threat model.
- [`../apps/coding_agent/README.md`](../apps/coding_agent/README.md): concise
  implementation module map.
- [`../artifacts/git/README.md`](../artifacts/git/README.md): immutable Git
  candidates and external-output receipts.
- [`../connectors/README.md`](../connectors/README.md): fixed connector and trust
  boundaries.
