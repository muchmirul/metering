# Source-only control-plane architecture

This page describes the internal software architecture of the repository-local
applications. It does not enlarge Metering's installed API or assign agent,
optimizer, or deployment responsibilities to the package.

“RISC-like” here is a software-design analogy: small orthogonal operations,
explicit load/store boundaries, read-only verification, and thin sequencers. It
is not a claim that these Python applications implement or target the RISC-V
instruction set.

## Invariants

The refactor preserves these boundaries:

- `src/metering/` still owns only the four named information measures, their
  strict JSON command, and opt-in measurement history;
- each application still owns its existing request/response schemas and domain
  policy;
- schema-version-1 ledgers, record IDs, canonical bytes, receipts, retry
  behavior, documented active script paths, and process boundaries remain valid;
- Population ledgers and receipts remain recurrence authority; SQLite remains a
  one-way disposable projection;
- protected final evidence cannot enter proposal feedback, development archives,
  or later scheduling; and
- typed harness candidate execution uses the reviewed source-only OCI profile;
  legacy arbitrary Git execution, tool-enabled proposal, installation, and
  deployment remain caller-controlled operations requiring appropriate isolation.

The architecture intentionally has no plugin registry, event bus, ORM,
dependency-injection container, universal dispatcher, or shared “fitness”
object. Controller, Population, and the two drivers remain separate semantic
owners.

## Mechanical instructions

Only mechanics shared byte-for-byte by multiple source applications live under
`apps/_support/`:

| Module | Operations |
|---|---|
| `wire.py` | strict JSON decode, canonical JSON encode, canonical digest |
| `process.py` | one bounded subprocess call, process-group cleanup, JSON response decode |
| `stdio.py` | one-shot and JSONL standard-stream application boundaries |
| `journal.py` | canonical record identity, predecessor-chain validation, append persistence |
| `durable.py` | directory fsync and atomic canonical checkpoint writes |

These modules do not import a domain application. They supply mechanics, not
policy. Applications import the owning support module directly; there is no
aggregate compatibility facade.

Source directories are importable package namespaces. Internal modules use
package-qualified imports; direct script entry points retain the small
`sys.path` bootstrap needed for documented commands such as:

```text
python apps/controller/controller.py
python apps/population/population.py
python apps/population_driver/population_driver.py
```

## Domain contracts

Cross-application calls use public owner contracts rather than another owner's
private helpers:

- `apps/controller/contract.py` validates and replays one Controller result and
  immutable receipt;
- `apps/population/contract.py` exposes Population initialization, replay,
  lookup, decode, append, and locking operations required by outer controls.

Population policy, protocol, state, and SQLite-index internals remain private to
Population. In particular, Population Driver does not import archive ranking,
allocation-draw, resource, or journal internals and never opens SQLite.

Schema dispatch is similarly explicit. Candidate Runner, Mutator, Forecast
Assay, Selection Gate, and Controller keep fixture-v1 and agent-v2 mechanics in
separate modules behind their unchanged thin command dispatchers. This avoids a
large branch-filled implementation without introducing a generic stage engine.

## Population Driver machine

The stable CLI is a thin dispatcher. Its implementation is split by instruction
type:

| Module | Responsibility |
|---|---|
| `population_driver_protocol.py` | strict request normalization and pure protocol derivations |
| `paths.py` | authoritative path and Population-load operations |
| `population_driver_state.py` | driver journal, pending checkpoint, receipt stores, and locks |
| `receipts.py` | immutable Controller/evidence receipt construction and replay |
| `replay.py` | read-only ledger/receipt replay and cross-ledger verification |
| `planner.py` | pure next-action and stop decision from a replayed view |
| `stopping.py` | pure evaluator-backed development-goal predicate over verified archives |
| `machine.py` | one explicit external effect or Population transition at a time |
| `runtime.py` | bounded load-plan-effect-store sequencing and recovery |
| `population_driver.py` | `run`, `retry`, and `verify` CLI dispatch |

The durable round progression is:

```text
READY
  -> CONTROLLER_INTENT
  -> CONTROLLER_RECEIPT
  -> EVIDENCE_RECEIPT
  -> POPULATION_RECORDS
  -> ROUND_COMMITTED
  -> READY or STOPPED
```

The persisted v1 pending stage names remain
`controller_pending`, `controller_complete`, and `evidence_complete`; the
uppercase names describe the architecture, not a schema migration. Every effect
is preceded by a durable intent or reservation. Replay derives the complete
view from canonical ledgers, receipts, and the optional pending checkpoint.
Planning receives that view and returns one action without writing. Effect code
performs only the selected call or append. A committed-but-not-removed pending
checkpoint is classified by read-only replay and removed explicitly by the
runtime sequencer.

An indeterminate Controller process still requires `retry`; a durable Controller
receipt still prevents another model call; evidence and partial Population
ingestion still resume idempotently. No final-role result is accepted as an
input to a subsequent action.

## Evolutionary Harness machine

`apps/harness` is a concrete Candidate Runner phenotype implementation, not a
seventh semantic owner. Its instruction split is:

| Module | Responsibility |
|---|---|
| `protocol.py` | complete nine-locus candidate validation; no execution |
| `runtime_manifest.py` | canonical model/image/limit/dependency identity |
| `model_contract.py` | one provider-neutral model action call |
| `runtime.py` | bounded context, compaction, tool, recursion, and completion state |
| `kernel_contract.py` | boot/request/interrupt/restart/snapshot sequencer |
| `kernel_server.py` | sandbox-side IPython effect process |
| `resources.py` | external procfs and cgroup-v2 observations |
| `receipts.py` | immutable content-addressed evidence |
| `conformance.py` | fixed lifecycle assay |
| `final_assay.py` | protected one-candidate evidence and Population seal |
| `experiment.py` | thin reference composition and offline verification |

Provider files do not enter this application owner. Pi and Prime Agent
translations under `connectors/fixed/` return one strict action with tools,
sessions, and discovery disabled. The project-local `.pi/extensions/` entrypoint
only re-exports the fixed Pi connector's Agentvolve extension; it does not
move recurrence, evaluation, final tasks, or selection authority into Pi.
Generic clone/content/commit mechanics stay in
`artifacts/git/`. Candidate bootstrap crosses into exactly `kernel_server.py`;
validation and the model connector never import or execute it. In live mode that
server is available only inside the immutable Docker image with no network,
mount, credential, device, capability, or writable root.

A model turn and an IPython execution are separate effects. The loop records
model procfs observations and kernel cgroup-v2 observations, then binds them to
the candidate manifest, runtime, task, transcript, and Population cost vector.
A recursive delegate gets a fresh context and kernel. Finite depth, calls, turns,
code, output, snapshot, model-call, process, memory, storage, CPU, and wall
bounds are validated before or enforced during effects. The CI process profile
uses the same ABI but is explicitly marked unsafe and cannot silently replace
the OCI profile.

The one-command sequencer first runs conformance, then Population Driver, then
loads protected final tasks, records an exact final allocation, declares one
one-use final experiment (which stops Driver recurrence before case execution),
appends its single final run, and invokes existing Population replay. Offline verification
also checks every Git checkout, typed manifest, dependency lock, run receipt,
final bundle, ledger, and permanent seal.

## Agentvolve machine

`apps/coding_agent` is Agentvolve's compatibility-stable narrow outer
composition, not an installed Metering
feature or a replacement for Controller/Population. It adds these instructions:

| Module | Responsibility |
|---|---|
| `protocol.py` | pure canonical `darwinian-coding-task-v1` normalization |
| `harness_workspace_editor.py` | selected-harness checkout and one isolated solution mutation |
| `candidate_runner.py` | fresh-container execution of one immutable solution/check pair |
| `solution_evaluator.py` | immutable execution-receipt loading and replay |
| `evaluator.py` | fresh-container evaluation of Level-2 returned workspaces |
| `evidence_adapter.py` | authenticated Controller traces to Population evidence |
| `final_assay.py` | lexicographic development selection and protected one-use assay |
| `solution_experiment.py` | bounded effects, Git publication, final sealing, and offline replay |

Generic snapshot/path primitives belong to `apps/harness/workspace.py`; generic
clone/content/commit operations remain in `artifacts/git`. Provider invocation
stays in `connectors/fixed/pi/coding_proposer.py`. The coding owner does not
import connectors, and the installed package does not import any source-control
plane.

The mutation effect is archive-in/archive-out. Host code resolves the approved
commit into regular-file records and never mounts its checkout or `.git` in the
kernel. The selected typed harness gets only fixed Docker-side workspace
helpers. The host validates the complete returned archive and creates the child
commit. Independent checks import that commit into new containers using fixed
argv from the caller profile. Solution and harness evolution are separate runs;
the exact sealed harness descriptor is a frozen Level-1 runtime input.

Population continues to own reproductive allocations. The coding final assay
adds one explicit outer deployment-choice policy because Pareto-uniform
allocation may preserve lower-cost failing candidates: maximize development
task rate, then reliability, then consume the caller's rational draw among
canonical-ID ties. It derives a rational Population allocation for that chosen
candidate, records both draws, and replays them offline before any protected
case evidence is accepted. No weighted score or protected evidence participates.

The Pi project extension is trusted host UI only. Its model-facing coding tool
accepts a fixed action enum and uses only an operator-configured absolute task
profile; no task text, evaluator argv, candidate, or output path comes from the
outer model. Candidate actions remain confined to the separately launched OCI
kernel.

## Executable Darwinian recurrence tests

`tests/test_darwinian_code_evolution.py` is the CI-safe minimal end-to-end mechanism
test. It creates a real Git repository and a subtraction seed, then runs two
bounded generations for the public task “return `left + right`”:

1. a descendant commit changes subtraction to addition and is promoted;
2. a descendant changes addition to multiplication and is rejected;
3. exact Population allocation makes the retained addition commit the next
   reproductive parent; and
4. the fresh final development archive contains only that commit.

The test checks Git parentage and content hashes, executes each immutable
`solver.py`, verifies task evidence and Controller decisions, checks the exact
allocation recurrence and Pareto exclusions, and replays the finished state.
Run it with:

```bash
uv run pytest -q tests/test_darwinian_code_evolution.py
```

`darwinian_code_adapter.py` is a deterministic trusted fixture. It executes only
its fixed generated arithmetic programs and is not a sandbox or evidence of
Qwen, Pi, or general problem-solving improvement. `tests/test_harness_evolution.py` additionally exercises the complete typed
harness manifest, recursive subagent context, kernel lifecycle and recovery,
resource receipts, tool-free mutation boundary, provider event translation,
Population recurrence, protected final run, seal, and offline verification. Its
host-process kernel is not a live sandbox. `tests/test_coding_agent.py` additionally evolves and seals a harness
on coding workspaces, creates real immutable solution descendants, retains and
rejects variants under independent checks, selects a development-capable
candidate, performs a protected final assay, emits a patch without modifying the
source, deletes SQLite, and replays every identity. Live typed-harness mutation requires
the checked-in Docker profile, a pinned image/model connector, cgroup-v2
observations, and credentials; withheld final evaluation remains separate.

## Enforced dependency rules

`tests/test_architecture.py` guards the architectural boundary. It rejects:

- non-entry modules that mutate `sys.path`;
- cross-application imports of private symbols;
- Population Driver imports of Population implementation modules;
- SQLite use outside Population's projection;
- duplicate hash-linked journal ownership;
- domain dependencies from shared mechanical support;
- durable store instructions in Population Driver replay; and
- imports from the source control plane into installed Metering core;
- provider imports from the harness or coding-agent application owners;
- candidate `exec`/`eval` effects outside the sandbox-side kernel server; and
- fixed mutator/evaluator/control files inside the reference candidate genome.

These tests protect dependency direction. The documented Population Driver
example additionally checks every authoritative schema-v1 state file against
`tests/fixtures/population-driver-v1-state.sha256.json`, a golden manifest from
the pre-refactor implementation. Protocol and end-to-end tests protect the other
behavioral contracts; neither substitutes for review of trust boundaries or
external sandbox enforcement.
