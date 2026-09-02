# Deterministic Population Archive

`population.py` is a source-only outer control plane around immutable agent
artifacts and trusted evaluation evidence. It does not change the installed
`metering` package, replace the six one-generation applications, execute a
candidate, or install a selected parent.

It implements a bounded subset of the deterministic-search proposal:

- canonical hash-linked candidate, experiment, run, archive, and allocation
  records;
- distinct candidate, experiment, run, replicate, and policy identities;
- development-only Pareto archive construction;
- exact uniform parent allocation from a caller-supplied rational draw;
- typed `agent-skill-v1` recombination with per-path provenance;
- a disposable SQLite query index rebuilt entirely from the canonical ledger;
- named task, safety, forecast-surprisal, novelty, information, reliability, and
  resource evidence without a generic fitness score.

This application itself does not invoke a model. The separate bounded
[Population Driver](../population_driver/README.md) now composes its exact
allocation with Controller mutation/evaluation for Git candidates. Adaptive
mutation, evaluator co-evolution, final-result feedback, deployment, and
unbounded recurrence remain unimplemented.

## Ownership boundary

| Layer | Owner |
|---|---|
| Four finite-distribution measurements | Installed `metering` package |
| Candidate/experiment/run records, archive policy, allocation, index | This source-only application |
| Candidate proposal and execution | Existing applications and external commands |
| Sandbox, evaluator assets, artifact storage, credentials | Caller infrastructure |
| Final evaluation, installation, deployment, rollback | Caller |

The population application is trusted control-plane code. It is not a candidate
and must not be mounted writable inside a candidate workspace. `population.py`
owns the command surface, `contract.py` exposes the narrow public operations
used by outer controls, `population_protocol.py` owns identities and evidence
validation, `population_policy.py` owns Pareto/allocation mathematics,
`population_state.py` owns canonical persistence and replay, and
`population_index.py` owns only derived SQLite facts. Callers do not import the
private policy/state helpers. SQLite and the ledger use Python standard-library
modules only and add no package dependency.

## State

Initialize a caller-selected directory:

```bash
state=/tmp/metering-population
printf '%s\n' '{
  "configuration":{
    "archive_policy":{
      "capacity":8,
      "reliability_kappa":1,
      "type":"pareto-uniform-v1"
    },
    "name":"example"
  },
  "schema_version":1
}' | uv run python apps/population/population.py init "$state"
```

The authoritative state is `population.jsonl`. Its first line binds the
configuration. Every later line contains its sequence, predecessor record ID,
canonical body, and SHA-256 record ID. Replay recomputes candidate, experiment,
run, measurement, archive, and allocation results. A duplicate replicate or a
broken, noncanonical, partial, reordered, or semantically inconsistent record
is rejected rather than repaired.

`population.sqlite` is derived state. Delete it at any time and run:

```bash
uv run python apps/population/population.py rebuild "$state"
uv run python apps/population/population.py verify-index "$state"
```

`verify-index` independently rebuilds the expected relational facts in memory
and rejects any differing row. Archive and allocation decisions replay from the
ledger and never trust SQLite.

A sibling `STATE.lock` directory excludes concurrent writers. Inspect an
abandoned lock before removing it.

## Candidate records

Record an already-normalized default, skill, or Git-backed artifact. A seed has
no parents and a null policy ID:

```json
{
  "artifact":{"artifact_schema":"agent-default-v1"},
  "parents":[],
  "schema_version":1,
  "variation":{"choice":{"source":"baseline"},"policy_id":null,"type":"seed-v1"}
}
```

Submit this to `population.py candidate STATE`. A mutation instead uses
`type: "mutation-v1"`, exactly one existing parent ID, and a lowercase SHA-256
policy ID. The candidate ID remains the existing
`agent-candidate-v1` digest over normalized artifact content; evaluation results
never enter it.

`git-candidate-v1` descriptors are accepted as candidate identity records, but
this application does not resolve or execute them. Use the existing
[`artifacts/git`](../../artifacts/git/README.md) verifier and a reviewed external
executor before recording evidence.

## Experiment and run records

An experiment binds a development or final role, task/evaluator/runtime IDs, a
behavior vocabulary, and finite resource caps:

```json
{
  "experiment":{
    "behavior_space":["direct","exploratory"],
    "budget":{
      "actions":100,
      "energy_millijoules":100000,
      "gpu_milliseconds":100000,
      "memory_bytes":1073741824,
      "storage_bytes":1073741824,
      "tokens":100000,
      "wall_milliseconds":300000
    },
    "case_count":2,
    "evaluator_id":"LOWERCASE_SHA256",
    "information_objective":false,
    "role":"development",
    "runtime_id":"LOWERCASE_SHA256",
    "task_set_id":"LOWERCASE_SHA256"
  },
  "schema_version":1
}
```

Submit it to `population.py experiment STATE`. The returned experiment ID hashes
that complete normalized identity. Every run must report exactly the declared
case count, preventing subset results from being compared as the same
experiment. Declare every final experiment before
recording its first run. The first final-role run seals the ledger against new
candidates, experiments, development runs, archives, allocations, or
recombinations; only additional runs of already declared final experiments and
read-only operations remain valid.

One `population.py run STATE` request has this shape:

```json
{
  "candidate_id":"LOWERCASE_SHA256",
  "evidence":{
    "behavior_distribution":[0.75,0.25],
    "cost":{
      "actions":2,
      "energy_millijoules":20,
      "gpu_milliseconds":0,
      "memory_bytes":1024,
      "storage_bytes":512,
      "tokens":100,
      "wall_milliseconds":50
    },
    "evidence_receipt":{
      "sha256":"LOWERCASE_SHA256",
      "uri":"evidence://development/run-1"
    },
    "information_model":null,
    "protected_passed":true,
    "target_probabilities":[0.8,0.6],
    "task":{"case_count":2,"passed_count":1,"safety_failures":0}
  },
  "experiment_id":"LOWERCASE_SHA256",
  "replicate_id":"replicate-1",
  "schema_version":1,
  "seed":17
}
```

`replicate_id` is a mandatory occurrence identity independent of the optional
seed value. Reusing the same candidate/experiment/replicate tuple is rejected,
including when the runtime remains nondeterministic under the same seed.

The immutable receipt identifies caller-owned detailed evaluator evidence
without placing protected case content in the population ledger. The application
does not fetch or authenticate that URI.

The application recomputes:

- task rate from integer pass and case counts;
- mean target self-information from one pre-reveal target probability per case;
- resource-cap admission from the fixed cost vector;
- survival from protected admission, no safety failure, and budget admission;
- optional information value as Metering mutual information over a declared
  finite prior and outcome/posterior model.

An information model is either null or:

```json
{
  "prior":[0.5,0.5],
  "outcomes":[
    {"probability":0.5,"posterior":[1,0]},
    {"probability":0.5,"posterior":[0,1]}
  ]
}
```

The weighted posteriors must recover the prior. Metering evaluates the resulting
joint distribution's mutual information; the application does not infer a
belief model from observations. An experiment with `information_objective: true`
requires this model on every run and includes the resulting coordinate in Pareto
retention. With `false`, information may still be recorded but cannot silently
change that experiment's objective set.

## Archive and parent allocation

Create a fresh archive over exactly one development experiment:

```json
{"experiment_id":"LOWERCASE_SHA256","schema_version":1}
```

Submit it to `population.py archive STATE`. Final-role experiments are rejected.
Candidates without a run for that experiment are marked unevaluated; candidates
whose runs violate protected, safety, or resource admission are marked
infeasible. Task and log-loss aggregates are weighted by case count; behavior
distributions and optional information values are averaged equally by replicate;
resource coordinates are summed. For each feasible candidate, the application
reports:

- aggregate task rate;
- `mean - kappa * sample_standard_deviation` reliability, with variability
  defined as zero for exactly one replicate;
- mean target surprisal;
- optional mean information value;
- each accumulated resource dimension; and
- directed KL novelty against the nearest *other* feasible candidate.

A sole candidate has defined novelty zero. Self-comparison is never included.
The archive keeps non-dominated candidates across the separately named
objectives. If the Pareto front exceeds configured capacity, a documented
lexicographic novelty/task/reliability/information/loss/cost/content-ID order
truncates it deterministically. This tie policy is application-specific, not a
Metering score.

Allocate one parent by passing the archive record ID and an exact rational draw:

```json
{
  "archive_record_id":"LOWERCASE_SHA256",
  "draw":{"denominator":100,"numerator":42},
  "schema_version":1
}
```

Submit it to `population.py allocate STATE`. Candidates are ordered by immutable
candidate ID and receive equal exact probability `1/n`; index
`floor(numerator * n / denominator)` is selected. The ordering, draw, vector,
and selected identity are committed. An empty, superseded, or evidence-stale
archive cannot allocate a parent.

## Typed recombination

Recombination is deliberately narrower than Git merging. Both parents must be
existing `agent-skill-v1` artifacts. The request selects exactly one parent for
every path in the union of their typed file loci:

```json
{
  "loci":[
    {"parent_candidate_id":"PARENT_A","path":"SKILL.md"},
    {"parent_candidate_id":"PARENT_B","path":"asset.txt"}
  ],
  "parents":["PARENT_A","PARENT_B"],
  "policy_id":"LOWERCASE_SHA256",
  "schema_version":1
}
```

Submit it to `population.py recombine STATE`. Each parent must contribute at
least one locus that differs from the other parent. Replay reconstructs the
complete child and verifies its candidate ID. Git candidates are intentionally
rejected because successful Git merging does not establish semantic
compatibility.

## Queries

After rebuilding, `population.py query STATE` accepts:

```json
{"schema_version":1,"type":"summary"}
{"schema_version":1,"type":"candidates"}
{"candidate_id":"LOWERCASE_SHA256","schema_version":1,"type":"lineage"}
{"archive_record_id":null,"schema_version":1,"type":"archive"}
```

A null archive ID selects the latest archive. Every query verifies the complete
index against a fresh ledger-derived reconstruction first.

## Limits and claims

- The ledger and Git hashes provide identity and accidental-tamper detection,
  not authorship, external timestamping, or protection from a writer who
  consistently replaces all state.
- Runner and evaluator evidence remains caller-owned. This application does not
  prove honest execution or provide a sandbox.
- Final evidence may be recorded for reporting, but its first run permanently
  seals search transitions in that population ledger. It cannot create an
  archive or parent allocation or be returned to a proposer in the same run.
- No selected candidate is executed, installed, merged, served, or deployed.
- Pareto retention and uniform allocation are explicit finite policies, not
  evidence of broad improvement.

See [foundations](docs/foundations.md) for equations, hypotheses, and falsifiers,
and the repository-wide
[deterministic search design](../../docs/deterministic-search-evolution.md) for
the implemented bounded composition and larger parked directions.
