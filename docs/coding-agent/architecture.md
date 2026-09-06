# Agentvolve architecture and threat model

This document defines the accepted source-only Agentvolve Level-1/Level-2 coding
workflow.
[`PLAN.md`](../../PLAN.md) remains normative. Use the [operations guide](operations.md)
for commands, the [task-profile reference](task-profile.md) for configuration,
and the [stopping-policy guide](stopping.md) for goal-or-limit semantics.

## Evolutionary semantics

A candidate's lifetime is one isolated Pi/harness execution. Its transcript,
IPython namespace, temporary files outside the exported workspace, and provider
session are phenotype/acquired state. They are not heredity. Heredity consists
only of an explicitly validated immutable Git child:

- for Level 1, a solution commit whose first parent is the allocated solution
  commit;
- for Level 2, an `evolutionary-harness-v1` commit whose first parent is the
  allocated harness commit and whose manifest binds all nine typed loci.

Model experience may guide the proposed edit, so mutation proposal is
Lamarckian. The edit receives no reproductive authority: fresh independent
checks produce evidence, Controller authenticates the pairwise comparison, and
Population controls retained archive membership and future allocation. This is
Darwinian retention inside Agentvolve; `darwinian-coding-*` remains the existing
machine-identifier prefix.

The implementation evolves only one level at a time:

| Experiment | Evolvable genome | Frozen authorities |
|---|---|---|
| Level 1 solution | Repository files under caller-approved paths | selected harness, model/runtime, task profile, evaluators, Population policy |
| Level 2 harness | Nine typed harness loci | coding workspaces/tasks, mutation transport, model/runtime, evaluators, kernel/Docker policy, Population policy |

A selected Level-2 harness is manually and immutably supplied to a later Level-1
run. Before accepting it, Level 1 offline-verifies the complete sealed Level-2
source run, preserves the original candidate identity while copying its Git
objects locally, and records `harness-provenance.json`. Later resume and replay
recheck that source evidence. A Level-1 result never changes harness policy.
This preserves attribution.

## Operator and worker processes

Interactive Pi is the operator, not the evolution executor. Conversational or
slash-command Agentvolve activation changes only session mode and starts no
task. After a canonical task is selected or prepared from user-only session
messages and directly reviewed, `/agentvolve`, `/evolve-start`, or the
model-facing start action launches `apps.coding_agent.agentvolve_worker` in a
detached session and returns control to Pi. The worker alone sequences harness
and solution effects using the canonical runtime manifest. It owns a
workflow-scoped inherited file lock, bounded logs, heartbeat/liveness identity,
and canonical ordinal start/resume/retry/verify jobs. Closing Pi or the live
dashboard does not attach to, cancel, or change that worker.

The boundary is portable filesystem JSON. A thin agent adapter needs only to
launch fixed worker actions and render `apps.coding_agent.operator_view` output;
it does not need access to mutation prompts or evaluator internals. The operator
view derives current rounds and lineage from canonical ledgers and candidate Git
objects. Its `worker-status.json`, `workflow-report.json`, per-run
`process-status.json`, dashboard, and stage notices are projection/orchestration
data only: they cannot authorize model calls, selection, final access, or replay.
Git, JSONL, allocations, receipts, and seals remain authoritative.

The operator sees the stable `[1/6]` through `[6/6]` lifecycle documented in the
[six-stage workflow](workflow.md). A reused sealed harness is explicitly marked
as reused rather than presented as work performed by the current worker.

## Evidence visibility

Three classes are distinct:

1. **Feedback evidence** is model-visible workspace content and output from
   commands the model chooses in its mutation container. It may guide only that
   lifetime's edit.
2. **Selection/development evidence** is produced by caller-owned checks in
   fresh evaluator containers. It controls Controller retention and Population
   archives. It is not inserted into sibling prompts by hidden mutable state.
3. **Protected-final evidence** is opened only after development stops. The
   Level-1 profile contains only an absolute path and SHA-256 for a separately
   permissioned canonical final profile. No protected evaluator request is made
   until final allocation is recorded. Declaring the final experiment stops
   Driver recurrence; its first run permanently seals Population. Protected
   data cannot become feedback or ancestry data. Separate operator preflight may
   validate the profile structure before search; it returns no protected contents,
   case counts, or outcomes and runs no candidate checks.

A candidate may create its own tests as ordinary changed files if their paths
are allowed, but those tests have no authority unless the reviewed profile also
runs them. The caller-owned check contract remains decisive. Legacy argv checks
use exit status, not proof that assertions completed. Optional Level-1
`stdout-json-v1` checks compare authenticated output values with an expectation
held outside the sandbox; this still does not prove general correctness or test
quality. Likewise, a worded
`goal` guides mutation but does not authorize stopping. Only fixed control-plane
logic over independently evaluated development evidence can report
`development_goal_reached`; a finite round limit remains mandatory.

For a component-by-component view of Git, Pi, Qwen/llama.cpp, IPython, Docker,
and the control plane, see the [Agentvolve component map](components.md).

## Authority and storage

```text
Git commits             candidate source/genome and first-parent ancestry
canonical JSONL         Driver/Population recurrence and selection authority
content-addressed JSON  mutation, execution, conformance, and final receipts
SQLite                  disposable query projection only
selected *.json/patch   operator-facing derived output, replay-checked
```

Mutable branch refs, Pi sessions, SQLite rows, convenience reports, and model
claims never identify a candidate or authorize recurrence. Git supplies content
and parent integrity, not authorship or correctness. Canonical receipt hashes
supply immutable local identity, not signatures or protection against an actor
who can consistently replace the entire run directory. Remote protection,
signing, and access control remain deployment concerns.

## Trust zones

| Zone | Trusted for | Not trusted for |
|---|---|---|
| Operator task profile | repository/base/path permission, check argv, budgets, final tie draw | implementation correctness until validated |
| Fixed host sequencer | archive import/export, candidate commits, receipts, recurrence, final seal | candidate task solution |
| Pi/model transport | proposing actions/edits under a pinned identity | checks, retention, credentials inside candidate container |
| Mutation container | executing untrusted model-generated code against an archive | host files, `.git`, network, Docker, evaluator assets, persistence |
| Evaluator container | executing reviewed argv against one candidate archive | mutation, selection, host access |
| Controller | authenticating one matched parent/child comparison | future-parent allocation |
| Population | evidence replay, Pareto retention, exact allocation, final seal | executing candidates or inventing task meaning |
| Metering package | four named finite-distribution measures | agent, evaluator, optimizer, sandbox, score, deployment |

Ordinary interactive Pi runs with the permissions of its host user and has no
built-in sandbox or command-approval boundary. Project trust controls whether
project resources load; it does not confine built-in tools. Pi extensions and
user/global packages also have host authority, so operators must review or
disable them before a sensitive run. This repository ships one thin project
extension shim for the reviewed implementation. The operator model may differ
from the manifest-pinned worker model; the dashboard labels both identities.
The model-facing action enum cannot supply task text, commands, evaluators,
candidates, output paths, profile paths, or retry authority. It may activate
operator mode without effects, read progress/history, or request a task draft
from user-only session messages; that draft still requires direct operator
review before fixed registration. The instruction to invoke run actions only
after a user request is prompt policy rather than an OS security boundary.

Candidate code and candidate-owned extensions are never loaded into the host Pi.
Nested Pi calls use isolated configuration roots with tools, sessions, skills,
extensions, discovered resources, and ambient context disabled; coding tools
exist only as fixed functions inside the OCI kernel.

## Archive-in/archive-out boundary

The host resolves the exact approved base commit, clones it into disposable
storage, and snapshots only sorted regular files. `.git`, symlinks, devices,
absolute paths, traversal, duplicate paths, noncanonical base64, more than 2,000
files, and more than 8 MiB are rejected. The archive enters the container over
stdin; there is no host mount.

The fixed Docker invocation enforces no image pull, no network, no shared IPC,
no mount, read-only root, bounded `/tmp`, numeric non-root UID/GID, dropped
capabilities, `no-new-privileges`, pids/memory-plus-swap/CPU/file-descriptor/core
limits, and cgroup-v2
observations. Docker absence or observation failure is fatal in a live profile;
there is no host fallback. `process-fixture-v1` is CI-only and requires explicit
unsafe opt-in.

The candidate gets fixed list/read/write/delete/search/run-command helpers.
Paths are normalized relative POSIX paths. Writes must be under reviewed
prefixes. Command execution is argv-only, inside the same no-network container,
with finite time/output bounds. On finish, fixed code enumerates every regular
file, rejects links/devices/disallowed changes/size overflow, computes a content
digest, and sends the complete archive back. Host code validates it again and
creates the child commit; candidates never receive `.git` or a host checkout.

Every development/final check starts a new container and receives a fresh copy
of one immutable commit. Evaluators never reuse mutation-container state. Check
commands are task-profile argv arrays and are not model-generated shell text.

## Failure model

The system fails closed on malformed profiles, missing immutable images,
runtime/model/version mismatch, unsupported dependency locks, container or
cgroup failure, timeout, over-limit output, invalid action, malformed archive,
disallowed path, receipt conflict, Git identity mismatch, stale Population
archive, incomplete task coverage, or replay disagreement.

Population Driver records a durable intent before a model effect. An
indeterminate model call requires explicit retry approval and another finite
reservation. Before that retry, fixed code records the content-addressed
mutation/evaluation effects already present and incorporates its digest into
the next hash-derived attempt identity. Replay uses that snapshot to classify
otherwise-unbound effects as non-selecting retry residue and still requires
exact receipt-set closure. Once a valid Controller receipt exists, resume cannot call the model
again; fixed adaptation and ledger ingestion finish idempotently. Final assay
failure is terminal for that sealed run, not an invitation to search on
protected evidence.

## Final candidate policy

Population's development archive intentionally preserves Pareto tradeoffs and
uniform reproductive allocation. That is appropriate for lineage diversity but
not sufficient for user-facing code selection: a lower-cost failing candidate
can be nondominated. The coding application therefore uses a predeclared
lexicographic final policy:

```text
maximize development task rate
then maximize replicate reliability
then apply the caller's exact rational tie draw over canonical candidate IDs
```

Fixed code maps that chosen candidate back to an exact Population allocation
draw and records both draws and the policy identifier. The protected assay runs
afterward. No resource/task weighted sum, hidden random number, softmax, or final
evidence enters the choice.

## Security properties and residual risks

The implementation is designed to prevent candidate access to host `.git`,
credentials, evaluator files, Docker, host mounts, and network; prevent
out-of-profile persisted writes; and prevent final-data feedback. Tests exercise
traversal, symlinks, disallowed changes, resource bounds, timeout/restart,
receipt tampering, SQLite-free replay, immutable ancestry, and final sealing.

Residual risks include vulnerabilities in Docker, the Linux kernel, Python,
IPython, Git, Pi, or the fixed host code; denial of service within finite host
limits; malicious operator-approved check commands; secrets already committed
inside the approved base tree; and a writer replacing an unsigned complete run
consistently. The profile must not archive credentials or secrets. High-risk
repositories should use a stronger reviewed VM boundary when one is implemented;
VM and remote transports are not silently accepted by this schema.

## Improvement claims

A candidate is “improved” only relative to named evidence under a fixed
experiment. Controller can prove a development pass-count increase for one
pair; the protected assay can show the selected commit passes its withheld
cases. Population's deterministic policy can guarantee only the non-regression
properties explicitly encoded in admission/selection, not universal future
quality.

A Level-2 run that produces descendants and selects a sealed harness proves the
harness-evolution mechanism. If seed and descendants all pass the development
suite, it does **not** prove capability improvement. General evidence requires a
matched study of one-shot, continual single-lineage, and Darwinian treatments
using the same model, tools, task set, checks, tokens/calls/wall budget, and
protected cases. Ordinary Pi remains preferable for simple, weakly evaluated,
or budget-constrained work.
