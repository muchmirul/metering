# Deterministic search and evolution design proposal

## Status

This document is a design proposal. It describes a direction that can be built
from Metering's existing measurement, artifact, evaluation, and recurrence
boundaries. It does not claim that the proposed population system, SQLite index,
recombination policy, or resource scheduler is implemented. [`PLAN.md`](../PLAN.md)
remains the normative contract until an implementation is separately specified,
tested, and accepted.

## Core claim

Metering should be a deterministic mathematical and evidential substrate that an
external agent can use while searching and evolving. It should not become the
agent, the world, or a universal optimizer.

The intended stack is:

1. an external coding agent such as Pi, driven by a model such as Qwen;
2. immutable candidate artifacts identified through Git;
3. trusted runners and evaluators operating under explicit budgets;
4. Metering's named mathematical measurements;
5. a queryable population and experiment index, for example SQLite;
6. an explicit external policy for parent allocation, retention, recombination,
   stopping, installation, and deployment.

The important refinement is:

> Metering can make search and evolution measurable, replayable, and composable
> without owning the meaning of fitness or silently collapsing every objective
> into one score.

This preserves the existing package boundary. The installed package continues
to accept caller-supplied finite probability models and return self-information,
entropy, KL divergence, or mutual information. Population policy, task meaning,
probability estimation, execution, and deployment remain outside that package.

## Why determinism matters

Evolution requires variation, but variation does not require hidden randomness.
A transition is reproducible when every source of variation is represented as
an explicit input.

Let:

- $`c_t`$ be a parent candidate;
- $`\theta_t`$ be the declared mutation or recombination policy;
- $`u_t`$ be an explicit draw, seed, or externally supplied choice;
- $`e_t`$ be the complete evaluation identity;
- $`o_t`$ be the observed evidence.

A deterministic protocol has the form:

$$
c'_t=M(c_t,\theta_t,u_t),
$$

$$
o_t=R(c'_t,e_t),
$$

$$
\mathcal A_{t+1}=U(\mathcal A_t,c'_t,o_t,\pi_t),
$$

where $`M`$ is variation, $`R`$ is execution and evaluation, $`\mathcal A_t`$
is the archive, $`U`$ is the archive update, and $`\pi_t`$ is an explicit
selection policy.

The same complete inputs should produce the same protocol decisions. This does
not require every model token or GPU operation to be bit-identical. When an
external model runtime is nondeterministic, the runtime identity, settings,
seed, and repeated outcomes must be recorded, and the observed distribution is
part of the evidence rather than being hidden behind a false determinism claim.

The useful distinction is:

- **measurement determinism:** the same valid probability input produces the
  same named Metering result within the documented numerical contract;
- **protocol determinism:** the same canonical artifacts, evidence, policy,
  and explicit draw produce the same retention or parent-allocation decision;
- **phenotype variability:** an external agent or runtime may still produce a
  distribution of outcomes, which must be measured through repeated trials.

## Architectural boundary

| Layer | Responsibility | Authority it must not receive |
|---|---|---|
| External agent and model | Propose, modify, or execute candidates | It must not judge its own retention or inspect protected evaluation material |
| Git artifact layer | Provide immutable candidate identity, parentage, diffs, and portable content | Git identity must not be treated as correctness, authorship, or fitness |
| Runner and sandbox | Execute a pinned candidate under a pinned environment and finite budget | It must not alter evaluator assets or the population record |
| Trusted evaluator | Produce task, safety, and resource evidence | It must not silently redefine the candidate or mutation policy |
| Metering package | Validate declared finite probability models and compute named information measures | It must not estimate probabilities, invent semantics, or return a generic intelligence score |
| Population index | Make candidates, lineages, runs, and metrics queryable | It must not become the sole source of truth or silently mutate evidence |
| Evolution policy | Allocate parents, apply selection pressure, preserve diversity, and stop | It must remain explicit, versioned, reviewable, and external to the measurement API |
| Caller | Approve protected constraints, final evaluation, installation, deployment, and rollback | These decisions must not be inferred from a local development score |

The design is general because each layer owns one kind of fact. Pi and Qwen are
one concrete proposer and execution stack, but the data and mathematical
boundaries do not depend on either one.

## Candidate, experiment, and evidence identity

A population system becomes unreliable when it confuses a candidate with the
conditions under which that candidate was evaluated.

Define a candidate as an immutable artifact:

$$
c=(a,\gamma),
$$

where $`a`$ is the content-identified artifact and $`\gamma`$ is its declared
configuration. Its identity is derived only from candidate content and
configuration, never from its later score.

Define an experiment as:

$$
e=(D,V,\rho,B),
$$

where:

- $`D`$ is the identified task or observation set;
- $`V`$ is the identified evaluator and protected policy;
- $`\rho`$ is the runner, model, connector, sandbox, and runtime identity;
- $`B`$ is the declared token, time, memory, device, and action budget.

A run is then:

$$
r=(c,e,s),
$$

where $`s`$ identifies the explicit random seed, draw, or replicate. Evidence
belongs to the run, not to the candidate in isolation.

This distinction prevents several common errors:

- treating a result from one harness as a property of the model alone;
- treating a score obtained under a larger budget as directly comparable to a
  score obtained under a smaller budget;
- embedding mutable evaluation results inside candidate identity;
- comparing candidates evaluated on different tasks, evaluator versions, or
  resource limits;
- losing the exact conditions needed to reproduce or challenge a claim.

## Git and SQLite have different jobs

Git should remain the immutable identity and evidence backbone. A database such
as SQLite should be a derived, queryable index over those immutable records.
They should not replace one another.

### Git owns durable identity

Git is appropriate for:

- candidate source and configuration trees;
- parent and child relationships;
- exact diffs;
- versioned evaluator and protocol descriptions when they are public;
- committed evidence receipts and provenance;
- portable checkout, review, and replay references.

A Git object proves that particular bytes were bound together under a particular
object identity. It does not prove that the candidate was honestly executed,
that a result is correct, or that the author is authentic.

### SQLite owns reconstruction and queries

A population search needs queries that are awkward or expensive to reconstruct
from Git history repeatedly. A derived SQLite index can represent:

- candidates and their immutable artifact IDs;
- parent, child, and recombination edges;
- experiment and evaluator identities;
- individual runs and replicate groups;
- named task, safety, calibration, novelty, information, and resource metrics;
- archive membership and behavior buckets;
- policy versions and explicit selection draws;
- promotion, rejection, quarantine, rollback, and final-evaluation events.

The database is not the authority for candidate bytes or immutable evidence. It
stores references and normalized indexes. A valid design must be able to delete
the database and rebuild it from canonical Git artifacts and append-only run
records.

This gives the consistency condition:

$$
\operatorname{Rebuild}(\text{Git records})=\text{SQLite index},
$$

up to database ordering and implementation details that do not change the
represented facts.

A row that cannot be traced to an immutable candidate, experiment, run, or
policy record is not admissible evolutionary evidence.

## Measurement model: keep a vector, not one universal score

The current Metering design correctly refuses to expose a generic fitness or
intelligence score. A Darwinian control plane should preserve that principle.
Different quantities answer different questions and should remain separately
named.

For a candidate $`c`$ evaluated under experiment $`e`$, define an evidence
vector:

$$
F(c;e)=
\left(
S,
Q,
G,
L,
N,
I,
C,
R
\right).
$$

The components are not all Metering package functions. They belong to the
external evaluation and selection layer, while Metering computes only the named
information-theoretic quantities for caller-declared models.

### Survival and protected constraints

Let:

$$
S(c;e)\in\{0,1\}
$$

indicate whether the candidate satisfies the experiment's protected admission
conditions. These may include sandbox integrity, protected-file identity,
interface conformance, task-independent safety rules, and hard resource caps.

A candidate with $`S=0`$ is ineligible for ordinary reproduction regardless of
its task score. It may be retained in a quarantine or failure archive for
analysis, but it must not become the active parent merely because it exploited
the evaluator.

Survival is therefore a feasibility condition, not a flattering weighted bonus:

$$
\mathcal F_e=\{c:S(c;e)=1\}.
$$

### Task capability

For binary task outcomes with declared task weights $`w_i`$:

$$
Q(c;e)=\frac{\sum_{i=1}^{n}w_i\,\operatorname{pass}_i(c;e)}
{\sum_{i=1}^{n}w_i}.
$$

Other domains may supply a different named task measure. The meaning, scale,
and aggregation belong to the evaluator and must be bound into $`e`$. Metering
must not infer that meaning from an arbitrary number.

### Generalization

Development evidence may influence evolution. A protected final evaluation must
not.

Let $`D_{dev}`$ be reusable search feedback and $`D_{final}`$ be an untouched
holdout. A simple transfer measurement is:

$$
G(c)=Q(c;D_{final})-Q(c_0;D_{final}),
$$

where $`c_0`$ is the declared baseline. This value can support a final claim, but
it must not be sent back into the same evolutionary run. Once final cases affect
selection, they become development evidence and a new final set is required.

### Calibration through logarithmic loss

When a candidate provides a complete pre-reveal probability for each realized
outcome, calibration evidence can use mean logarithmic loss:

$$
L(c;e)=-\frac{1}{n}\sum_{i=1}^{n}\log_2 q_c(y_i\mid x_i,e).
$$

Forecast Assay already follows this proper-scoring structure. Lower loss means
that the candidate assigned more probability to the outcomes that occurred. It
does not by itself establish task capability, safety, or semantic understanding.

### Novelty through declared behavior distributions

Novelty is meaningful only after the caller declares an aligned behavior space
and constructs a probability distribution over it.

For candidate behavior distribution $`P_c`$ and archive member distribution
$`P_a`$, one possible directed novelty measurement is:

$$
N(c)=\min_{a\in\mathcal A}
D_{\mathrm{KL}}(P_c\Vert P_a).
$$

This is not a generic distance and may be infinite when supports differ. A
symmetric or task-specific behavior measure may be more appropriate in another
application. The selection layer must name that choice explicitly. Metering
should only evaluate the declared KL inputs; it should not decide what counts as
behavior or novelty.

### Information value of an experiment

When an application maintains an explicit belief $`B_t`$ over finite
hypotheses, an experiment can be valued by its expected reduction in uncertainty:

$$
I_t=H(B_t)-\mathbb E[H(B_{t+1})].
$$

This can preserve informative failures. A candidate that does not improve task
performance may still reveal that an entire mutation family, tool policy, or
world hypothesis is unlikely. Such evidence belongs in the archive even when
the candidate is not promoted.

The equation is valid only for the declared belief model and update rule. It is
not a universal measure of scientific value.

### Physical cost

Cost should remain a vector because different resources are not universally
interchangeable:

$$
C(c;e)=
\left(
C_{tokens},
C_{wall},
C_{gpu},
C_{memory},
C_{storage},
C_{energy}
\right).
$$

A particular experiment may define an explicit scalar budget or exchange rate,
but that policy must be versioned and reviewable. The measurement layer should
not silently decide that one second, one token, and one joule have a universal
conversion.

### Reliability across replicates

For replicate task scores $`Q_1,\ldots,Q_k`$, the archive can retain both the
sample mean and variability. A conservative application-owned statistic may be:

$$
R(c;e)=\bar Q(c;e)-\kappa\,s_Q(c;e),
$$

where $`\kappa`$ is declared by the experiment. This prevents one lucky model
run from being treated as stable capability. It remains a finite-sample policy,
not a proof of future reliability.

## Selection remains an explicit external policy

The evidence vector does not choose a parent by itself. Selection is a policy
applied to named evidence.

A first filter is feasibility:

$$
\mathcal F_t=\{c\in\mathcal A_t:S(c;e_t)=1\}.
$$

A multi-objective archive may retain the Pareto set:

$$
\mathcal P_t=
\left\{
c\in\mathcal F_t:
\nexists d\in\mathcal F_t\text{ that is no worse in every declared objective
and strictly better in at least one}
\right\}.
$$

If an application requires scalarization, it may declare normalized evidence
$`\widetilde F`$ and a versioned weight vector $`w`$:

$$
J_w(c)=w^\top\widetilde F(c;e).
$$

That value is an application-owned reproductive score, not a Metering measure
and not a universal statement of candidate quality.

A soft parent-allocation policy can preserve exploration:

$$
p_t(c)=
\frac{\exp(\beta J_w(c))}
{\sum_{d\in\mathcal P_t}\exp(\beta J_w(d))}.
$$

The selection pressure $`\beta`$ is explicit. A supplied draw $`u_t\in[0,1)`$
then deterministically identifies the selected parent from the cumulative
probabilities. Recording $`p_t`$, $`u_t`$, and the policy version makes the
selection replayable without pretending that exploration is non-random.

The archive update can be written generally as:

$$
\mathcal A_{t+1}
=
\operatorname{Archive}_{\pi_t}
\left(
\mathcal A_t\cup\mathcal O_t
\right),
$$

where $`\mathcal O_t`$ contains newly evaluated candidates and $`\pi_t`$
explicitly defines capacity, behavior buckets, Pareto retention, quarantine,
and eviction. There is no universally correct archive policy.

## Recombination

Git artifacts make recombination possible, but Git merging is not automatically
biological or semantically valid recombination.

A valid recombination operator must declare:

- which loci, files, modules, prompts, skills, or configuration fields are
  independently inheritable;
- which combinations are illegal;
- how conflicts are resolved;
- which parents contributed each inherited element;
- the explicit draw or deterministic rule used;
- the resulting complete child identity.

Abstractly:

$$
c'=K(c^{(1)},c^{(2)},\eta,u),
$$

where $`\eta`$ is the declared recombination policy and $`u`$ is an explicit
draw or choice. The child must receive a fresh content identity. The database
records both parent edges and the recombination receipt; Git stores the actual
resulting artifact.

Blindly combining commits is likely to produce invalid candidates and obscure
causal attribution. Recombination should initially operate only on explicit,
typed, independently testable loci.

## Population architecture

The proposed population control plane adds six responsibilities around the
existing one-generation kernel:

1. **Archive:** retain multiple viable and informative candidates rather than
   only one current head.
2. **Parent allocation:** choose which lineage receives the next expensive model
   call or evaluation budget.
3. **Diversity accounting:** prevent every candidate from collapsing into one
   nearly identical behavior or configuration bucket.
4. **Resource accounting:** measure the cost of proposal, execution, evaluation,
   and storage under a shared budget.
5. **Recombination and mutation policy:** make variation operators explicit,
   content-bound, and replayable.
6. **Protected evaluation:** keep evaluator assets, final holdouts, and promotion
   authority outside candidate access.

The end-to-end relation is:

$$
\text{external proposer}
\rightarrow
\text{immutable candidate}
\rightarrow
\text{bounded execution}
\rightarrow
\text{trusted evidence}
\rightarrow
\text{named measurements}
\rightarrow
\text{archive update}
\rightarrow
\text{explicit parent allocation}.
$$

Metering's role is concentrated in the middle: it makes assumptions, candidate
identity, evidence alignment, and mathematical measurements explicit. It does
not decide that evolution should continue forever or that a selected candidate
should be installed.

## Relationship to the seven AI limits

| Limit | What this design contributes | What it cannot solve |
|---|---|---|
| Search and reachability | Population archives, parent allocation, novelty, recombination, and retained failures expose more useful paths than single-head hill climbing | It cannot guarantee that the globally best candidate is generated or reached |
| Semantic undecidability | Explicit time, action, memory, and process bounds turn unbounded questions into bounded operational evaluations | It cannot decide every semantic property of arbitrary Turing-complete candidates |
| Unprovability and certification | Protected invariants, strict schemas, replay, tests, and optional local proofs can certify narrow properties | They cannot prove every true beneficial property or global superiority |
| Evaluation and generalization | Separated evaluators, pre-reveal forecasts, matched cases, holdouts, and versioned policies reduce self-confirmation | A finite proxy can still diverge from long-run real-world value |
| Information and identifiability | Belief entropy, information-valued experiments, failure retention, and structured lineage improve evidence use | Indistinguishable worlds remain indistinguishable without new interventions or assumptions |
| Physical resources | Explicit cost vectors and allocation policies expose opportunity cost and permit early rejection | They cannot remove finite compute, memory, bandwidth, latency, or energy limits |
| Strategic multi-agent coupling | Multiple populations and evaluator versions can later represent co-adaptation explicitly | A fixed single-agent score cannot generally capture moving equilibria among adaptive agents |

The practical goal is not to abolish these limits. It is to make each limitation
visible at the layer where it enters the decision.

## Protected core and searchable surface

A self-evolving system needs a clear distinction between what is searchable in a
particular experiment and what remains fixed long enough to judge the search.

A reasonable initial protected core includes:

- the four Metering definitions and validation rules;
- canonical candidate and experiment identity rules;
- evaluator isolation and hidden-case access control;
- sandbox and resource-enforcement policy;
- run and lineage provenance;
- the versioned selection and archive policy;
- final-evaluation separation;
- caller authority over installation, deployment, and rollback.

The searchable surface may include:

- complete `SKILL.md` artifacts;
- prompts and system instructions;
- tool descriptions and routing;
- context and compaction policy;
- memory organization;
- verification loops;
- harness source artifacts;
- model-output artifacts;
- typed combinations of independently evaluable components.

The boundary may move between experiments, but it must not disappear inside one
experiment. If the candidate can rewrite both itself and the definition of
success without an external reference, promotion becomes self-confirmation.

## Proposed implementation sequence

This proposal intentionally separates design order from code ownership.

### Phase 1: canonical population record

Specify candidate, experiment, run, evidence, policy, lineage, archive-event,
and resource identities. Establish that a SQLite index can be rebuilt from Git
artifacts and append-only records. Do not introduce new selection behavior yet.

### Phase 2: read-only population index

Add a source-only query layer that can answer lineage, metric, cost, replicate,
and archive-membership questions without changing the installed package. Git
and canonical ledgers remain authoritative.

### Phase 3: explicit multi-objective archive

Replace one selected head as the only retained state with a bounded archive.
Keep survival, task performance, calibration, novelty, information value, cost,
and reliability separately named. Define Pareto or behavior-bucket retention in
the application contract.

### Phase 4: deterministic parent allocation

Introduce versioned parent-allocation policies with explicit probability
vectors and supplied draws. Record why each lineage received compute. Preserve
single-head mode as a simpler policy, not as the only possible architecture.

### Phase 5: typed recombination

Allow recombination only across declared loci with compatibility checks,
provenance, and independent tests. Do not treat arbitrary Git merge success as
semantic validity.

### Phase 6: adaptive mutation policy

Use accumulated evidence to modify $`\theta_t`$, the external proposal policy.
Mutual information between declared mutation features and outcomes may be one
analysis tool, but it does not establish causality by itself. Policy adaptation
must remain versioned and reversible.

### Phase 7: adversarial and co-evolving environments

Only after evaluator isolation and population replay are trustworthy should the
system introduce competing populations, adversarial task generation, or
evaluator co-evolution. These features increase strategic non-stationarity and
can corrupt the reference used to define improvement.

## Falsifiable design hypotheses

### H1: index reconstruction

**Claim.** Every accepted population-index fact can be rebuilt from immutable
candidate artifacts and canonical append-only records.

**Falsifier.** A valid database state affecting search or selection that cannot
be reconstructed from those sources.

### H2: evidence separation

**Claim.** Candidate identity, experiment identity, run evidence, and selection
policy remain independently inspectable.

**Falsifier.** A promoted candidate whose content, evaluation conditions, or
selection rule cannot be uniquely recovered.

### H3: population benefit under equal budget

**Claim.** On at least one declared task family, a bounded diverse archive finds
higher untouched-final performance than the existing single-head recurrence
under the same proposal and evaluation budget.

**Falsifier.** Controlled repeated experiments show no improvement or a reliable
regression once budget and evaluator exposure are matched.

### H4: protected evaluation reduces self-confirmation

**Claim.** Restricting candidate access to evaluator internals and maintaining an
untouched final set reduces the gap between development score and final score.

**Falsifier.** Controlled experiments show no reduction in that gap, or show that
the restriction only hides rather than prevents evaluator exploitation.

### H5: structured failures reduce repeated waste

**Claim.** Recording failed mutations, their context, and their evidence reduces
repeated equivalent failures or improves parent allocation under a fixed budget.

**Falsifier.** The structured archive does not change repeated-failure rate,
search efficiency, or final performance relative to an otherwise matched run.

## Non-goals

This proposal does not make the installed Metering package an AI framework. It
does not add a model SDK, hidden probability estimator, universal fitness
function, generic semantic score, autonomous deployment system, or proof of
recursive self-improvement.

It also does not claim that SQLite creates intelligence, that Git creates valid
inheritance, or that information measures alone determine survival. Those tools
supply different pieces:

- Git supplies immutable content identity and inspectable lineage;
- SQLite supplies derived population queries and scheduling state;
- Metering supplies exact named information measurements;
- evaluators supply domain evidence;
- evolution policies supply explicit selection and resource allocation;
- external agents supply candidate variation and execution behavior;
- callers preserve the final authority needed to make improvement meaningful.

The design succeeds when these parts can be recombined without blurring their
claims. Its minimal principle is:

> Keep the mathematical core small and deterministic; make candidate artifacts,
> evidence, policy, and resource use explicit; allow evolution in the
> composition around that core rather than hiding an optimizer inside it.
