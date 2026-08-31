# Deterministic variant search

This source-only application adds a population-level layer above Metering's
existing one-generation tools. It is not installed with the `metering` package.
It does not run an agent, estimate probabilities, define intelligence, inspect a
hidden evaluator, or install a selected artifact.

Its boundary is deliberately narrow:

```text
external proposer / Pi / Qwen
        -> immutable candidate
external runner + evaluator
        -> environment-bound evidence vector
variant-search
        -> registry + parentage + active pool + explicit allocation
optional git-recombiner
        -> deterministic two-parent Git child
```

SQLite stores logical population state. Git remains the exact source-artifact
store. Metering's four public measures remain unchanged and are used only when a
named information quantity is required; for example, Variant Search reports the
Shannon entropy of a reproductive distribution.

See [the foundations, claim boundaries, and falsifiers](docs/foundations.md) for
the mathematical and scientific contract.

## Why this boundary exists

The existing Evolution Driver follows one selected head:

```text
parent -> one challenger -> one winner -> repeat
```

That is directed hill climbing. Darwinian search additionally needs:

- a registry containing more than the current winner;
- explicit one- or two-parent heredity;
- environment-bound evaluation vectors;
- a bounded active pool;
- differential future proposal allocation; and
- externally supplied draws so selection remains replayable.

The population tool adds those mechanics without moving model policy or
evaluator authority into Metering.

## State model

For one fixed run law, the logical state is

\[
S_t=(R_t,E_t,P_t,L_t,\Lambda),
\]

where \(R_t\) is the candidate registry and parent graph, \(E_t\) is immutable
environment-bound evidence, \(P_t\) is the active pool and reproductive
distribution, \(L_t\) is a hash-linked event ledger, and \(\Lambda\) is the
caller-declared fixed run law.

The SQLite file is an implementation detail. Its raw bytes are not identity.
`state_id` is the SHA-256 of canonical logical state, while every event binds the
previous event ID:

\[
e_t=\operatorname{SHA256}(\operatorname{CanonicalJSON}(
\text{kind}_t,\text{payload}_t,e_{t-1})).
\]

`verify` checks SQLite integrity, foreign keys, candidate and evidence identities,
parent generations, normalized pool weights, event hashes, and agreement between
the event ledger and materialized tables. This detects inconsistent or
accidentally modified state; it does not authenticate an authorized database
writer.

## Candidate and evidence separation

Candidates reuse the existing `agent-candidate-v1` identity. A registration also
records:

```json
{
  "parents": ["PARENT_ID_0", "PARENT_ID_1"],
  "generation": 4,
  "operator": "git_path_recombination",
  "manifest": {"caller_defined": "heritable state"}
}
```

A seed has no parents and generation zero. A descendant has one or two distinct
registered parents and generation

\[
g(c)=1+\max_{p\in\operatorname{parents}(c)}g(p).
\]

Evidence is never stored as an intrinsic candidate property. It is bound to the
fixed run law and one declared environment:

```json
{
  "candidate_id": "CANDIDATE_ID",
  "environment_id": "coding-suite-v1",
  "metrics": {
    "task_pass_rate": 0.8,
    "latency_seconds": 12.5
  },
  "constraints": {
    "survival": true,
    "protected_files_unchanged": true
  },
  "descriptors": {
    "strategy": "repository-first"
  },
  "resources": {
    "tokens": 4200,
    "gpu_seconds": 18.2
  }
}
```

Selection must name exact evidence IDs. The tool rejects comparisons across
different `environment_id` values and duplicate reports for one candidate. It
never silently chooses the latest report or aggregates unmatched runs.

## Selection mathematics

### Hard survival gate

A required constraint is not a soft score:

\[
\operatorname{eligible}(c)=
\prod_{h\in\mathcal H}\mathbf 1[h(c)=\text{true}].
\]

Failed candidates remain in the registry as evidence and ancestry but cannot
enter the selected pool.

### Multi-objective frontier

For caller-declared metric directions, candidate \(a\) Pareto-dominates \(b\)
when it is no worse on every objective and strictly better on at least one. The
tool returns the non-dominated frontier before scalar tie-breaking.

### Explicit scalarization

When a bounded pool requires one ordering, the caller supplies every metric
weight and direction:

\[
s(c)=\sum_k w_k d_k m_k(c),
\qquad d_k\in\{-1,+1\}.
\]

This is a declared experiment policy, not a repository-defined universal
fitness score. Metric units and weights remain caller responsibilities.

### Reproductive allocation

For retained scores and explicit selection pressure \(\beta\), the initial
reproductive distribution is

\[
p_i=\frac{\exp(\beta(s_i-\max_j s_j))}
{\sum_j\exp(\beta(s_j-\max_k s_k))}.
\]

`beta = 0` is uniform allocation. Larger values increase exploitation. The tool
reports

\[
H(P)=-\sum_i p_i\log_2p_i
\]

through Metering so population collapse remains visible.

A later caller-supplied contribution update uses the finite replicator equation:

\[
p'_{i}=\frac{p_iq_i}{\sum_jp_jq_j},
\qquad q_i\ge0.
\]

The framework applies declared \(q_i\); it does not invent the mapping from task,
safety, novelty, cost, or descendant yield to \(q_i\).

### Explicit parent draws

Parent sampling has no hidden RNG. The caller supplies each draw \(r\in[0,1)\),
and the tool records the distribution and resolved candidate. Two draws select
two distinct parents without replacement and can be passed to the Git
recombiner.

### Population attribution

`population_math.py` also exposes finite weighted mean, variance, covariance,
and the Price-equation accounting identity:

\[
\Delta\bar z=
\frac{\operatorname{Cov}(w,z)}{\mathbb E[w]}
+
\frac{\mathbb E[w\Delta z]}{\mathbb E[w]}.
\]

The returned terms are `allocation_effect` and `change_effect`. This separates
change associated with giving more attempts to existing variants from change in
their descendants. It is an accounting identity, not causal proof.

## Command

Every invocation applies one strict JSON operation:

```bash
uv run python apps/variant_search/variant_search.py \
  --database /tmp/metering-population.sqlite3
```

### Initialize one fixed run law

```json
{
  "schema_version": 1,
  "operation": "initialize",
  "law": {
    "runner": "pi-qwen27b-llamacpp-v1",
    "evaluator": "sealed-coding-suite-v1",
    "budget": "r9700-local-v1"
  }
}
```

### Register a seed or descendant

```json
{
  "schema_version": 1,
  "operation": "register_candidate",
  "candidate": {"artifact": {}, "candidate_id": "LOWERCASE_SHA256"},
  "parents": [],
  "generation": 0,
  "operator": "seed",
  "manifest": {}
}
```

A recombined child supplies exactly two parent IDs and the next valid generation.

### Record one evaluation

```json
{
  "schema_version": 1,
  "operation": "record_evaluation",
  "candidate_id": "LOWERCASE_SHA256",
  "environment_id": "coding-suite-v1",
  "metrics": {"task_pass_rate": 0.8, "latency_seconds": 12.5},
  "constraints": {"survival": true},
  "descriptors": {"strategy": "repository-first"},
  "resources": {"tokens": 4200}
}
```

### Select a pool and one or two parents

```json
{
  "schema_version": 1,
  "operation": "select",
  "evidence_ids": ["EVIDENCE_SHA256_A", "EVIDENCE_SHA256_B"],
  "objectives": [
    {"metric": "task_pass_rate", "direction": "maximize", "weight": 1.0},
    {"metric": "latency_seconds", "direction": "minimize", "weight": 0.01}
  ],
  "required_constraints": ["survival"],
  "pool_size": 8,
  "beta": 2.0,
  "parent_draws": [0.15, 0.72]
}
```

### Apply explicit contribution factors

```json
{
  "schema_version": 1,
  "operation": "reallocate",
  "contribution_factors": {
    "CANDIDATE_SHA256_A": 1.0,
    "CANDIDATE_SHA256_B": 1.5
  },
  "parent_draws": [0.4]
}
```

### Inspect or verify

```json
{"schema_version":1,"operation":"snapshot"}
```

```json
{"schema_version":1,"operation":"verify"}
```

## Git recombination

`artifacts/git/git_recombiner.py` consumes two complete `git-candidate-v1`
candidates and an explicit `path_sources` map. Files unique to either parent are
inherited automatically. Identical paths are inherited from parent zero. Every
path whose bytes or executable mode conflict must explicitly choose parent zero
or one.

The tool creates a deterministic two-parent commit using fixed commit metadata,
publishes it beneath `METERING_GIT_REF_PREFIX`, recomputes the portable content
digest, and returns the normalized child plus complete path provenance. It does
not run tests or decide retention.

Path-level recombination is intentionally mechanical. A syntactically valid Git
tree can still be a broken program. Run the child through the existing trusted
runner, evaluator, assay, and selection boundaries before registration or
promotion.

## Security and evaluation boundary

SQLite is not a sandbox. Git hashes are not a sandbox. Process separation is not
a sandbox. Run untrusted candidate code and model-driven workspace edits inside
a reviewed container or VM with protected evaluator assets mounted outside the
candidate boundary.

The development evaluator may feed bounded evidence into selection. A final
holdout must remain outside the database and outside all reproductive feedback.
Otherwise stronger search can optimize the evaluator instead of the intended
capability.
