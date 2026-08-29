# Pure Darwinian Variant Search Framework Proposal

## Status

This document is a **non-normative, unimplemented design proposal**. It does not
change [`PLAN.md`](../../PLAN.md), the installed `metering` package, any current
application protocol, or runtime behavior.

The proposal targets the architecture currently on `main` and keeps the
repository focused on one idea:

> Build a deterministic software substrate for **Darwinian search**: explicit
> variation, heredity, differential future allocation, selection, diversity,
> and accumulated evidence across generations.

This proposal does **not** use Gödel-machine, recursive-self-rewrite, or
self-referential proof machinery as a foundation. External agents may generate
software variants, but the repository's scientific model is ordinary Darwinian
variation and selection applied to computer artifacts.

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
   or future proposal opportunities than others.
3. **Heredity**: descendants resemble their parents strongly enough that useful
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

The framework should preserve the current repository rule:

> Keep the deterministic mechanism small; keep assumptions, policies, and
> interpretation explicit in source-only layers above it.

The installed Metering package remains responsible for the four named
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

The representation should have two layers.

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

The existing `git-candidate-v1` boundary already provides most of this.
Branches remain mutable navigation. Immutable commits, trees, content digests,
and output hashes remain candidate identity inputs.

### Canonical JSON: semantic variant manifest

Each framework-compatible Git candidate should contain:

```text
.metering/variant.json
```

The manifest describes configurable state in developer language:

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

The manifest is not a capability report. Fields such as `debugging_score` or
`reasoning_quality` do not belong there unless they are literal configurable
settings. Measured properties belong in evaluation evidence.

A stable `setting_id` identifies the same configurable locus across variants.
The current value is the inherited state at that locus. Stable identifiers make
later comparison and recombination possible without depending on array order or
file location alone.

The normalized manifest identity is conceptually:

\[
\operatorname{manifest\_id}
=
\operatorname{SHA256}(\operatorname{CanonicalJSON}(V_i)).
\]

RFC 8785 is the engineering reference for deterministic JSON canonicalization
when cryptographic identity depends on serialization.

## Fixed run law versus configurable candidate state

For one experiment, represent a candidate as

\[
A_i=(\lambda,C_i,V_i),
\]

where:

- \(\lambda\) is the fixed run law;
- \(C_i\) is the immutable Git candidate;
- \(V_i\) is its canonical variant manifest.

The run law binds the conditions under which variants are compared:

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
explicitly versioned migration rather than silently extending old evidence.

This boundary is important scientifically: natural selection is meaningful only
relative to a defined environment and inheritance mechanism. Changing the
selection environment while pretending the experiment is unchanged confounds
the result.

## Semantic change records

Git answers **what bytes changed**. A separate canonical JSON record answers
**what configurable state changed**.

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

1. referenced parent and child variants exist;
2. `before` values match the parent manifest;
3. `after` values match the child manifest;
4. referenced path changes agree with the Git tree difference;
5. undeclared manifest changes are rejected;
6. the record is canonical and content-addressed.

The record does not claim that a change caused an improvement.

## Evaluation results are environment-bound evidence

The same variant may perform differently under a different task suite, runtime,
budget, or evaluator. Evaluation evidence must therefore bind all of them.

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

For matched parent \(p\), challenger \(c\), and task suite \(E\), define the
observed effect vector

\[
\Delta\boldsymbol{\phi}_E
=
\boldsymbol{\phi}(c,E)-\boldsymbol{\phi}(p,E).
\]

This is local empirical evidence, not an intrinsic property of the manifest.

## Candidate registry and active candidate pool

A Darwinian process should not discard every non-head branch.

### `candidate_registry`

The registry contains all accepted, content-valid variants and their version
relationships. It is append-only evidence of what existed and where it came
from.

```text
c0
├── c1
│   ├── c4
│   └── c5
├── c2
└── c3
    └── c6
```

The registry does not mean every stored variant is currently eligible for future
proposals.

### `candidate_pool`

The pool is the bounded subset currently allowed to receive future proposal
opportunities:

\[
P_t\subseteq R_t.
\]

Separating registry and pool prevents two bad collapses:

- deleting useful historical stepping stones merely because they are currently
  inactive;
- treating every historical variant as equally active forever.

## Differential future allocation

Darwinian selection is not just pairwise comparison. Successful heritable
variants must receive differential contribution to the future search.

Let the active pool contain variants \(c_1,\ldots,c_n\). The caller declares a
parent-allocation distribution

\[
W_t=(w_{1,t},\ldots,w_{n,t}),
\qquad
w_{i,t}\ge0,
\qquad
\sum_iw_{i,t}=1.
\]

Given an explicit caller-supplied draw \(r_t\), parent choice is deterministic
and replayable:

\[
i_t=\operatorname{Draw}(W_t,r_t).
\]

The framework does not hide a random-number generator. Randomness may be
external, but the exact distribution and realized draw become part of the event
record.

A simple replicator-style allocation update is

\[
\boxed{
p_{i,t+1}
=
\frac{p_{i,t}q_{i,t}}
{\sum_jp_{j,t}q_{j,t}}}
\]

where \(q_{i,t}\) is a caller-derived non-negative contribution factor from
observed evidence. The framework may apply this declared update, but it must not
invent a universal rule mapping task evidence into \(q_i\).

Taylor and Jonker's replicator dynamics provide the mathematical reference for
frequency change under differential success.

## Mutation-selection accounting

When variation also changes type, a discrete mutation-selection update has the
form

\[
\boxed{
p_{j,t+1}
=
\frac{\sum_i p_{i,t}q_{i,t}M_{ij,t}}
{\sum_i p_{i,t}q_{i,t}}}
\]

where \(M_{ij,t}\) is the declared probability that a contribution from parent
type \(i\) produces descendant type \(j\).

This separates two things that should remain separate in software:

```text
selection/allocation: who gets more future opportunities?
variation: what kinds of children are produced?
```

Eigen's mutation-selection/quasispecies work is a foundational reference for
this decomposition.

## Price-equation attribution

The Price equation is the cleanest population-level accounting identity for the
framework.

For candidate characteristic \(z_i\), contribution \(w_i\), and average
descendant change \(\Delta z_i\):

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

Interpretation:

- `allocation_effect`: did variants already possessing characteristic \(z\)
  receive more future contribution?
- `change_effect`: did descendants differ from parents in \(z\)?
- `total_delta`: how did the candidate-pool mean change?

The identity is useful because it prevents the framework from conflating a
better proposal operator with merely allocating more attempts to already-strong
variants.

Price's 1970 covariance equation is the primary theoretical reference.

## Evaluation mathematics missing from Metering

Metering currently measures uncertainty, surprise, distributional difference,
and dependence. Darwinian experiments also need ordinary finite statistics and
proper scoring to describe the consequences of variation.

These should first live in the source-only framework rather than expanding the
installed Metering API.

### Weighted mean

\[
\mu_x=\mathbb E_p[x]=\sum_i p_ix_i.
\]

Useful for expected task result, latency, resource cost, or candidate-pool
characteristics under declared weights.

### Weighted variance

\[
\operatorname{Var}_p(x)=\sum_ip_i(x_i-\mu_x)^2.
\]

Useful for instability across tasks or contexts. Variance is not quality: a
candidate may be consistently bad.

### Weighted covariance

\[
\operatorname{Cov}_p(x,y)
=
\sum_ip_i(x_i-\mu_x)(y_i-\mu_y).
\]

This is the key mathematical primitive required by the Price equation.
Covariance is association under declared weights, not proof of causation.

### Paired effect statistics

Parent and challenger must run on matched cases. For a metric \(m\):

\[
d_i=m_i(c)-m_i(p),
\qquad
\bar d=\frac1n\sum_i d_i,
\]

\[
s_d^2=\frac1{n-1}\sum_i(d_i-\bar d)^2.
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

An optional paired bootstrap may use caller-supplied resampling indices. Efron's
bootstrap is the standard reference for empirical resampling-based uncertainty.

### Proper probability scoring

The current Forecast Assay already uses realized log score via
self-information. A bounded companion is the multiclass Brier score:

\[
BS(q,y)=\sum_k(q_k-\mathbf 1[k=y])^2.
\]

Brier's 1950 score and the general theory of strictly proper scoring rules
support keeping complete probabilistic forecasts honest. Log score and Brier
score should be reported separately, never blended into a universal fitness
number.

## Multi-objective retention

Computer-agent evaluation is naturally a vector:

\[
\mathbf m(c)
=
(\text{task success},\text{safety},\text{cost},\text{latency},\ldots).
\]

Do not collapse this into one repository-defined scalar.

After hard constraints, candidate \(a\) Pareto-dominates candidate \(b\) when

\[
m_k(a)\ge m_k(b)\quad\forall k
\]

and it is strictly better in at least one dimension.

A developer-facing ordering can be:

```text
1. reject invalid or hard-constraint failures
2. reject configured safety regressions
3. prefer a Pareto-dominating candidate
4. retain both when each is superior on different valid dimensions and
   different behavior buckets permit coexistence
5. use an explicit caller tie policy only when a single winner is required
```

NSGA-II is a standard evolutionary-computation reference for elitist,
non-dominated multi-objective selection with diversity preservation.

## Diversity and behavior buckets

Darwinian search can lose useful stepping stones if it retains only the current
global winner. The framework should allow caller-defined behavior descriptors:

```json
{
  "task_family": "debugging",
  "cost_band": "low",
  "tool_pattern": "repository-first"
}
```

A behavior bucket is not a claim of biological niche equivalence. It is a
software mechanism for preserving qualitatively different variants.

Track at least:

\[
\operatorname{coverage}
=
\frac{\text{occupied declared buckets}}
{\text{declared buckets}}.
\]

Existing Metering entropy can measure the distribution of active candidates
across buckets. Existing mutual information can measure dependence between
candidate/bucket identity and environment outcomes when the caller supplies a
valid joint distribution.

MAP-Elites is the main reference for preserving high-performing solutions across
behavior dimensions. Novelty Search is a complementary reference showing that
objective-only evolutionary search can become trapped and that behavioral
novelty can preserve useful exploration.

## Evolvability as proposal yield

The framework eventually needs to evaluate not only variants but also the
variation process that produces them. Keep the code term developer-friendly:
`proposal_yield`.

For proposal policy \(\theta\), define an empirical yield such as

\[
Y(\theta)
=
\frac{\text{accepted useful children produced under }\theta}
{\text{proposal budget consumed under }\theta}.
\]

This is an empirical framework metric, not a universal definition of
biological evolvability.

Wagner and Altenberg provide the theoretical foundation: evolvability depends
strongly on the representation and genotype-phenotype map, especially modularity
and the ability for variation to change useful components without destroying
unrelated function.

The framework should therefore favor explicit modular settings and stable IDs,
not opaque whole-repository strings as the only representation.

## Structural innovation IDs

If the manifest later supports graph-like module connections, new structural
connections need persistent identities independent of array position.

NEAT provides a practical evolutionary-computation precedent: historical
markers align structural innovations across varying topologies. The first
framework phase only needs stable identifiers; crossover can remain deferred.

## Environment and task-suite changes

The first implementation should hold task suites and evaluator law fixed.
Otherwise the system cannot attribute improvement cleanly.

A later **coevolution** phase may version task suites or adversarial test sets,
but it must remain Darwinian in framing:

```text
candidate variants change
        +
test/task variants change
        ->
reciprocal selection pressure
```

Hillis's coevolving-parasites work is a direct computational reference for
coevolving solutions and test cases to avoid local stagnation. Niche-construction
and eco-evolutionary feedback literature provide biological references for
organisms modifying conditions that subsequently alter selection.

Protected final evaluation remains outside this loop. Repeatedly adapting to the
same final suite turns it into development data.

## Pure deterministic framework state

Let framework state be

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

A completed external event \(U_t\) contains all exogenous results required for a
transition: parent draw, proposed child, Git identity, semantic change record,
evaluation evidence, resource evidence, and comparison result.

The state transition is

\[
\boxed{S_{t+1}=F_\Lambda(S_t,U_t)}.
\]

`F` must be deterministic. It must not call a model, generate hidden randomness,
read protected evaluator state, invent metrics, or choose objectives.

This is the repository's core engineering interpretation of Darwinian evolution:
external variation may be stochastic, but recorded inheritance and selection are
explicit and replayable.

## Proposed future source-only structure

No runtime files are added by this documentation PR. A later implementation
should use ordinary developer-facing names:

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

Owns equations, schema meaning, trust boundaries, primary theory references,
claims, nonclaims, and falsifiers.

### `driver.py`

Impure orchestration only: select one declared parent event, invoke the existing
one-generation path, collect the completed evidence bundle, and submit it to the
reducer. It does not contain mathematical policy hidden from state.

### `state.py`

Strict framework-state validation: registry, active pool, weights, bucket state,
run law ID, and event-head identity.

### `reducer.py`

Pure deterministic transition from valid state plus one completed event to the
next state. No model calls, evaluator calls, file discovery, or random draws.

### `variant_manifest.py`

Validates `.metering/variant.json`, stable setting identities, canonical JSON,
Git-path references, and manifest identity.

### `change_record.py`

Validates parent-to-child semantic changes against parent and child manifests and
Git identities.

### `evaluation.py`

Validates matched candidate evidence bound to task suite, evaluator, law, and
budget.

### `evaluation_math.py`

Neutral finite calculations: weighted mean, variance, covariance, paired effect,
and paired effect variance.

### `scoring.py`

Complete probabilistic forecast scoring. Reuse Metering for log score where
appropriate; add Brier score locally.

### `compare.py`

Hard constraints, safety-first rules, Pareto dominance, minimum-effect policy,
and explicit caller tie behavior.

### `candidate_registry.py`

Append-only content and relationship registry for all accepted variants.

### `candidate_pool.py`

Bounded currently active subset. Membership is distinct from historical
existence.

### `allocation.py`

Validates and applies declared parent weights, explicit draws, and documented
allocation updates. It never converts arbitrary evidence to a hidden universal
fitness value.

### `attribution.py`

Price-equation population-change accounting with developer-facing names:
`allocation_effect`, `change_effect`, `total_delta`.

### `behavior_buckets.py`

Validates caller-declared behavior descriptors, occupancy, local retained
variants, coverage, and diversity diagnostics.

## Phased implementation

### Phase 1: variant identity and heredity

Add only:

```text
variant_manifest.py
change_record.py
```

Requirements:

- `.metering/variant.json` is canonical and content-addressed;
- Git candidate and manifest identities are bound;
- parent-to-child changes are replayable and structurally verified;
- no new selection behavior exists yet.

This phase establishes heredity before adding population policy.

### Phase 2: matched evaluation mathematics

Add:

```text
evaluation.py
evaluation_math.py
scoring.py
```

Requirements:

- parent and challenger use identical declared cases and budgets;
- weighted moments reproduce independent calculations;
- paired effects reproduce case-level differences;
- Brier score matches known examples;
- current log-score behavior remains separate and unchanged.

### Phase 3: registry, pool, and differential allocation

Add:

```text
candidate_registry.py
candidate_pool.py
allocation.py
state.py
reducer.py
driver.py
```

Requirements:

- multiple branches remain stored;
- active pool is bounded independently of registry history;
- parent selection is reproduced from declared distribution and explicit draw;
- invalid, unknown, or inactive parents cannot produce an accepted event;
- every completed event is replayable;
- no hidden RNG exists.

This is the first phase that satisfies the full variation + heredity +
differential-contribution Darwinian structure.

### Phase 4: multi-objective selection and diversity

Add:

```text
compare.py
behavior_buckets.py
```

Requirements:

- hard constraints are applied before performance preference;
- Pareto comparison is deterministic;
- no repository-wide scalar fitness is introduced;
- different behavior buckets can retain different valid variants;
- coverage and bucket-distribution diagnostics are separately named.

### Phase 5: selection/change attribution and proposal yield

Add:

```text
attribution.py
```

and versioned proposal-policy evidence.

Requirements:

- Price identity reconstructs observed pool-mean change;
- `allocation_effect` and `change_effect` remain separate;
- proposal policies are compared under matched budgets;
- mutation/proposal policy changes are explicit configuration changes, not
  hidden framework adaptation.

### Phase 6: optional coevolution

Only after Phases 1-5 are stable:

- version task suites;
- maintain a separate task/test registry;
- evaluate reciprocal candidate/test pressure;
- preserve a protected one-use final suite;
- do not let candidates rewrite evaluator law or final evidence.

This phase is grounded in coevolutionary computation, not Gödelian
self-modification.

## Trust boundary

Candidate variants must not be able to modify or read protected parts of the
selection mechanism merely because they are part of the same repository.
Initially keep these outside configurable candidate state:

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

Selection pressure exploits whatever the evaluation actually rewards. A variant
that changes or hides the evaluator has invalidated the experiment rather than
improved under it.

## Scientific hypotheses and falsifiers

### H1: structured heredity improves attribution

**Hypothesis.** A Git candidate plus canonical variant manifest and semantic
change record makes it possible to identify which declared configurable state
changed between parent and child without relying on free-form diff
interpretation.

**Falsifier.** Two accepted variants have conflicting or unverifiable manifest
changes, or a change record can disagree with their manifests without rejection.

### H2: candidate-pool search finds stepping stones a single head loses

**Hypothesis.** Under the same proposal and evaluation budget, preserving a
bounded set of diverse valid parents can discover final variants that a
single-head process misses on deceptive or multi-modal search spaces.

**Falsifier.** Across predeclared repeated environments, the pool method does not
improve final held-out outcome over matched single-head controls, or any observed
advantage disappears under equalized proposal budget.

### H3: explicit parent allocation is replayable

**Hypothesis.** Given identical pool state, weights, and explicit draws, parent
choice and accepted state transitions are identical.

**Falsifier.** A transition depends on hidden randomness, process order, wall
clock, or undeclared mutable state.

### H4: Price attribution reconstructs pool change

**Hypothesis.** For valid finite declared data, `allocation_effect +
change_effect` reconstructs `total_delta` within documented numerical tolerance.

**Falsifier.** A valid finite counterexample violates the identity.

### H5: behavior buckets preserve diversity without redefining quality

**Hypothesis.** A bucketed pool retains more declared behavioral coverage than a
single global incumbent under matched proposal budget, while quality remains a
separate evidence dimension.

**Falsifier.** Bucket assignment silently becomes a generic fitness score, or
coverage cannot be reproduced from stored descriptors.

### H6: proposal policy can be evaluated as a heritable search component

**Hypothesis.** Under matched parent/task/budget conditions, proposal policies
have measurably different yields of valid retained children.

**Falsifier.** Policy effects disappear under matched controlled runs or cannot
be separated from unequal parent/task allocation.

## What must remain out of scope

The framework should not add:

- Gödel-machine proof search;
- recursive self-referential optimizer rewriting;
- a universal intelligence or fitness scalar;
- hidden randomness;
- automatic deployment or installation;
- candidate access to evaluator secrets;
- biological vocabulary as required public API terminology;
- unbounded candidate retention;
- unrestricted test/evaluator mutation;
- claims that entropy or diversity alone imply capability.

## Theory-to-mechanism map

| Mechanism | Theory |
|---|---|
| variation + differential contribution + heredity | Lewontin's abstract conditions for natural selection |
| population change decomposition | Price equation |
| parent-weight dynamics | replicator dynamics |
| mutation + selection | Eigen mutation-selection / quasispecies models |
| modular variant representation | Wagner & Altenberg on evolvability |
| stable structural innovation identity | NEAT historical markings |
| multi-objective retention | NSGA-II |
| preserved behavioral diversity | Novelty Search; MAP-Elites |
| probability forecast evaluation | Brier score; proper scoring rules |
| paired uncertainty | bootstrap theory |
| candidate/test coevolution | Hillis coevolving test cases |
| canonical JSON identity | RFC 8785 |
| uncertainty and distribution diagnostics | Shannon information theory |

None of these references changes the repository contract by itself. They justify
specific proposed mechanisms and identify what would falsify the corresponding
engineering claim.

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

The repository should be understood as building deterministic tools for this
process:

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

That is the entire scientific direction of this proposal: **pure Darwinian
search over computer-agent variants, implemented with deterministic and
reviewable software boundaries.**
