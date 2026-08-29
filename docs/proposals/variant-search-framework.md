# Variant Search Framework Proposal

## Status

This document is a **non-normative, unimplemented design proposal**. It does not
change the accepted scope in [`PLAN.md`](../../PLAN.md), the installed
`metering` package, any application protocol, or any runtime behavior.

The proposal targets the repository architecture on `main`: Metering provides
four deterministic information measures; repository-local applications perform
one evidence-gated parent-versus-challenger generation; the optional Evolution
Driver repeats the selected head under explicit limits; and the Git artifact
bridge binds immutable source and external-output variants.

The purpose of this proposal is to specify the missing framework **above** those
boundaries for population-style, branching, evidence-aware variant search. It
uses developer-familiar terminology even where evolutionary theory motivates the
design.

## Summary

The current repository already supplies a strong deterministic unit of
adaptation:

```text
selected parent
    -> propose one challenger
    -> execute parent and challenger under matched controls
    -> obtain independent task and safety evidence
    -> retain exactly one candidate
    -> return next_parent
```

That unit is sufficient for a single selected lineage. It is not yet a complete
population-style search system because it has no branching candidate registry,
active candidate pool, explicit parent-allocation distribution, structured
variant manifest, environment-bound characteristic map, or population-level
change attribution.

The proposed framework adds those responsibilities without moving policy,
interpretation, or stochasticity into Metering:

```text
Git variants + canonical JSON manifests
                  |
                  v
        candidate registry (all accepted variants)
                  |
                  v
          active candidate pool
                  |
       explicit parent weights + draw
                  |
                  v
      existing one-generation applications
                  |
                  v
 matched evaluation + effect + uncertainty
                  |
                  v
 deterministic state reducer and event ledger
```

## Developer terminology

The design keeps biological terms in the theory section and uses ordinary
software vocabulary in code and protocols.

| Theory term | Developer-facing term |
|---|---|
| genome / DNA | `variant_manifest` |
| gene / locus | `setting` |
| allele | `value` |
| mutation | `change` |
| phenotype | `evaluation_result` |
| fitness | `evaluation_vector` |
| population | `candidate_pool` |
| reproductive allocation | `parent_weight` |
| archive | `candidate_registry` |
| lineage | `version_graph` |
| niche | `behavior_bucket` |
| evolution driver | `variant_search` |
| evolvability | `proposal_yield` |
| environment | `task_suite` or `runtime_context` |

The documentation may state the evolutionary analogy, but public schemas should
not require developers to think in biological vocabulary.

## Design goals

1. Reuse the existing deterministic generation boundary rather than replace it.
2. Use Git commits and content hashes for exact executable/source variants.
3. Use canonical JSON for the semantic configurable state of each variant.
4. Keep measured characteristics separate from declared configuration.
5. Preserve multiple useful branches and stepping stones.
6. Allocate proposal opportunities explicitly and replayably.
7. Evaluate parent and challenger under matched controls.
8. Report effect size, uncertainty, safety, cost, and calibration separately.
9. Keep hard constraints and evaluator authority outside candidate control.
10. Make every state transition replayable from content-identified inputs.
11. Keep the installed `metering` package free of search policy and agent state.
12. State mathematical identities, implementation hypotheses, and empirical
    hypotheses separately.

## Non-goals

This proposal does not define:

- a universal fitness scalar;
- a hidden random-number generator;
- a model-provider SDK or generic agent class;
- an evaluator plugin framework;
- automatic installation, merge, serving, or deployment;
- unrestricted self-modification of the evaluator or control plane;
- a claim that entropy, novelty, or diversity alone implies capability;
- a database, event bus, dashboard, or distributed scheduler;
- automatic environment generation in the first implementation phase;
- crossover or multi-parent recombination in the first implementation phase;
- changes to the four public Metering measures.

## Existing boundaries to preserve

| Existing component | Responsibility retained |
|---|---|
| `metering` | Validate caller-supplied finite probability models and evaluate self-information, entropy, KL divergence, and mutual information |
| `metering-history` | Record accepted measurement request/response pairs in one local linear ledger |
| Mutator / proposer | Produce one explicit challenger artifact |
| Candidate Runner | Execute parent and challenger through the same declared adapter boundary |
| Observer / evaluator | Reveal protected task results only after submissions and forecasts exist |
| Forecast Assay | Recompute named forecast measurements and bind task evidence |
| Selection Gate | Apply one explicit pairwise task/safety retention policy |
| Controller | Enforce ordering and identity within one generation |
| Evolution Driver | Repeat one selected head under explicit limits |
| Git artifact bridge | Bind immutable source commits, trees, content hashes, entrypoints, and external-output receipts |

The new framework treats one completed Controller result as one **birth event** in
the theory, but should call it a `completed_change` or `candidate_event` in code.

## Core state model

Let the complete framework state be

\[
S_t =
\left(
R_t,\,
P_t,\,
W_t,\,
B_t,\,
L_t,\,
\Lambda_t
\right),
\]

where:

- \(R_t\) is the candidate registry containing all accepted variants;
- \(P_t \subseteq R_t\) is the bounded active candidate pool;
- \(W_t\) is the declared parent-allocation distribution;
- \(B_t\) is the behavior-bucket map;
- \(L_t\) is the append-only event ledger;
- \(\Lambda_t\) identifies the relatively fixed law: schemas, evaluator
  contract, runtime constraints, and reducer version.

A completed external event \(U_t\) contains all data not generated by the pure
state reducer: the explicit parent draw, proposer output, Git candidate,
evaluation evidence, resource evidence, and pairwise verdict.

The framework transition is

\[
\boxed{
S_{t+1} = F_{\Lambda_t}(S_t, U_t)
}
\]

`F` must be deterministic. External agent behavior may be stochastic, but its
output is content-addressed before reduction. The reducer must never call a
model, inspect hidden tests, generate randomness, execute candidate code, or
choose an objective.

## Fixed law and configurable state

A candidate should be interpreted as

\[
\boxed{
A_i = (\lambda, C_i, V_i)
}
\]

where:

- \(\lambda\) is the fixed runtime and evaluation law for the current run;
- \(C_i\) is the immutable Git-backed candidate;
- \(V_i\) is its canonical JSON variant manifest.

The same source and manifest under a different runtime law is a different
experimental candidate. A run-level `law_id` should bind at least:

```text
schema versions
evaluator identity
runner identity
sandbox and permission policy
task-suite identity
resource-budget contract
selection/comparison policy
state-reducer version
```

A change to this law starts a new run or an explicitly versioned migration. It
must not silently continue the old evidence lineage.

## Git as exact variant tracking

Git should own the exact executable and source variant:

```text
repository
commit
tree
portable content SHA-256
entrypoint
external output receipts
parent commit(s)
```

The existing `git-candidate-v1` contract already supplies most of this boundary.
Branches remain navigation and publication conveniences; immutable commit,
tree, portable content digest, and output hashes remain authoritative identity.

For a one-parent change:

```text
child commit parent = selected parent commit
```

A later recombination phase may allow multiple Git parents, but only after stable
setting and innovation identities exist. Git ancestry alone is not sufficient
to explain the semantic change; that is the responsibility of the JSON manifest
and change record.

## Canonical JSON variant manifest

Every framework-compatible Git candidate should contain:

```text
.metering/variant.json
```

The first schema should be intentionally small and explicit:

```json
{
  "schema_version": 1,
  "modules": [
    {
      "module_id": "strategy",
      "settings": [
        {
          "setting_id": "strategy.instructions",
          "kind": "git_path",
          "value": {
            "path": "SKILL.md",
            "sha256": "LOWERCASE_SHA256"
          }
        },
        {
          "setting_id": "strategy.max_steps",
          "kind": "integer",
          "value": 12
        }
      ]
    }
  ],
  "connections": [
    {
      "innovation_id": "LOWERCASE_SHA256",
      "source": "memory",
      "target": "strategy",
      "role": "provides_context",
      "enabled": true
    }
  ]
}
```

This is illustrative protocol material, not implementation code.

### Manifest invariants

- JSON parsing rejects duplicate keys and non-finite numbers.
- The normalized form is canonical and content-addressed.
- `module_id`, `setting_id`, and `innovation_id` are stable identifiers.
- Arrays with semantic set meaning have one documented canonical order.
- Every referenced Git path exists in the exact candidate tree.
- Every referenced content hash matches that tree or external receipt.
- The manifest does not contain measured claims such as `"debugging": 0.9`.
- A candidate ID binds the Git artifact, manifest ID, and run law ID.
- The candidate cannot expand its own permission ceiling through manifest data.

The manifest identity is

\[
\operatorname{manifest\_id}
=
\operatorname{SHA256}
\left(
\operatorname{CanonicalJSON}(V_i)
\right).
\]

The framework candidate identity is conceptually

\[
\operatorname{framework\_candidate\_id}
=
H\left(
\operatorname{git\_candidate\_id},
\operatorname{manifest\_id},
\operatorname{law\_id}
\right).
\]

The existing application identity formulas should remain unchanged. This
framework identity is an additional source-only composition identity, not a
replacement for `git-candidate-v1`.

## Semantic change records

Git provides exact file history. A separate JSON record states the intended
semantic transition:

```json
{
  "schema_version": 1,
  "parent_candidate_ids": ["PARENT_ID"],
  "child_candidate_id": "CHILD_ID",
  "operator": "replace_value",
  "changes": [
    {
      "setting_id": "strategy.max_steps",
      "before": 8,
      "after": 12
    }
  ],
  "proposal_id": "PROPOSAL_ID",
  "proposal_policy_id": "POLICY_ID",
  "change_id": "CHANGE_ID"
}
```

The validator should confirm:

1. every parent and child candidate exists and is content-valid;
2. declared `before` values match parent manifests;
3. declared `after` values match the child manifest;
4. the Git tree difference is compatible with referenced path changes;
5. no undeclared manifest setting changed;
6. the record is canonical and content-addressed.

A record is an assertion about structure, not proof that the change caused an
observed improvement.

## Evaluation results are not configuration

A measured characteristic must bind the candidate to the exact experimental
context:

```json
{
  "schema_version": 1,
  "candidate_id": "CANDIDATE_ID",
  "manifest_id": "MANIFEST_ID",
  "law_id": "LAW_ID",
  "task_suite_id": "TASK_SUITE_ID",
  "evaluator_id": "EVALUATOR_ID",
  "budget_id": "BUDGET_ID",
  "case_results": [],
  "metrics": {
    "passed_count": 18,
    "case_count": 20,
    "safety_failures": 0,
    "token_count": 4210,
    "tool_call_count": 9
  },
  "evidence_id": "EVIDENCE_ID"
}
```

The candidate may forecast its own outcomes, but it cannot author trusted task
results, safety results, or resource evidence.

For a matched parent \(p\), challenger \(c\), and task suite \(E\), the effect is

\[
\boxed{
\Delta\boldsymbol{\phi}_{E}
=
\boldsymbol{\phi}(c,E)
-
\boldsymbol{\phi}(p,E)
}
\]

This effect is local to the declared law, task suite, evaluator, and budget. It
must not be promoted into a universal property of the variant.

## Missing evaluation mathematics

Metering currently answers questions about surprise, uncertainty, distribution
difference, and dependence. Population-style variant search additionally needs
finite moments, paired effect estimation, proper scoring alternatives,
multi-objective comparison, and population-change attribution.

These should first live in the source-only framework. They should not be added
to the installed Metering API without a separate versioned scope decision.

### Weighted mean

\[
\mu_x = \mathbb E_p[x] = \sum_i p_i x_i
\]

Use cases:

- expected task success under a declared task distribution;
- expected latency, tokens, or cost;
- average characteristic under parent-allocation weights.

### Weighted variance

\[
\operatorname{Var}_p(x)
=
\sum_i p_i(x_i-\mu_x)^2
\]

Use cases:

- instability across tasks or environments;
- variability of resource cost;
- sensitivity of a variant characteristic.

Variance is not an improvement score. A low variance candidate can be
consistently bad.

### Weighted covariance

\[
\operatorname{Cov}_p(x,y)
=
\sum_i p_i(x_i-\mu_x)(y_i-\mu_y)
\]

Use cases:

- whether proposal allocation is associated with a characteristic;
- cost-capability trade-offs;
- correlations among observed change effects.

Covariance reports association under the declared weights, not causation.

### Price-style change attribution

For characteristic \(z_i\), parent contribution \(w_i\), and average descendant
change \(\Delta z_i\),

\[
\boxed{
\Delta\bar z
=
\frac{\operatorname{Cov}(w,z)}
{\mathbb E[w]}
+
\frac{\mathbb E[w\Delta z]}
{\mathbb E[w]}
}
\]

Developer-facing output names should be:

```text
allocation_effect
change_effect
total_delta
```

Interpretation:

- `allocation_effect`: did variants already possessing a characteristic receive
  more future proposal opportunities?
- `change_effect`: did children change the characteristic relative to parents?
- `total_delta`: did the candidate pool mean change?

This is an assay and attribution operation, not a selection policy.

### Brier score

The current system already uses logarithmic score through realized
self-information. A useful bounded companion for a complete categorical
forecast \(q\) and realized class \(y\) is

\[
BS(q,y)
=
\sum_k
\left(q_k-\mathbf 1[k=y]\right)^2.
\]

Log score strongly penalizes assigning near-zero probability to the realized
outcome. Brier score measures squared probability error. The framework should
report both separately rather than combining them into one score.

### Paired effect and uncertainty

Parent and challenger must be compared on matched cases. For a metric \(m\),

\[
d_i=m_i(c)-m_i(p),
\qquad
\bar d=\frac1n\sum_i d_i,
\]

\[
s_d^2
=
\frac1{n-1}\sum_i(d_i-\bar d)^2.
\]

Report at minimum:

```text
case_count
mean_delta
delta_variance
wins
ties
losses
```

An optional deterministic paired bootstrap may use caller-supplied resampling
indices. The framework must not hide a random-number generator or silently
choose confidence levels.

### Constraint-first Pareto comparison

An agent evaluation is a vector, not naturally one scalar:

\[
\mathbf m(c)
=
(\text{task},\text{safety},\text{cost},\text{latency},\text{calibration},\ldots).
\]

After hard constraints, \(a\) dominates \(b\) when

\[
m_k(a)\ge m_k(b)\quad\forall k
\]

and

\[
m_j(a)>m_j(b)\quad\text{for at least one }j,
\]

after each metric is oriented so that larger means preferred.

Recommended comparison ordering:

```text
1. reject invalid evidence or identity
2. reject hard-constraint failure
3. reject declared safety regression
4. prefer a Pareto-dominating candidate
5. retain both when each is better on a different objective and pool capacity permits
6. use a caller-declared tie rule only when one winner is required
```

### Parent-weight update

The active candidate pool needs an explicit distribution over future proposal
opportunities. A simple declared update is

\[
p_i'
=
\frac{p_iw_i}{\sum_jp_jw_j},
\]

where the framework validates and applies the update, while the caller defines
how evidence maps to nonnegative \(w_i\).

Metering can already report:

\[
H(P_t)
\]

for concentration of proposal allocation and

\[
D_{\mathrm{KL}}(P_{t+1}\Vert P_t)
\]

for allocation shift.

### Coverage and dependence

For caller-declared behavior buckets,

\[
\operatorname{coverage}
=
\frac{\text{occupied buckets}}{\text{declared buckets}}.
\]

Existing Metering measures can report:

- entropy of bucket occupancy;
- mutual information between candidate identity and task-suite success;
- mutual information between change categories and discretized effect
  categories;
- KL change in proposal or change-policy distributions.

These are diagnostics. High diversity or mutual information does not by itself
establish useful capability.

## Candidate registry

The candidate registry stores every accepted and structurally valid variant,
not only the current selected head.

A registry entry should bind:

```text
candidate ID
Git artifact identity
manifest ID
law ID
parent candidate IDs
birth/change record ID
evaluation evidence IDs
behavior-bucket IDs
active/retired status
```

The registry must support multiple children from one parent. It may later support
multiple parents, but one-parent changes are the first accepted scope.

A rejected or failed challenger may be recorded in the event ledger for audit
without becoming an accepted registry member. The exact retention rule must be
declared; the framework must not silently discard failure evidence needed to
diagnose proposal quality.

## Active candidate pool

The active pool is a bounded set of candidates eligible for future proposal:

\[
P_t \subseteq R_t.
\]

It is separate from the registry:

- registry membership means the variant and evidence are retained;
- pool membership means the variant currently receives search resources.

Pool state includes:

```text
candidate IDs
capacity
parent weights
behavior-bucket occupancy
activation reason
retirement reason
```

A deterministic parent selection event contains:

```text
normalized parent-weight distribution
explicit draw in [0, 1)
selected candidate ID
distribution entropy
selected-outcome surprisal
```

The framework verifies the selection. The caller or higher-level policy supplies
the weights and draw.

## Behavior buckets and stepping stones

A global-best-only pool risks premature convergence. The framework should allow
caller-defined behavior descriptors such as:

```json
{
  "task_family": "debugging",
  "cost_band": "low",
  "tool_pattern": "repository-first"
}
```

The first implementation should:

- validate the descriptor schema;
- derive a stable bucket ID;
- track occupancy and coverage;
- allow a local retained candidate per bucket;
- keep global task evidence separate from bucket membership.

The framework does not invent behavior dimensions. Poor dimensions can preserve
irrelevant diversity and are an external modeling risk.

## Proposal-yield tracking

The system should measure whether a proposal policy produces useful changes.

For a proposal policy \(q\), record:

```text
attempted changes
structurally valid changes
evaluation-complete changes
accepted changes
hard failures
safety failures
mean effect vector
effect variance
```

A useful initial diagnostic is

\[
\operatorname{proposal\_yield}
=
\frac{\text{accepted changes}}{\text{completed proposals}},
\]

reported together with counts and matched effect distributions. This ratio must
not become a universal objective: a policy generating rare major stepping
stones may have low short-run yield.

A later phase may make proposal-policy settings part of the variant manifest.
That transition should occur only after change records and effect evidence are
reliable.

## Environment and task-suite evolution

The first framework phase keeps task suites and evaluators fixed. A later,
separate phase may version task suites as first-class candidates:

\[
\mathcal P_t
=
\{(c_i,e_j)\},
\]

where \(c_i\) is a software candidate and \(e_j\) is a task-suite or runtime
context candidate.

That phase requires:

- a separate environment/task-suite registry;
- immutable environment identity;
- a minimal-criterion filter preventing trivial or impossible tasks;
- transfer evaluation across candidate-task pairs;
- protected final suites outside the adaptive loop;
- explicit rules preventing candidates from weakening their own evaluator.

Environment evolution must not be combined with the first candidate-pool PR.

## Trust and safety boundary

The following remain outside candidate control:

```text
canonicalization and identity law
hidden evaluator assets
hard safety constraints
credential and network policy
sandbox and filesystem policy
resource ceilings
state reducer
event-ledger integrity rules
installation and deployment authority
final evaluation
```

Candidates may change only caller-approved paths and manifest settings. Any
candidate able to alter the scorer, hide evidence, weaken safety checks, or
change the comparison policy invalidates the experiment rather than winning it.

Development, selection, and final evidence should be separated:

```text
development suites
    reusable and available as bounded proposal feedback

selection suites
    protected; return only approved evidence

final suites
    one-use; loaded only after the adaptive run stops
```

Repeated reuse of a final suite converts it into development evidence.

## Proposed repository layout

This PR does **not** create these runtime files. It specifies their intended
responsibilities for later implementation.

```text
apps/
└── variant_search/
    ├── README.md
    ├── driver.py
    ├── state.py
    ├── reducer.py
    ├── variant_manifest.py
    ├── change_record.py
    ├── evaluation.py
    ├── evaluation_math.py
    ├── scoring.py
    ├── compare.py
    ├── candidate_registry.py
    ├── candidate_pool.py
    ├── allocation.py
    ├── attribution.py
    ├── behavior_buckets.py
    └── example-request.json

tests/
└── test_variant_search.py
```

### `apps/variant_search/README.md`

Contains the implemented application contract, equations, trust boundary,
claim limits, falsifiers, command examples, and primary references.

### `driver.py`

Owns impure orchestration only:

1. read and verify framework state;
2. select one parent from caller-supplied weights and draw;
3. invoke one existing Controller generation;
4. construct one complete candidate event;
5. call the pure reducer;
6. append only a successfully reduced event.

It does not implement evaluation mathematics, proposal policy, or deployment.

### `state.py`

Defines and validates strict source-only JSON records for:

```text
run header
candidate registry
active pool
parent weights
behavior buckets
law identity
ledger head
```

It does not access Git, run subprocesses, or choose candidates.

### `reducer.py`

Implements the pure deterministic transition

\[
S_{t+1}=F_\Lambda(S_t,U_t).
\]

It verifies event completeness, candidate identity, parent selection,
evaluation context, comparison result, capacity rules, and ledger linkage.

### `variant_manifest.py`

Validates `.metering/variant.json`, stable identifiers, typed values, path
references, canonical form, manifest ID, and binding to the exact Git tree.

### `change_record.py`

Validates the semantic parent-to-child change and confirms that declared values
match parent and child manifests.

### `evaluation.py`

Builds matched parent/challenger result records from existing Controller
evidence and separately identified resource accounting.

### `evaluation_math.py`

Contains neutral finite calculations:

```text
weighted mean
weighted variance
weighted covariance
paired mean delta
paired delta variance
```

These functions do not interpret metrics or choose winners.

### `scoring.py`

Contains complete categorical forecast scoring:

```text
log score through Metering self-information
Brier score
```

It reports the two named scores separately.

### `compare.py`

Applies caller-declared hard constraints, safety ordering, Pareto dominance,
minimum-effect rules, and explicit tie behavior.

### `candidate_registry.py`

Validates and queries the complete branching version graph. It does not decide
active pool membership.

### `candidate_pool.py`

Owns bounded active membership, parent weights, activation, retirement, and
capacity enforcement.

### `allocation.py`

Validates normalized parent weights, verifies an explicit draw, and applies a
declared weight update. It does not derive weights from raw evidence.

### `attribution.py`

Computes Price-style `allocation_effect`, `change_effect`, and `total_delta` for
declared characteristics.

### `behavior_buckets.py`

Validates caller-declared descriptors, derives bucket identities, tracks local
retained candidates, and reports coverage and occupancy distributions.

### `example-request.json`

Provides one finite deterministic demonstration with a fixed Git repository,
fixed law, explicit initial candidates, parent weights, draws, task suite,
budgets, and stopping limits.

### `tests/test_variant_search.py`

Covers protocol and reducer behavior, not broad improvement claims.

## Implementation phases

### Phase 1: Git and manifest binding

Add only:

```text
variant manifest validation
manifest identity
Git-tree binding
semantic change records
one deterministic example
```

Acceptance requires:

- missing, malformed, duplicate-key, noncanonical, or stale manifests fail;
- every path/hash reference is verified;
- undeclared manifest changes fail;
- candidate and change identities are stable;
- no installed package API or dependency changes.

### Phase 2: matched evaluation evidence

Add:

```text
environment-bound evaluation records
resource-evidence binding
weighted moments
paired deltas
Brier score
effect records
```

Acceptance requires:

- parent and challenger use identical cases, runner, evaluator, and budget;
- evidence cannot be self-authored by candidates;
- aggregate values are recomputed;
- log and Brier scores remain separately named;
- uncertainty output never implies a universal generalization guarantee.

### Phase 3: registry and active pool

Add:

```text
branching candidate registry
bounded active pool
explicit parent weights and draw
pure reducer
append-only event ledger
```

Acceptance requires:

- one parent can have multiple children;
- old accepted variants can become active again;
- failed generations do not partially advance state;
- replay reconstructs byte-equivalent canonical state;
- tampering, stale state, broken ancestry, and unknown candidates fail.

### Phase 4: multi-objective retention and behavior buckets

Add:

```text
constraint-first comparison
Pareto dominance
bucket-local retention
coverage diagnostics
```

Acceptance requires:

- hard constraints precede optimization;
- incomparable variants may both remain when capacity permits;
- bucket dimensions are caller-owned;
- no generic scalar fitness is introduced;
- deterministic capacity and eviction rules are documented.

### Phase 5: adaptive proposal allocation

Add:

```text
proposal-yield evidence
parent-weight update
proposal-policy distribution records
Price-style attribution
```

Acceptance requires:

- raw evaluation never directly mutates policy without an explicit update event;
- every distribution is caller-declared and measured separately;
- attribution reconstructs total declared pool change within tolerance;
- adaptive policy changes are versioned and replayable.

### Phase 6: task-suite co-development

Only after the earlier phases are proven, add a separate task-suite registry,
minimal-criterion admission, candidate transfer, and cross-suite evaluation.
Protected evaluators and final suites remain immutable.

## Mathematical ownership boundary

| Quantity or transition | Proposed owner |
|---|---|
| Self-information, entropy, KL divergence, mutual information | installed `metering` package |
| Weighted mean, variance, covariance | source-only `evaluation_math.py` initially |
| Log score | `scoring.py` using Metering |
| Brier score | source-only `scoring.py` |
| Paired effect and uncertainty | source-only `evaluation_math.py` |
| Price-style attribution | source-only `attribution.py` |
| Pareto comparison | source-only `compare.py` |
| Parent-weight update | source-only `allocation.py` |
| Pool and registry transitions | source-only pure `reducer.py` |
| Proposal, execution, and protected evaluation | existing external/application boundaries |

No search policy or state transition belongs in Metering. Weighted moments should
be considered for a future neutral sibling package only after at least two
independent applications demonstrate the shared need.

## Claims and falsifiers

### Mathematical claims

The finite formulas should equal their declared definitions within documented
floating-point tolerances.

Falsifiers include:

- a valid weighted mean, variance, covariance, Brier, or Price-decomposition
  counterexample;
- failure to reconstruct total change from declared attribution terms;
- non-deterministic canonical identity for the same accepted input.

### Implementation hypotheses

**H1: manifest transparency.** A canonical manifest and semantic change record
make configurable differences inspectable beyond raw Git paths.

Falsifier: an accepted child whose manifest changed without a declared and
validated setting change.

**H2: branching replay.** A pure reducer and content-addressed ledger reproduce
the same registry, active pool, and weights from the same events.

Falsifier: replay disagreement, accepted broken ancestry, or partial advancement
after a failed event.

**H3: matched comparison.** Pairing parent and challenger on identical tasks,
law, evaluator, and budget makes evidence mismatches observable.

Falsifier: an accepted comparison using different cases, budgets, evaluator
identity, or post-reveal forecasts.

**H4: diversity preservation.** Behavior buckets preserve useful, qualitatively
different variants that a single-head process would discard.

Falsifier: controlled experiments showing no improvement in coverage, stepping
stones, or untouched-suite performance relative to matched single-head search.

### Empirical hypotheses

A later controlled experiment may test whether the proposed framework improves
fresh-suite outcomes relative to the existing single-head Evolution Driver under
matched initial candidates, proposer, model, task distribution, evaluator,
budget, and external draws.

The proposal itself does not establish that result.

## Scientific and technical foundations

1. Claude E. Shannon, “A Mathematical Theory of Communication,” 1948.  
   https://doi.org/10.1002/j.1538-7305.1948.tb01338.x  
   https://doi.org/10.1002/j.1538-7305.1948.tb00917.x

2. George R. Price, “Selection and Covariance,” *Nature* 227, 520–521,
   1970.  
   https://doi.org/10.1038/227520a0

3. R. C. Lewontin, “The Units of Selection,” *Annual Review of Ecology and
   Systematics* 1, 1–18, 1970.  
   https://doi.org/10.1146/annurev.es.01.110170.000245

4. Peter D. Taylor and Leo B. Jonker, “Evolutionary Stable Strategies and Game
   Dynamics,” *Mathematical Biosciences* 40, 145–156, 1978.  
   https://doi.org/10.1016/0025-5564(78)90077-9

5. Günter P. Wagner and Lee Altenberg, “Complex Adaptations and the Evolution
   of Evolvability,” *Evolution* 50, 967–976, 1996.  
   https://doi.org/10.1111/j.1558-5646.1996.tb02339.x

6. David H. Wolpert and William G. Macready, “No Free Lunch Theorems for
   Optimization,” *IEEE Transactions on Evolutionary Computation* 1, 67–82,
   1997.  
   https://doi.org/10.1109/4235.585893

7. Kenneth O. Stanley and Risto Miikkulainen, “Evolving Neural Networks through
   Augmenting Topologies,” *Evolutionary Computation* 10, 99–127, 2002.  
   https://doi.org/10.1162/106365602320169811

8. Kalyanmoy Deb, Amrit Pratap, Sameer Agarwal, and T. Meyarivan, “A Fast and
   Elitist Multiobjective Genetic Algorithm: NSGA-II,” *IEEE Transactions on
   Evolutionary Computation* 6, 182–197, 2002.  
   https://doi.org/10.1109/4235.996017

9. Glenn W. Brier, “Verification of Forecasts Expressed in Terms of
   Probability,” *Monthly Weather Review* 78, 1–3, 1950.  
   https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2

10. Tilmann Gneiting and Adrian E. Raftery, “Strictly Proper Scoring Rules,
    Prediction, and Estimation,” *Journal of the American Statistical
    Association* 102, 359–378, 2007.  
    https://doi.org/10.1198/016214506000001437

11. Bradley Efron, “Bootstrap Methods: Another Look at the Jackknife,”
    *The Annals of Statistics* 7, 1–26, 1979.  
    https://doi.org/10.1214/aos/1176344552

12. Jean-Baptiste Mouret and Jeff Clune, “Illuminating Search Spaces by Mapping
    Elites,” 2015.  
    https://arxiv.org/abs/1504.04909

13. Rui Wang, Joel Lehman, Jeff Clune, and Kenneth O. Stanley, “Paired
    Open-Ended Trailblazer (POET),” 2019.  
    https://arxiv.org/abs/1901.01753

14. Jenny Zhang, Shengran Hu, Cong Lu, Robert Lange, and Jeff Clune, “Darwin
    Gödel Machine: Open-Ended Evolution of Self-Improving Agents,” 2025.  
    https://arxiv.org/abs/2505.22954

15. A. Rundgren, B. Jordan, and S. Erdtman, “JSON Canonicalization Scheme
    (JCS),” RFC 8785, 2020.  
    https://www.rfc-editor.org/rfc/rfc8785.html

## Decision requested

This proposal asks maintainers to decide whether the repository should pursue a
source-only `variant_search` framework above the current deterministic
generation tools, with:

- Git for exact variant history;
- canonical JSON for semantic configurable state;
- matched evaluation with effect and uncertainty;
- a branching registry and bounded active pool;
- explicit proposal allocation;
- multi-objective and behavior-bucket preservation;
- no expansion of the installed Metering package in the first implementation.

Approval of this document would approve the **direction and boundaries**, not
the runtime implementation. Each phase should arrive in a separate reviewed PR.
