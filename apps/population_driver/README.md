# Bounded Population Driver

`population_driver.py` is the source-only outer orchestrator that connects the
implemented Population Archive to the existing one-generation Controller:

```text
fresh Pareto archive
  -> exact parent allocation
  -> one Git-code mutation proposal
  -> matched parent/child Controller evaluation
  -> immutable evidence receipts
  -> Population candidate and replicate records
  -> fresh Pareto archive
  -> next exact allocation
```

It activates only bounded automatic population execution. It does not adapt the
mutation policy, recombine Git candidates, train model weights, evolve an
evaluator, provide a sandbox, consume final evidence, install a selected
candidate, or deploy one. Qwen, Pi, or another fixed proposer remains the
mutation operator; immutable Git candidate content is the evolving genome.

The driver is excluded from the installed package. It adds no dependency and
does not change Metering's four-measure Python API, CLI, lockfile, or wheel.

## Ownership

| Fact or transition | Owner |
|---|---|
| One mutation, matched execution/evaluation, pairwise report | Existing Controller and its six applications |
| Candidate/run identities, named evidence, Pareto archive, exact allocation | Population Archive |
| Round bounds, proposal-call approval, receipts, replay, composition | Population Driver |
| Candidate resolution/execution isolation, credentials, physical resource enforcement | Caller-provided runner, or the concrete typed `apps/harness` OCI profile |
| Mutation implementation, such as fixed Pi/Qwen over a Git workspace | Caller-provided proposer connector |
| Withheld final evaluation, installation, deployment, rollback | Caller |

Controller's `next_parent` remains an authenticated result of its pairwise
selection policy, but it does **not** choose the next population parent. After
both Controller reports become Population runs, Population Archive recomputes
the multi-objective Pareto set and its exact allocation record chooses the next
parent. No scalar fitness or intelligence score is introduced.

## Instruction architecture

The schema-version-1 durable records and CLI identifiers are unchanged. The
request now admits one optional, versioned evaluator-backed stopping policy;
requests that omit it retain limit-only behavior. Implementation ownership is
explicit: `replay.py` performs read-only ledger/receipt verification,
`planner.py` returns one pure next action, `stopping.py` evaluates only verified
development archives, `machine.py` owns external effects and Population
transitions, `population_driver_state.py` owns durable stores, and
`runtime.py` is the bounded load-plan-effect-store sequencer.
`population_driver.py` is the thin `run|retry|verify` dispatcher.
Population access goes through `apps.population.contract`; no driver module
imports Population policy, state, allocation, or SQLite internals.

The durable progression is intent -> Controller receipt -> evidence receipt ->
Population records -> committed round. Existing pending-stage strings and all
canonical identities remain schema version 1. A stale checkpoint left after a
committed round is recognized without a verifier write and removed explicitly
by the runtime under the driver lock. See the repository
[source-only architecture](../../docs/source-architecture.md).

## Deterministic protocol demonstration

From the repository root:

```bash
rm -rf /tmp/metering-population-driver /tmp/metering-population-driver.lock
uv run python apps/population_driver/population_driver.py \
  run /tmp/metering-population-driver \
  < apps/population_driver/example-request.json
uv run python apps/population_driver/population_driver.py \
  verify /tmp/metering-population-driver < /dev/null
```

The checked-in `demo_adapter.py` is a non-executing protocol test double. It
constructs Git-shaped immutable code descriptors and synthetic evidence; it is
not a sandbox, a Git verifier, a model run, or empirical adaptation evidence.
For arbitrary code evolution, use the reviewed
[Git artifact bridge](../../artifacts/git/README.md), a fixed Pi/Qwen proposer,
and a caller-isolated runner/evaluator. For the repository-complete typed
prompt/context/tool/subagent/IPython candidate, use the
[Evolutionary Harness](../harness/README.md), which supplies the concrete Docker
profile, receipts, final assay, and offline verifier behind this unchanged
Driver contract.

## Executable Git recurrence test

The deterministic end-to-end test uses real immutable Git commits and executes a
specific arithmetic candidate task:

```bash
uv run pytest -q tests/test_darwinian_code_evolution.py
```

It begins with a subtraction solver, retains a child implementing addition,
uses that archived child as the next exact Population parent, rejects a
multiplication regression, and verifies the final archive and all ledgers. The
checked-in `darwinian_code_adapter.py` generates only those trusted fixture
programs. This proves the mutation/evaluation/allocation recurrence for that
case; it is neither a sandbox nor evidence of general agent or Qwen improvement.

## Run request

`run STATE` reads one strict schema-version-1 JSON object. The complete example
is [`example-request.json`](example-request.json). Its top-level fields are:

- `initial_parent_artifact`: one normalized `git-candidate-v1` descriptor;
- `proposal`: fixed proposer command, timeout, and caller-approved context;
- `generation`: Controller evaluation ID, tasks, runner, evaluator, and explicit
  pairwise selection policy;
- `population.configuration`: Pareto capacity, reliability coefficient, and
  population name;
- `population.development`: behavior vocabulary, positive per-candidate resource
  budget, and a content-derived runtime identity that binds model, connector,
  sandbox, and execution settings;
- `evidence_adapter`: trusted command that supplies only behavior distribution,
  protected admission, resource observations, and run seed metadata;
- `allocation_draws`: exactly `max_rounds - 1` rational draws in the Population
  Archive format;
- optional `stopping`: `all-development-cases-pass-v1` plus a positive
  `minimum_replicates`; and
- `limits`: positive round, proposal-call, global timeout-reservation, and
  resource limits.

The driver derives rather than accepts the development experiment's case count,
evaluator ID, and task-set ID. The evaluator ID hashes its exact command. The
task-set ID hashes the evaluation label and normalized public task array. The
experiment role is always `development` and its information objective is always
false, preventing request fields from relabeling final evidence as search input.

A worded objective belongs in `proposal.context`; it guides mutation but cannot
self-certify completion. With the optional stopping policy, recurrence ends only
when the latest independently computed development archive contains a feasible
candidate whose accumulated public cases all pass for at least the configured
replicate count. The status is `development_goal_reached`. `max_rounds` remains
mandatory and finite, so this is goal-or-limit stopping rather than an unbounded
natural-language loop. The policy suppresses the otherwise unused next-parent
allocation when the goal is reached. It never reads protected-final evidence.
Concrete Level-1 configuration examples are in the [Agentvolve stopping-policy
guide](../../docs/coding-agent/stopping.md).

Only ordinary Git candidates are accepted in this first schema. Controller must
return a different normalized Git child. If a proposer reproduces a Git
candidate already known to the population, the driver records the new replicate
runs and mutation attempt in its round receipt without rewriting that
content-identified candidate's original lineage record.

## Evidence adapter

After Controller returns and its canonical receipt is durable, the driver sends
the configured evidence adapter:

```json
{
  "controller_receipt":{"sha256":"...","uri":"population-driver-receipt:///..."},
  "controller_result":{},
  "experiment":{"experiment_id":"...","specification":{}},
  "protocol_version":1,
  "round":1
}
```

The exact response is:

```json
{
  "candidates":[
    {
      "behavior_distribution":[0.75,0.25],
      "candidate_id":"LOWERCASE_SHA256",
      "cost":{
        "actions":1,
        "energy_millijoules":1,
        "gpu_milliseconds":1,
        "memory_bytes":1,
        "storage_bytes":1,
        "tokens":1,
        "wall_milliseconds":1
      },
      "protected_passed":true,
      "seed":{"runtime_draw":17}
    },
    {
      "behavior_distribution":[0.25,0.75],
      "candidate_id":"LOWERCASE_SHA256",
      "cost":{
        "actions":1,
        "energy_millijoules":1,
        "gpu_milliseconds":1,
        "memory_bytes":1,
        "storage_bytes":1,
        "tokens":1,
        "wall_milliseconds":1
      },
      "protected_passed":true,
      "seed":{"runtime_draw":17}
    }
  ],
  "protocol_version":1
}
```

There must be exactly one entry for the incumbent and one for the challenger.
The adapter cannot change task counts, pass/safety results, target
probabilities, candidate IDs, evaluator identity, or Controller selection; the
driver validates and copies those facts directly from the Controller receipt.
Population Archive authoritatively checks behavior normalization, cost shape,
resource feasibility, named measurements, and archive replay.

The evidence adapter is trusted composition code, not candidate code. Detailed
case evidence stays in the immutable Controller receipt. The subsequent
immutable evidence-adapter receipt embeds that Controller-bound request and the
adapter response; each Population run references this combined receipt.
Protected final cases must never be placed in this request,
Controller task list, or adapter.

## Bounds

The limits are deterministic scheduling limits rather than claims that Python
can undo physical work:

- `max_rounds` bounds completed mutation/evaluation/archive rounds and supports
  numeric limits such as 100;
- `max_proposal_calls` bounds initial attempts plus explicitly approved retries;
- `max_wall_seconds` bounds the sum of configured Controller and evidence-adapter
  timeout **reservations** across the durable run, including failed attempts;
- `max_total_candidate_cost` admits a new round only if current recorded cost
  plus twice the experiment's per-candidate budget fits every resource
  coordinate.

The runner sandbox and proposer connector must enforce their declared physical
budgets. If observed evidence exceeds an experiment budget, Population Archive
retains it as infeasible evidence; software cannot retroactively prevent the
already consumed resource. The driver will not schedule a later round whose
preflight bound fails.

An evaluator-verified development goal, empty archive, any configured limit, or
declaration of the first final-role experiment stops new rounds. Its first run
activates the broader Population seal. Allocation draws are explicit request inputs; no hidden random-number
generator or SQLite query affects scheduling.

## State and interruption recovery

A state directory contains:

```text
STATE/
  driver.jsonl
  population/
    population.jsonl
    population.sqlite       optional, disposable, never read by the driver
  pending/
    round-intent.json        present only during an incomplete round
  receipts/
    ATTEMPT.controller.json
    ATTEMPT.evidence.json
```

`driver.jsonl`, `population/population.jsonl`, immutable receipts, and a pending
intent are authoritative. Every completed driver round is canonical,
hash-identified, predecessor-linked, and cross-references the exact Population
candidate, run, archive, and allocation records. `verify` replays both ledgers,
receipt digests, Controller reports and selection, parent recurrence, and
cross-ledger identities. It never opens `population.sqlite`; that file may be
missing, stale, corrupt, or rebuilt only when queries are needed.

A round intent is written atomically before Controller starts. Controller output
is validated and written as an immutable receipt before the evidence adapter or
Population transition. Population ingestion is prefix-checked and idempotent,
so an interruption between its records and the completed driver record resumes
without another model call.

If no valid Controller receipt exists, ordinary `run` returns
`"status":"pending_round"` and never silently repeats the possibly completed
model call. Inspect the pending error and approve exactly one retry:

```bash
printf '%s\n' \
  '{"intent_id":"LOWERCASE_SHA256","reason":"operator approved another model call","schema_version":1}' \
  | uv run python apps/population_driver/population_driver.py \
      retry /tmp/metering-population-driver
```

The intent ID must match pending state. A retry authorizes only that pending
Controller attempt and consumes another proposal-call and Controller-timeout
reservation. After it succeeds, any later rounds remain governed by the bounds
and draws preapproved in the original request. If Controller is already durable but the
evidence adapter failed, `run` resumes the adapter and Population ingestion
without repeating proposal or evaluation.

A sibling `STATE.lock` excludes concurrent driver transitions. Population
Archive retains its own lock for its shorter ledger transitions. Caller code
must inspect abandoned locks and pending intents rather than deleting them
blindly. Malformed command/request input exits with status 2 and
`invalid_request`; invalid state, receipt, or composition exits with status 2
and `population_driver_error`. A recoverable indeterminate call is valid state,
so it returns a successful summary with `status: pending_round` instead.

## Final evidence and trust boundary

The driver creates and archives only one derived development experiment. A
caller may later declare final experiments directly in
`STATE/population/population.jsonl` through Population Archive. Declaring the
first final experiment stops Driver recurrence immediately, before protected
case execution; recording its first final run then activates Population's
permanent seal over candidate, development-run, archive, allocation, and
recombination transitions. Subsequent `run` calls return
`final_evidence_sealed`; no final result is placed in proposer feedback or a
search archive.

Commands execute with the caller's permissions. Process-group cleanup, strict
JSON, path validation, locks, timeouts, and Git hashes are not a security
sandbox. Real candidate execution and tool-enabled proposal require an
externally reviewed container or VM that isolates files, secrets, network,
devices, processes, and resources. Receipt hashes prove byte identity and local
integrity, not honest execution, authorship, correctness, or broad improvement.

See [foundations](docs/foundations.md) for the recurrence, hypotheses, and
falsifiers and the repository-wide
[deterministic search design](../../docs/deterministic-search-evolution.md) for
the larger boundary.
