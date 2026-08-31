# Pure Darwinian Variant Search Framework Proposal

## Status

This document is a **non-normative, unimplemented design proposal**. It does not
change [`PLAN.md`](../../PLAN.md), the installed `metering` package, any current
application protocol, or runtime behavior.

The proposal targets the architecture currently on `main` and keeps the
repository focused on one idea:

> Build a deterministic software substrate for **Darwinian search**: explicit
> variation, heredity, differential future contribution, selection, diversity,
> and accumulated evidence across generations.

External agents may generate software variants, but the repository's scientific
model is ordinary Darwinian variation and selection applied to computer
artifacts.

## Why the current repository is close but incomplete

The current applications already implement the irreducible one-generation
transition:

```text
selected parent
    -> propose one challenger
    -> run parent and challenger under matched controls
    -> evaluate both
    -> measure declared evidence
    -> select one
    -> return next_parent
```

The bounded Evolution Driver can repeat that transition, but it follows one
selected head. That is enough for a directed single-lineage evolutionary search.
A stronger Darwinian system additionally needs population-level state:

```text
many heritable variants
        |
        v
explicit variation
        |
        v
measured consequences
        |
        v
differential future allocation
        |
        v
retained diversity + ancestry
        |
        +---------- repeat ----------+
```

The missing framework therefore sits **above** the existing deterministic
one-generation tools. It should not move search policy or biological semantics
into Metering itself.

## Darwinian requirements

Lewontin's abstract conditions for evolution by natural selection are the most
useful foundation for the framework:

1. **Variation**: candidates differ.
2. **Differential contribution**: some variants receive more future descendants
   or proposal opportunities than others.
3. **Heredity**: descendants resemble parents strongly enough that useful
   differences can accumulate.

For software, translate those conditions directly:

| Darwinian concept | Developer-facing repository concept |
|---|---|
| variation | `change` |
| heredity | Git parentage + `variant_manifest` |
| differential reproduction | `parent_weight` / proposal allocation |
| population | `candidate_pool` |
| lineage/archive | `candidate_registry` / `version_graph` |
| phenotype | `evaluation_result` |
| fitness components | `evaluation_vector` |
| niche | `behavior_bucket` |
| evolvability | `proposal_yield` |

Biological terminology belongs in theory and documentation. Public schemas and
source files should use familiar software language.

## Scope principle

The framework should preserve the repository rule:

> Keep deterministic mechanism small; keep assumptions, policies, and
> interpretation explicit in source-only layers above it.

The installed Metering package remains responsible for exactly the four named
information measures:

```text
self-information
entropy
KL divergence
mutual information
```

The Darwinian framework may use those measurements, but does not redefine them
as fitness, capability, intelligence, or meaning.

## Git tracks exact variants; canonical JSON describes configurable state

The representation has two layers.

### Git: exact inherited artifact

Git owns:

```text
repository
commit
tree
portable content digest
entrypoint
external output receipts
parent commit(s)
```

The existing `git-candidate-v1` boundary already provides most of this. Branches
remain mutable navigation. Immutable commits, trees, content digests, and output
hashes remain candidate identity inputs.

### Canonical JSON: semantic variant manifest

Each framework-compatible Git candidate should contain:

```text
.metering/variant.json
```

Example:

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
  "connections": []
}
```

The manifest describes inherited configurable state, not measured capability.
A stable `setting_id` identifies the same configurable locus across variants;
the current `value` is the inherited setting at that locus.

The normalized manifest identity is

\[
\operatorname{manifest\_id}
=
\operatorname{SHA256}(\operatorname{CanonicalJSON}(V_i)).
\]

RFC 8785 is the engineering reference for deterministic JSON canonicalization
where cryptographic identity depends on serialization.

## Fixed run law versus configurable candidate state

For one experiment, represent a candidate as

\[
A_i=(\lambda,C_i,V_i),
\]

where:

- \(\lambda\) is the fixed run law;
- \(C_i\) is the immutable Git candidate;
- \(V_i\) is its canonical variant manifest.

The run law binds:

```text
schema versions
runner identity
evaluator identity
task-suite identity
sandbox and permission policy
resource-budget contract
comparison policy
state-reducer version
```

Changing the run law changes the experiment. It must start a new run or an
explicit versioned migration rather than silently extending old evidence.

This is important scientifically because selection is always relative to an
environment and inheritance mechanism.

## Semantic change records

Git answers **what bytes changed**. A separate canonical record answers **what
configurable state changed**.

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

A validator should prove structural consistency only:

1. parent and child variants exist;
2. `before` values match parent manifests;
3. `after` values match child manifests;
4. referenced path changes agree with Git differences;
5. undeclared manifest changes are rejected;
6. the record is canonical and content-addressed.

The record does not claim that the change caused an improvement.

## Evaluation results are environment-bound evidence

The same variant may perform differently under a different task suite, runtime,
budget, or evaluator. Evidence must bind all of them.

```json
{
  "schema_version": 1,
  "candidate_id": "CANDIDATE_ID",
  "manifest_id": "MANIFEST_ID",
  "law_id": "LAW_ID",
  "task_suite_id": "TASK_SUITE_ID",
  "evaluator_id": "EVALUATOR_ID",
  "budget_id": "BUDGET_ID",
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

For matched parent \(p\), challenger \(c\), and task suite \(E\):

\[
\Delta\boldsymbol{\phi}_E
=
\boldsymbol{\phi}(c,E)-\boldsymbol{\phi}(p,E).
\]

This is local empirical evidence, not an intrinsic property of the manifest.

## Candidate registry and active candidate pool

### `candidate_registry`

The registry contains all accepted content-valid variants and their version
relationships:

```text
c0
├── c1
│   ├── c4
│   └── c5
├── c2
└── c3
    └── c6
```

It preserves stepping stones and ancestry.

### `candidate_pool`

The pool is the bounded subset currently eligible for future proposal
opportunities:

\[
P_t\subseteq R_t.
\]

Registry and pool must remain different concepts: historical existence is not
the same as current reproductive/search activity.

## Differential future allocation

Darwinian selection requires that heritable variants contribute differently to
future search.

Let active variants be \(c_1,\ldots,c_n\) with parent-allocation distribution

\[
W_t=(w_{1,t},\ldots,w_{n,t}),
\qquad
w_{i,t}\ge0,
\qquad
\sum_iw_{i,t}=1.
\]

Given caller-supplied draw \(r_t\):

\[
i_t=\operatorname{Draw}(W_t,r_t).
\]

No hidden random-number generator is required. External randomness is acceptable
only when the declared distribution and realized draw are recorded.

A simple replicator-style update is

\[
\boxed{
p_{i,t+1}
=
\frac{p_{i,t}q_{i,t}}
{\sum_jp_{j,t}q_{j,t}}}
\]

where \(q_{i,t}\) is a caller-derived non-negative contribution factor. The
framework may apply a declared update but must not invent a universal mapping
from evidence to \(q_i\).

Taylor and Jonker's replicator dynamics are the primary reference for this kind
of frequency change under differential success.

## Mutation-selection accounting

When variation changes type as well as frequency:

\[
\boxed{
p_{j,t+1}
=
\frac{\sum_i p_{i,t}q_{i,t}M_{ij,t}}
{\sum_i p_{i,t}q_{i,t}}}
\]

where \(M_{ij,t}\) is the declared probability that contribution from parent
type \(i\) produces descendant type \(j\).

This keeps two responsibilities explicit:

```text
allocation: which variants receive more future opportunities?
variation: what descendants are produced?
```

Eigen's mutation-selection and quasispecies work is the foundational reference.

## Price-equation attribution

The Price equation gives a clean population-level accounting identity.

For characteristic \(z_i\), contribution \(w_i\), and average descendant change
\(\Delta z_i\):

\[
\boxed{
\Delta\bar z
=
\frac{\operatorname{Cov}(w,z)}{\mathbb E[w]}
+
\frac{\mathbb E[w\Delta z]}{\mathbb E[w]}
}
\]

Use developer-facing output names:

```text
allocation_effect
change_effect
total_delta
```

- `allocation_effect`: variants with which characteristics received more future
  contribution?
- `change_effect`: how did descendants differ from parents?
- `total_delta`: how did the candidate-pool mean change?

This prevents the framework from confusing better proposal generation with
simply giving more attempts to already-strong variants.

Price's 1970 covariance equation is the primary reference.

## Evaluation mathematics missing from Metering

Metering measures uncertainty, surprise, distributional difference, and
dependence. Darwinian experiments also need ordinary finite statistics and
proper scoring to quantify consequences of variation.

These should first live in the source-only framework rather than changing the
installed Metering API.

### Weighted mean

\[
\mu_x=\mathbb E_p[x]=\sum_i p_ix_i.
\]

### Weighted variance

\[
\operatorname{Var}_p(x)=\sum_ip_i(x_i-\mu_x)^2.
\]

### Weighted covariance

\[
\operatorname{Cov}_p(x,y)
=
\sum_ip_i(x_i-\mu_x)(y_i-\mu_y).
\]

Covariance is the key primitive needed by Price attribution. It measures
association under declared weights, not causation.

### Paired effect statistics

Run parent and challenger on matched cases. For metric \(m\):

\[
d_i=m_i(c)-m_i(p),
\qquad
\bar d=\frac1n\sum_i d_i,
\]

\[
s_d^2=\frac1{n-1}\sum_i(d_i-\bar d)^2.
\]

Report:

```text
case_count
mean_delta
delta_variance
wins
ties
losses
```

Optional paired bootstrap uncertainty may use caller-supplied resampling
indices. Efron's bootstrap is the reference.

### Proper probability scoring

The existing Forecast Assay already uses realized log score through
self-information. A useful bounded companion is the Brier score:

\[
BS(q,y)=\sum_k(q_k-\mathbf 1[k=y])^2.
\]

Brier's score and proper-scoring-rule theory support honest complete probability
forecasts. Log score and Brier score remain separate measurements.

## Multi-objective retention

Computer-agent evaluation is naturally a vector:

\[
\mathbf m(c)
=
(\text{task success},\text{safety},\text{cost},\text{latency},\ldots).
\]

Do not collapse this into one repository-defined scalar.

After hard constraints, \(a\) Pareto-dominates \(b\) when

\[
m_k(a)\ge m_k(b)\quad\forall k
\]

and it is strictly better in at least one dimension.

Recommended ordering:

```text
1. reject invalid or hard-constraint failures
2. reject configured safety regressions
3. prefer a Pareto-dominating candidate
4. retain both when they occupy different valid behavior buckets
5. use explicit caller tie policy only when one winner is required
```

NSGA-II is the standard evolutionary-computation reference for elitist
multi-objective selection with diversity preservation.

## Diversity and behavior buckets

Global-best-only search can discard useful stepping stones. Allow caller-defined
behavior descriptors:

```json
{
  "task_family": "debugging",
  "cost_band": "low",
  "tool_pattern": "repository-first"
}
```

Track coverage:

\[
\operatorname{coverage}
=
\frac{\text{occupied declared buckets}}
{\text{declared buckets}}.
\]

Existing Metering entropy can describe active-candidate distribution across
buckets. Mutual information can describe dependence between candidate/bucket
identity and environment outcome under a caller-supplied joint distribution.

MAP-Elites is the primary reference for retaining strong solutions across
behavior dimensions. Novelty Search provides complementary evidence that
objective-only evolutionary search can lose exploration on deceptive landscapes.

## Evolvability as proposal yield

The variation process itself can be evaluated without making the framework
self-referential.

For proposal policy \(\theta\), define an empirical yield such as

\[
Y(\theta)
=
\frac{\text{accepted useful children under }\theta}
{\text{proposal budget under }\theta}.
\]

Use developer term `proposal_yield`.

Wagner and Altenberg motivate this direction: evolvability depends on how a
representation maps heritable variation into useful phenotypic variation.
Modular settings and stable identities are therefore preferable to treating an
entire repository as one opaque mutable string.

## Structural innovation IDs

If the manifest later supports graph-like connections, new structural
connections need stable identities independent of list position.

NEAT provides a practical evolutionary-computation precedent through historical
markers that align structural innovations across different topologies. Initial
implementation should only establish stable IDs; recombination remains deferred.

## Optional candidate/test coevolution

The first implementation should keep task suites and evaluator law fixed for
clean attribution.

A later phase may version task/test variants:

```text
candidate variants change
        +
test variants change
        ->
reciprocal selection pressure
```

Hillis's coevolving-test work is the direct computational reference. Protected
final evaluation remains outside this loop.

## Pure deterministic framework state

Let

\[
S_t=(R_t,P_t,W_t,B_t,L_t,\Lambda),
\]

where:

- \(R_t\): candidate registry;
- \(P_t\): active candidate pool;
- \(W_t\): parent-allocation distribution;
- \(B_t\): behavior-bucket state;
- \(L_t\): append-only event ledger;
- \(\Lambda\): fixed run law.

A completed external event \(U_t\) contains parent draw, proposed child, Git
identity, semantic change record, evaluation evidence, resource evidence, and
comparison result.

The state transition is

\[
\boxed{S_{t+1}=F_\Lambda(S_t,U_t)}.
\]

`F` must be deterministic. It must not call a model, generate hidden randomness,
read protected evaluator state, invent metrics, or choose objectives.

## Proposed future source-only structure

No runtime files are added by this documentation PR.

```text
apps/variant_search/
    README.md
    driver.py
    state.py
    reducer.py
    variant_manifest.py
    change_record.py
    evaluation.py
    evaluation_math.py
    scoring.py
    compare.py
    candidate_registry.py
    candidate_pool.py
    allocation.py
    attribution.py
    behavior_buckets.py
    example-request.json
```

### `README.md`

Equations, schema meaning, trust boundaries, references, claims, nonclaims, and
falsifiers.

### `driver.py`

Impure orchestration only: select the declared parent event, invoke the existing
one-generation path, collect the completed evidence bundle, and submit it to the
reducer.

### `state.py`

Strict state validation: registry, active pool, weights, bucket state, run law,
and event-head identity.

### `reducer.py`

Pure deterministic transition from valid state plus one completed event to next
state. No model calls, evaluator calls, discovery, or random draws.

### `variant_manifest.py`

Validate `.metering/variant.json`, setting IDs, canonical JSON, Git references,
and manifest identity.

### `change_record.py`

Validate parent-to-child semantic changes against manifests and Git identities.

### `evaluation.py`

Validate matched evidence bound to task suite, evaluator, law, and budget.

### `evaluation_math.py`

Weighted mean, variance, covariance, paired effect, and paired effect variance.

### `scoring.py`

Complete forecast scoring. Reuse Metering for log score where appropriate; add
Brier score locally.

### `compare.py`

Hard constraints, safety-first rules, Pareto dominance, minimum-effect policy,
and explicit caller tie behavior.

### `candidate_registry.py`

Append-only content and relationship registry for all accepted variants.

### `candidate_pool.py`

Bounded currently active subset.

### `allocation.py`

Validate and apply parent weights, explicit draws, and declared allocation
updates. Never invent a universal fitness mapping.

### `attribution.py`

Price-equation accounting with `allocation_effect`, `change_effect`, and
`total_delta`.

### `behavior_buckets.py`

Validate behavior descriptors, occupancy, local retained variants, coverage, and
diversity diagnostics.

## Phased implementation

### Phase 1: variant identity and heredity

Add `variant_manifest.py` and `change_record.py` only.

Acceptance:

- canonical `.metering/variant.json`;
- Git/manifest binding;
- replayable parent-to-child change;
- no new selection behavior.

### Phase 2: matched evaluation mathematics

Add `evaluation.py`, `evaluation_math.py`, and `scoring.py`.

Acceptance:

- matched cases and budgets;
- correct weighted moments;
- correct paired effects;
- Brier known-value tests;
- existing log-score behavior unchanged.

### Phase 3: registry, pool, and differential allocation

Add registry, pool, allocation, state, reducer, and driver.

Acceptance:

- multiple branches preserved;
- bounded active pool;
- explicit parent distribution + draw;
- exact replay;
- no hidden RNG.

This is the first phase satisfying variation + heredity + differential
contribution as a population process.

### Phase 4: multi-objective selection and diversity

Add comparison and behavior buckets.

Acceptance:

- hard constraints precede preference;
- deterministic Pareto comparison;
- no global scalar fitness;
- different valid behavior buckets can coexist;
- coverage remains separately named.

### Phase 5: attribution and proposal yield

Add Price attribution and versioned proposal-policy evidence.

Acceptance:

- Price identity reconstructs pool-mean change;
- allocation and descendant-change effects remain separate;
- proposal policies compared under matched budgets;
- proposal-policy changes are explicit configuration changes.

### Phase 6: optional coevolution

Only after Phases 1-5:

- version task/test suites;
- maintain separate test registry;
- evaluate reciprocal candidate/test pressure;
- preserve protected final evaluation.

## Trust boundary

Keep these outside configurable candidate state initially:

```text
canonical identity rules
state reducer
evaluator secrets
hard safety constraints
credential and network policy
resource ceilings
protected final evaluation
installation and deployment authority
```

A candidate that weakens the evaluator invalidates the experiment rather than
winning it.

## Scientific hypotheses and falsifiers

### H1: structured heredity improves attribution

**Hypothesis.** Git + canonical variant manifest + semantic change record makes
declared configurable changes unambiguous.

**Falsifier.** Conflicting or unverifiable manifest changes are accepted.

### H2: candidate-pool search preserves useful stepping stones

**Hypothesis.** Under matched proposal/evaluation budget, a bounded diverse pool
can find final variants that single-head search misses on deceptive or
multi-modal spaces.

**Falsifier.** The advantage disappears under predeclared matched repeated
experiments.

### H3: parent allocation is replayable

**Hypothesis.** Identical pool, weights, and draws reproduce identical parent
choices and accepted transitions.

**Falsifier.** Results depend on hidden randomness or undeclared state.

### H4: Price attribution reconstructs population change

**Hypothesis.** `allocation_effect + change_effect = total_delta` within declared
numerical tolerance.

**Falsifier.** A valid finite counterexample violates the identity.

### H5: behavior buckets preserve declared diversity

**Hypothesis.** Bucketed retention preserves more declared coverage than a
single global incumbent under matched proposal budget.

**Falsifier.** Coverage cannot be reproduced or bucket labels silently become
fitness.

### H6: proposal policies differ in useful yield

**Hypothesis.** Under matched parents, tasks, and budgets, proposal policies have
measurably different retained-child yield.

**Falsifier.** Effects vanish under controlled matched runs or are confounded by
allocation differences.

## What remains out of scope

- universal intelligence or fitness scalar;
- hidden randomness;
- automatic deployment or installation;
- candidate access to evaluator secrets;
- biological vocabulary as required public API terminology;
- unbounded candidate retention;
- unrestricted evaluator/test mutation;
- claims that entropy or diversity alone imply capability.

## Theory-to-mechanism map

| Mechanism | Theory |
|---|---|
| variation + differential contribution + heredity | Lewontin |
| population-change decomposition | Price equation |
| parent-weight dynamics | replicator dynamics |
| mutation + selection | Eigen mutation-selection models |
| modular inherited representation | Wagner & Altenberg |
| stable structural innovation identity | NEAT historical markings |
| multi-objective retention | NSGA-II |
| preserved behavioral diversity | Novelty Search; MAP-Elites |
| probability forecast evaluation | Brier score; proper scoring rules |
| paired uncertainty | bootstrap theory |
| candidate/test coevolution | Hillis |
| canonical JSON identity | RFC 8785 |
| uncertainty and distribution diagnostics | Shannon information theory |

## Primary references

1. Richard C. Lewontin, “The Units of Selection,” *Annual Review of Ecology and
   Systematics*, 1, 1970, pp. 1-18.  
   https://doi.org/10.1146/annurev.es.01.110170.000245

2. George R. Price, “Selection and Covariance,” *Nature*, 227, 1970,
   pp. 520-521.  
   https://doi.org/10.1038/227520a0

3. Peter D. Taylor and Leo B. Jonker, “Evolutionarily Stable Strategies and
   Game Dynamics,” *Mathematical Biosciences*, 40, 1978, pp. 145-156.  
   https://doi.org/10.1016/0025-5564(78)90077-9

4. Manfred Eigen, “Selforganization of Matter and the Evolution of Biological
   Macromolecules,” *Naturwissenschaften*, 58, 1971, pp. 465-523.  
   https://doi.org/10.1007/BF00623322

5. Günter P. Wagner and Lee Altenberg, “Complex Adaptations and the Evolution of
   Evolvability,” *Evolution*, 50(3), 1996, pp. 967-976.  
   https://doi.org/10.1111/j.1558-5646.1996.tb02339.x

6. Kenneth O. Stanley and Risto Miikkulainen, “Evolving Neural Networks through
   Augmenting Topologies,” *Evolutionary Computation*, 10(2), 2002,
   pp. 99-127.  
   https://doi.org/10.1162/106365602320169811

7. Kalyanmoy Deb, Amrit Pratap, Sameer Agarwal, and T. Meyarivan, “A Fast and
   Elitist Multiobjective Genetic Algorithm: NSGA-II,” *IEEE Transactions on
   Evolutionary Computation*, 6(2), 2002, pp. 182-197.  
   https://doi.org/10.1109/4235.996017

8. Joel Lehman and Kenneth O. Stanley, “Abandoning Objectives: Evolution Through
   the Search for Novelty Alone,” *Evolutionary Computation*, 19(2), 2011,
   pp. 189-223.  
   https://doi.org/10.1162/EVCO_a_00025

9. Jean-Baptiste Mouret and Jeff Clune, “Illuminating Search Spaces by Mapping
   Elites,” 2015.  
   https://arxiv.org/abs/1504.04909

10. Glenn W. Brier, “Verification of Forecasts Expressed in Terms of
    Probability,” *Monthly Weather Review*, 78(1), 1950, pp. 1-3.  
    https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2

11. Tilmann Gneiting and Adrian E. Raftery, “Strictly Proper Scoring Rules,
    Prediction, and Estimation,” *Journal of the American Statistical
    Association*, 102(477), 2007, pp. 359-378.  
    https://doi.org/10.1198/016214506000001437

12. Bradley Efron, “Bootstrap Methods: Another Look at the Jackknife,” *The
    Annals of Statistics*, 7(1), 1979, pp. 1-26.  
    https://doi.org/10.1214/aos/1176344552

13. W. Daniel Hillis, “Co-Evolving Parasites Improve Simulated Evolution as an
    Optimization Procedure,” *Physica D*, 42(1-3), 1990, pp. 228-234.  
    https://doi.org/10.1016/0167-2789(90)90076-2

14. Anders Rundgren, Bret Jordan, and Samuel Erdtman, “JSON Canonicalization
    Scheme (JCS),” RFC 8785, 2020.  
    https://www.rfc-editor.org/rfc/rfc8785.html

15. Claude E. Shannon, “A Mathematical Theory of Communication,” *The Bell
    System Technical Journal*, 27, 1948, pp. 379-423 and 623-656.  
    https://doi.org/10.1002/j.1538-7305.1948.tb01338.x

## Final architecture statement

\[
\boxed{
\text{variation}
+
\text{heredity}
+
\text{differential future contribution}
+
\text{measured consequences}
+
\text{preserved diversity}
\longrightarrow
\text{cumulative Darwinian search}
}
\]

Git supplies exact inherited variants. Canonical JSON supplies semantic
configurable state. The existing generation apps supply matched variation,
execution, evaluation, and pairwise retention. The proposed framework supplies
the missing population, branching, allocation, diversity, and attribution
layers.

The scientific direction is intentionally narrow: **Darwinian search over
computer-agent variants, implemented with deterministic and reviewable software
boundaries.**
