# System foundations, design rationale, and hypotheses

## Status and claim boundary

This document connects the mathematics, biology analogy, and engineering
decisions used across Metering and its six repository-local applications. It
explains why the pieces have their current boundaries; it does not expand the
normative contract in [`PLAN.md`](../PLAN.md).

Three kinds of statement must remain separate:

1. **Mathematical identities** follow from a declared probability model.
2. **Implementation hypotheses** are falsifiable claims that the programs obey
   their documented schemas, equations, ordering, and identity rules.
3. **Empirical hypotheses** concern performance on future observations and need
   controlled experiments outside this repository.

Passing an implementation test cannot prove an empirical adaptation claim.
Likewise, a biological analogy does not make these programs organisms.

## One system, several named layers

| Layer | Object or transition | Foundation | Repository owner |
|---|---|---|---|
| Measurement | finite probability model -> named quantity | Shannon information theory | installed `metering` package |
| Observation | version belief -> probe result -> conditioned belief | finite Bayesian experiment design | Observer |
| Variation | parent + mutation event -> child | mutation kernel and inheritance | Mutator |
| Expression | genome -> complete pre-reveal result forecast | pushforward probability distribution | Candidate Runner |
| Assay | revealed targets -> empirical mean log loss | logarithmic proper scoring | Forecast Assay |
| Retention | two aligned assay reports -> selected identity | strict pairwise elitist selection | Selection Gate |
| One generation | variation -> expression -> reveal -> assay -> retention | directed-evolution-inspired composition | Evolution Controller |
| Integrity | canonical object + parent digest -> content/lineage ID | SHA-256 content addressing | identities and `metering-history` |

The [high-level system diagram](../README.md#system-at-a-glance) shows the data
flow. The separation above is substantive: an observation is not a mutation,
uncertainty is not forecast quality, an assay value is not selection, and a
selection result is not a persistent lineage.

## 1. Finite discrete information theory

### Declared probability models

Let $X$ have a finite outcome set $\mathcal X$ and probability mass
function $p(x)$ satisfying

$$
p(x)\ge 0,\qquad \sum_{x\in\mathcal X}p(x)=1.
$$

The caller owns the outcome meanings and construction of $p$. Metering owns
only strict validation and numerical evaluation. This is why the package does
not infer a distribution from samples, normalize counts, add a prior, smooth a
zero, or choose an estimator: each operation would introduce a model that the
caller did not declare.

### Self-information and its logarithm

For a realized outcome $x$, self-information in base $b>1$ is

$$
I_b(x)=-\log_b p(x).
$$

`p(x)` is the declared probability of the outcome and $b$ fixes the unit;
base 2 gives bits and base $e$ gives nats. If two events are independent,
their joint probability multiplies, so their information adds:

$$
I_b(x,y)=-\log_b[p(x)p(y)]=I_b(x)+I_b(y).
$$

That additivity is the reason for the logarithm. A probability-zero event has
positive infinite surprisal, not a large clipped finite value.

### Entropy

The expected self-information is Shannon entropy:

$$
H_b(X)=\mathbb E[I_b(X)]
      =-\sum_{x\in\mathcal X}p(x)\log_b p(x).
$$

For $n$ possible outcomes,

$$
0\le H_b(X)\le \log_b n,
$$

with zero for a certain outcome and the upper bound for a uniform distribution.
Entropy describes uncertainty in the supplied model. It does not say whether
the outcomes are meaningful or whether resolving them is useful.

### Relative entropy and mutual information

For aligned finite distributions $P$ and $Q$, Kullback-Leibler divergence
is

$$
D_{\mathrm{KL},b}(P\Vert Q)
=\sum_x p(x)\log_b\frac{p(x)}{q(x)}.
$$

It measures a directed discrepancy relative to $Q$; reversing the arguments
usually changes the value. It is not a distance because it is not generally
symmetric and does not obey the triangle inequality.

For a joint model $P_{XY}$, mutual information is

$$
I_b(X;Y)
=D_{\mathrm{KL},b}(P_{XY}\Vert P_XP_Y)
=\sum_{x,y}p(x,y)\log_b
  \frac{p(x,y)}{p(x)p(y)}.
$$

It is the divergence between the declared joint distribution and the
independent model formed from its marginals. It measures statistical dependence
in that model, not causal influence or semantic relevance.

### Logarithmic loss

If the data-generating distribution is $P$ and a forecaster reports a
complete distribution $Q$, expected logarithmic loss decomposes as

$$
\mathbb E_{Y\sim P}[-\log_b q(Y)]
=H_b(P)+D_{\mathrm{KL},b}(P\Vert Q).
$$

Because KL divergence is non-negative, expected log loss is minimized at
$Q=P$. This is the proper-scoring foundation for Forecast Assay and Selection
Gate. It requires a coherent complete forecast made before the target is known.
Forecast Assay receives only the realized target coordinate. Candidate Runner
constructs a complete forecast for its fixed finite model; Evolution Controller
validates unique normalized outcomes before reveal and enforces local call
ordering. The controller cannot prove completeness for an arbitrary outcome
domain, and none of these checks is a cryptographic proof of timing.

For $n$ revealed cases, the repository reports the empirical mean

$$
L_E(c)=-\frac{1}{n}\sum_{i=1}^{n}
       \log_2 q_c(y_i\mid x_i,E).
$$

Here $c$ is a candidate, $E$ is the named evaluation, $x_i$ is a case,
$y_i$ is its revealed target, and $q_c$ is the candidate forecast. This
sample average is evidence on exactly those cases. By itself it supplies no
confidence interval or guarantee about future cases.

## 2. Observation as a finite experiment

Let $V$ be an unknown fixture version, $q$ an allowed probe, and
$R_q=f_q(V)$ its deterministic result. The result distribution is the
pushforward of the version belief:

$$
P(R_q=r)=\sum_{v:f_q(v)=r}P(V=v).
$$

For a deterministic noiseless channel, $H(R_q\mid V)=0$, hence

$$
I(V;R_q)=H(R_q)
=H(V)-\mathbb E_r[H(V\mid R_q=r)].
$$

This identity explains Observer's maximum-result-entropy reference policy: it
maximizes expected one-step reduction in version uncertainty under its exact
finite model. It does not prove that the same greedy rule is globally optimal
with noise, nonuniform priors, unequal probe costs, or a different catalogue.

## 3. Variation, selection, and the biology analogy

Lewontin's abstract conditions for evolution by natural selection are variation,
differential survival or reproduction, and heritable correlation between parent
and offspring. The repository keeps those responsibilities explicit:

```text
Mutator creates variation
Candidate Runner expresses a genome as forecasts
Forecast Assay measures behavior on revealed evidence
Selection Gate makes differential retention explicit
Evolution Controller returns one selected child or parent
external caller repeats generations and may adapt mutation policy
```

This is a directed-evolution-inspired software decomposition. The apps do not
model cells, genomes, reproduction rates, populations, ecology, or natural
selection literally.

For parent $c_t$, caller-owned mutation kernel $Q_{\theta_t}$, and child
$c'_t$, the abstract generation begins with

$$
c'_t\sim Q_{\theta_t}(\cdot\mid c_t).
$$

For finite assay losses, retention is

$$
\Delta_t=L_E(c_t)-L_E(c'_t),
$$

$$
c_{t+1}=
\begin{cases}
c'_t,&\Delta_t>\delta,\\
c_t,&\text{otherwise},
\end{cases}
\qquad \delta\ge 0.
$$

If either loss is infinite, Selection Gate uses its separately documented
extended-real ordering and does not form the undefined difference
$+\infty-(+\infty)$.

The Mutator request supplies both the finite support of $Q$ and the draw, so
it evaluates one declared mutation event without owning randomness. Selection
Gate owns the strict threshold rule; only the controller turns that decision
into `next_parent`. Updating $\theta_t$, repeating the transition, and
stopping remain caller-owned policy.

The Price equation provides a useful conceptual reason not to merge variation
and selection:

$$
\bar w\,\Delta\bar z
=\operatorname{Cov}(w_i,z_i)+\mathbb E[w_i\Delta z_i].
$$

Here $z_i$ is a parent trait, $w_i$ is its descendant contribution,
$\Delta z_i$ is within-lineage transmission change, and $\bar w$ is mean
contribution. The covariance term separates differential selection from the
transmission term. Metering does not compute this equation: the current
one-parent/one-child gate has neither a biological population nor reproductive
weights. The equation supports the responsibility split, not a claim of
biological equivalence.

## 4. Content identity and linear history

Each identity boundary defines its own canonical serialization $C_s(m)$ and
uses a SHA-256 digest

$$
d_s(m)=\operatorname{SHA256}(\operatorname{UTF8}(C_s(m))).
$$

The schema-specific subscript matters: Observer manifests, candidate genomes,
mutations, selection evidence, and history records each document their own
fields and JSON encoding. Digests from different schemas are not
interchangeable merely because every boundary uses SHA-256. Candidate IDs bind
a declared genome to its schema. Snapshot and history record IDs additionally
include a parent identifier. For a history record $R_t$, the lineage relation
is structurally

$$
R_t.\text{parent\_record\_id}=d_{\mathrm{history}}(R_{t-1}),
\qquad \text{record\_id}_t=d_{\mathrm{history}}(R_t).
$$

A changed canonical object should therefore have a different digest under the
collision-resistance assumption of SHA-256, and the next unchanged descendant
still points to the ancestor's old digest. This is integrity checking, not
authentication. A
party able to rewrite every object and `HEAD` can construct another internally
consistent lineage; there are no signatures, trusted timestamps, or remote
witnesses.

## 5. Why the software is designed this way

### Four named measures, no generic score

Entropy change, outcome surprisal, KL divergence, and mutual information can
coincide in a special uniform deterministic partition but differ in general.
Separate function names preserve the model's meaning and make a wrong
interpretation reviewable. A generic “information gain,” “fitness,” or
“intelligence” score would erase necessary assumptions.

### Pure package, caller-owned model

The installed functions are deterministic and side-effect free. Keeping model
construction, policy, application I/O, and domain interpretation outside the
package allows each number to be reproduced from its explicit inputs. It also
prevents a measurement helper from silently becoming an agent framework.

### Strict standard-stream protocols

One JSON object in and one canonical JSON object out is enough for shells,
agents, tests, and other languages. Exact schemas, duplicate-key rejection,
finite-number checks, and explicit errors turn malformed assumptions into
visible failures. An HTTP service, plugin layer, database, or session framework
would add state and failure modes without improving the four equations.

### Separate source-only applications

Each app owns one transition and can reject inconsistent composition at its
boundary. Candidate Runner cannot read the active fixture; the controller gets
both complete forecasts before reveal; Forecast Assay does not select; Selection
Gate recomputes rather than trusts reported aggregates. These separations make
identity swapping, evidence mismatch, and target leakage testable.

### One generation, not an autonomous loop

The controller returns after one generation. This keeps mutation-policy updates,
budgets, repetition, deployment, and stopping visible to the caller. Hidden
iteration would combine mechanism with policy and make an apparently simple
measurement repository responsible for an optimizer it could not generally
validate.

### Explicit draws and content IDs

An explicit draw makes mutation replayable and testable. Canonical content IDs
make the exact parent and child portable across processes. Neither device proves
that a candidate is good or that trusted code produced it.

## 6. Repository hypotheses and falsifiers

### H1: measurement conformance

**Claim.** For accepted finite discrete inputs, the four public functions agree
with their named mathematical definitions within the documented
double-precision contract.

**Falsifier.** A valid counterexample that violates an exact identity, support
boundary, non-negativity rule, or documented numerical tolerance.

**Current evidence.** Unit and property-style regression cases cover exact
values, near-equal distributions, subnormal probabilities, support mismatch,
normalization boundaries, and direct/CLI agreement. This supports code
conformance; it does not validate a caller's probability model.

### H2: boundary transparency

**Claim.** Splitting observation, variation, expression, assay, retention, and
one-generation orchestration into strict processes makes ordering, identity,
and evidence errors observable without adding a general framework.

**Falsifier.** An accepted composition that swaps parent and child identity,
forecasts after reveal, compares different evidence, trusts a forged aggregate,
or advances an unknown selected candidate.

**Current evidence.** Focused app tests and the complete controller integration
test exercise representative ordering, identity, evidence-alignment, and
recomputation paths. The claim is limited to the documented version 1 schemas
and trusted local processes; it is not a proof that every possible composition
fault has a dedicated regression test.

### H3: fixed-fixture generation prediction

For the checked-in `v3` request, the incumbent assigns each delivered target
probability $2/3$, while the challenger assigns $5/6$. Therefore

$$
L_E(\text{incumbent})=-\log_2(2/3),
$$

$$
L_E(\text{challenger})=-\log_2(5/6),
$$

and

$$
\Delta=\log_2(5/4)\approx0.321928\text{ bits}>0.05.
$$

**Claim.** The controller promotes the child, preserves its content ID, and
identifies `v3` only after, for each probe, both candidate forecasts were
captured before that probe's reveal.

**Falsifier.** Any different measurement, ordering, identity, observation count,
or retention result under the checked-in request. This is a deterministic
fixture hypothesis, not evidence of general learning.

### H4: history tamper visibility

**Claim.** Changing a canonical stored record without finding a SHA-256
collision or consistently rebuilding its descendants causes `metering-history
verify` to reject the history.

**Falsifier.** An altered object accepted under its old record ID, or a broken
parent/reachability relation accepted by `verify`. This claim excludes
authentication, rollback detection against an external checkpoint, and an
attacker who rewrites the entire lineage.

### H5: external adaptation experiment

The repository's scientific hypothesis is deliberately external:

> With initial candidates, variant generator, environment distribution,
> evaluation budget, and compute budget held fixed, repeated retention by lower
> development-set mean logarithmic loss yields lower mean logarithmic loss on
> untouched one-use test observations than a measurement-independent retention
> rule using the same initial state, mutation mechanism, matched exogenous draws
> where applicable, and proposal/compute budget.

For paired runs $j$, define

$$
D_j=L_{\text{test},\text{metered},j}
    -L_{\text{test},\text{control},j}.
$$

The directional alternatives are

$$
H_1:\mathbb E[D_j]<0,
\qquad
H_0:\mathbb E[D_j]\ge0.
$$

This requires predeclared environments, paired seeds or initial states, complete
pre-reveal forecasts, identical budgets, untouched final data, repeated runs,
and uncertainty reporting. $D_j$ is defined only for finite paired final losses;
an experiment permitting infinities must predeclare a separate extended-real
ordering or catastrophic-failure outcome and must not subtract two infinities.
Because different retention decisions can create different later parents,
matched random streams need not yield identical realized variants; an
experiment that requires identical proposals must instead predeclare a common
off-policy candidate stream or proposal tree. A paired estimator and one-sided
interval or test rule must be chosen before data are seen. Failure to meet that
rule is failure to support $H_1$, not a logical proof that the population
expectation is nonnegative. The checked-in four-fixture demonstration cannot
test the claim. Reusing the same finite cases for selection makes them
development data and invalidates a fresh-generalization claim.

## Primary references

- C. E. Shannon, “A Mathematical Theory of Communication,” 1948, introduces
  logarithmic information, entropy, and mutual information:
  [part I](https://doi.org/10.1002/j.1538-7305.1948.tb01338.x) and
  [part II](https://doi.org/10.1002/j.1538-7305.1948.tb00917.x).
- S. Kullback and R. A. Leibler, “On Information and Sufficiency,” 1951,
  introduces the directed information divergence used here:
  [DOI](https://doi.org/10.1214/aoms/1177729694).
- D. V. Lindley, “On a Measure of the Information Provided by an Experiment,”
  1956, connects expected posterior uncertainty change with experiment choice:
  [Project Euclid](https://projecteuclid.org/journals/annals-of-mathematical-statistics/volume-27/issue-4/On-a-Measure-of-the-Information-Provided-by-an-Experiment/10.1214/aoms/1177728069.full).
- T. Gneiting and A. E. Raftery, “Strictly Proper Scoring Rules, Prediction,
  and Estimation,” 2007, gives the proper-scoring interpretation of logarithmic
  loss: [JASA](https://www.tandfonline.com/doi/abs/10.1198/016214506000001437).
- A. P. Dawid, “Statistical Theory: The Prequential Approach,” 1984, supplies
  the forecast-then-observe evaluation perspective:
  [JRSS A](https://rss.onlinelibrary.wiley.com/doi/10.2307/2981683).
- R. C. Lewontin, “The Units of Selection,” 1970, states the abstract conditions
  for evolution by natural selection:
  [Annual Reviews](https://www.annualreviews.org/content/journals/10.1146/annurev.es.01.110170.000245).
- G. R. Price, “Selection and Covariance,” 1970, supplies the covariance and
  transmission decomposition used only as design rationale:
  [Nature](https://www.nature.com/articles/227520a0).
- K. Chen and F. H. Arnold, “Tuning the Activity of an Enzyme for Unusual
  Environments,” 1993, demonstrates sequential mutation and screening in
  laboratory directed evolution:
  [PNAS](https://pmc.ncbi.nlm.nih.gov/articles/PMC46772/).
- G. C. Cawley and N. L. C. Talbot, “On Over-fitting in Model Selection and
  Subsequent Selection Bias in Performance Evaluation,” 2010, supports the
  fresh-evaluation limitation:
  [JMLR](https://www.jmlr.org/papers/v11/cawley10a.html).
- NIST, *Secure Hash Standard (SHS), FIPS 180-4*, specifies SHA-256 and its
  message-digest purpose:
  [FIPS 180-4](https://csrc.nist.gov/pubs/fips/180-4/upd1/final).
- S. Haber and W. S. Stornetta, “How to Time-Stamp a Digital Document,” 1991,
  is historical primary work on hash-linked records; Metering does not implement
  its timestamping or signature system:
  [DOI](https://doi.org/10.1007/BF00196791).
