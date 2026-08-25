# Selection Gate foundations, design rationale, and hypotheses

## Biological role and its limit

Mutation creates variation. Selection changes which variants contribute to a
later generation. A measurement without differential retention is observation,
not selection.

In this software architecture:

```text
Mutator          -> variation
Candidate Runner -> expressed forecasts
Forecast Assay   -> measured evidence
Selection Gate   -> one differential-retention decision
Controller       -> inherited next parent
```

The gate therefore supplies one necessary transition in a
directed-evolution-inspired loop, not a complete evolutionary system.

The Price equation separates differential selection from transmission:

$$
\bar w\,\Delta\bar z
=\mathrm{Cov}(w_i,z_i)+\mathbb E[w_i\Delta z_i].
$$

Here $z_i$ is a parent trait, $w_i$ is descendant contribution, and
$\Delta z_i$ is within-lineage trait change. Selection Gate is only a
pairwise differential-retention analogue. It does not estimate population
covariance, reproductive fitness, or any term of this biological equation.

## Empirical log-loss evidence

For candidate $c$, declared evaluation identifier $E$, $n$ unique cases
$x_i$, revealed targets $y_i$, and supplied pre-reveal target probabilities
$q_c(y_i\mid x_i,E)$, Forecast Assay reports

$$
L_E(c)=-\frac{1}{n}\sum_{i=1}^{n}
       \log_2q_c(y_i\mid x_i,E).
$$

This is equal-weight empirical mean target surprisal in bits. The gate verifies
the same declared evaluation string and the same set of `(observation, target)`
labels, then recomputes every term and the mean. It does not receive the full
case $x_i$, environment contents, candidate executable, forecast timestamp,
or evidence provenance.

For a true finite target distribution $P$ and complete forecast $Q$,

$$
\mathbb E_{Y\sim P}[-\log_2Q(Y)]
=H_2(P)+D_{\mathrm{KL},2}(P\Vert Q).
$$

KL non-negativity makes $Q=P$ the unique expected log-loss minimum. This
strictly proper scoring statement requires a complete normalized forecast fixed
before target reveal. Forecast Assay receives only the realized coordinate, so
the gate cannot prove either prerequisite. Candidate Runner constructs complete
forecasts for its fixed model; Evolution Controller validates unique
normalized outcomes and local call order but cannot prove completeness for an
arbitrary domain. Those checks still are not cryptographic proof about another
process.

## Pairwise decision equation

For incumbent $c_t$, challenger $c'_t$, caller-declared threshold
$\delta\ge0$, and two finite reports, define

$$
\Delta_t=L_E(c_t)-L_E(c'_t).
$$

The gate returns

$$
\text{promote challenger}\quad\Longleftrightarrow\quad\Delta_t>\delta.
$$

Equality retains the incumbent. The threshold $\delta$ is a required observed
effect size in bits. It is not a p-value, confidence bound, numerical epsilon,
or test of statistical significance.

When every target probability is strictly positive,

$$
\Delta_t
=\frac1n\sum_{i=1}^{n}
 \log_2\frac{q_{c'_t}(y_i\mid x_i,E)}
                  {q_{c_t}(y_i\mid x_i,E)}.
$$

Exponentiating gives

$$
2^{\Delta_t}
=\left(
  \prod_{i=1}^{n}
  \frac{q_{c'_t}(y_i\mid x_i,E)}
       {q_{c_t}(y_i\mid x_i,E)}
 \right)^{1/n}.
$$

Thus $\Delta_t>\delta$ means the challenger's geometric mean of
realized-target probability ratios exceeds $2^\delta$. This is a paired
descriptive identity on the submitted cases. It is not by itself a Bayes factor;
that interpretation needs additional joint-likelihood and model assumptions.
It is also not a generalization guarantee.

An external controller may turn the decision into inheritance:

$$
c_{t+1}=
\begin{cases}
c'_t,&\Delta_t>\delta,\\
c_t,&\text{otherwise}.
\end{cases}
$$

The gate itself returns a selected identity and retains no parent state.

## Zero probabilities and extended-real ordering

For any delivered target,

$$
q_c(y_i\mid x_i,E)=0
\Longrightarrow
-\log_2q_c(y_i\mid x_i,E)=+\infty
\Longrightarrow
L_E(c)=+\infty.
$$

The application does not clip or smooth an impossible-event forecast. Its
extended-real decision table, with incumbent retention as the both-infinite
tie-break, is:

```text
infinite incumbent, finite challenger -> promote challenger
finite incumbent, infinite challenger -> retain incumbent
both infinite                         -> retain incumbent
```

When both means are infinite, `infinity - infinity` is undefined, so the gate
does not invent a finite improvement. When only one report is infinite, any
finite threshold is irrelevant to the extended-real ordering.

## What the rule guarantees

Conditioned on correct candidate binding and genuinely identical evidence, an
obeyed gate has a narrow deterministic guarantee:

- retaining the incumbent leaves the selected submitted development loss
  unchanged;
- when both reports are finite, promoting the challenger lowers that loss by
  strictly more than $\delta$; and
- a finite challenger replaces an infinite incumbent.

This is structurally a pairwise elitist `(1+1)` rule: one parent, one child, and
one retained identity. It is not the Gaussian `(1+1)` evolution strategy and
does not implement covariance-matrix adaptation or mutation-policy learning.

The guarantee does not imply lower future loss, cross-environment improvement,
safety, lower cost, better reasoning, or a global optimum. A strict hill climber
can reject an intermediate regression required to reach a better distant
candidate.

## Why the software uses this narrow design

- **Recompute instead of trust:** forged per-outcome values or aggregate means
  cannot directly control retention.
- **Align named evidence:** array order is irrelevant, while missing, changed,
  or duplicated cases fail explicitly.
- **Pairwise comparison:** one incumbent and one challenger are the smallest
  differential-retention boundary; populations and tournaments would introduce
  new policy.
- **Strict caller threshold:** equality behavior and required effect size are
  visible; there is no hidden tolerance in selection.
- **Explicit infinity rules:** undefined arithmetic never becomes an
  accidental promotion.
- **Opaque candidate labels:** the gate remains model-independent, while the
  controller must perform the actual content-to-execution binding.
- **Stateless transport:** no hidden incumbent, generation counter, or prior
  result can affect another request.

## Evidence content identity

Let $C$ be the gate's canonical JSON serialization and let
$\mathrm{cases}(E)$ be the list of exact
`{"observation": ..., "target": ...}` objects sorted by observation ID. The
returned identity is

$$
\text{evidence\_id}
=\mathrm{SHA256}(\mathrm{UTF8}(C(\{
\text{cases}:\mathrm{cases}(E),
\text{evaluation}:E,
\text{schema\_version}:1
\}))).
$$

This identifies the declared aligned evidence labels. It deliberately excludes
candidate IDs, probabilities, report bytes, environment case contents, authors,
and provenance. It is not a report hash, signature, or authentication token.

## Adaptive evaluation risk

Repeated selection against the same finite evaluation makes that evaluation
part of development. Monotonic development loss can coexist with worse fresh
performance through model-selection overfitting. The gate supplies no
uncertainty interval, dependence model, multiple-comparison correction,
fresh-holdout mechanism, or environment weighting.

A serious external experiment needs forecasts committed before reveal,
identical budgets and cases, a predeclared baseline, untouched final
observations, repeated paired runs, and uncertainty reporting. Separate
environments should be reported separately unless a weighting rule was declared
before selection.

## Falsifiable hypotheses

### Implementation hypothesis

For every accepted request, the gate:

1. recomputes both reports from supplied target probabilities;
2. compares the same declared evaluation and exact `(observation, target)` set;
3. ignores report array order;
4. promotes finite reports only under strict $\Delta>\delta$;
5. applies the documented extended-real infinity table;
6. returns an evidence content ID for the aligned labels; and
7. returns the same canonical decision for the same semantic request.

A counterexample falsifies the implementation claim.

### Conditional development-loss claim

If the candidate labels are correctly bound to executed candidates, complete
forecasts were captured before reveal, and the evidence labels name genuinely
identical cases, obeying the gate makes selected **verified development loss**
non-increasing for that one comparison. Violating any premise invalidates the
claim; the gate cannot establish those external facts from opaque labels.

### External adaptation hypothesis

> Across predeclared repeated runs, a gated mutate-evaluate loop produces lower
> final mean log loss on an untouched evaluation than a predeclared
> measurement-independent retention baseline under the same mutation mechanism,
> matched exogenous draws where applicable, and proposal/compute budget.

The experiment must predeclare a paired estimator and one-sided interval or
test rule. That finite-difference procedure applies only when both paired final
losses are finite. An experiment permitting infinities must instead predeclare
an extended-real comparison or a separate catastrophic-failure outcome; it
must not subtract two infinities or add epsilon clipping after seeing results.
Failure to meet the declared rule is failure to support the hypothesis, even
if development loss decreased monotonically; an interval wholly at or above
zero is evidence against it under the declared design. Selection Gate alone
cannot run or adjudicate that experiment.

Because retention changes later parents, matched random draws need not produce
identical realized proposals. A comparison requiring identical proposals must
predeclare a common off-policy proposal stream or proposal tree.

## Limitations

- Evidence identifiers are alignment data, not authenticated environment
  content or provenance.
- The gate never executes a candidate or verifies that its label matches a
  genome.
- The mean is unweighted and descriptive; no sampling or dependence assumptions
  are inferred.
- There is no population, tournament, Pareto frontier, statistical test,
  adaptive threshold, safety policy, deployment gate, rollback, or lineage.
- The rule can overfit reused evidence and get stuck at local optima.

## Primary sources

- C. E. Shannon, “A Mathematical Theory of Communication,” 1948, supplies the
  self-information foundation:
  [part I](https://doi.org/10.1002/j.1538-7305.1948.tb01338.x) and
  [part II](https://doi.org/10.1002/j.1538-7305.1948.tb00917.x).
- T. Gneiting and A. E. Raftery, “Strictly Proper Scoring Rules, Prediction,
  and Estimation,” 2007, formalizes the logarithmic proper scoring rule:
  [JASA](https://www.tandfonline.com/doi/abs/10.1198/016214506000001437).
- R. C. Lewontin, “The Units of Selection,” 1970, states the abstract conditions
  for evolution by natural selection:
  [Annual Reviews](https://www.annualreviews.org/content/journals/10.1146/annurev.es.01.110170.000245).
- G. R. Price, “Selection and Covariance,” 1970, separates differential
  selection from transmission:
  [Nature](https://www.nature.com/articles/227520a0).
- G. C. Cawley and N. L. C. Talbot, “On Over-fitting in Model Selection and
  Subsequent Selection Bias in Performance Evaluation,” 2010, documents
  selection-criterion overfitting:
  [JMLR](https://www.jmlr.org/papers/v11/cawley10a.html).
- C. Dwork et al., “The Reusable Holdout: Preserving Validity in Adaptive Data
  Analysis,” 2015, analyzes adaptive holdout reuse:
  [Science](https://doi.org/10.1126/science.aaa9375).
