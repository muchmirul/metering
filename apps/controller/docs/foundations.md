# Evolution Controller foundations, design rationale, and hypotheses

## Exact role

Evolution Controller composes one explicit software generation:

```text
variation -> pre-reveal forecasts -> observation -> assay -> retention
```

It is the smallest executable place where the repository's separate app
boundaries become one state transition. It does not own a population, repeated
generations, mutation-policy learning, deployment, or stopping.

## Biological foundation and its limit

Lewontin describes three abstract requirements for evolution by natural
selection: variation, differential survival or reproduction, and heritable
correlation between parent and offspring. The version 1 composition maps those
ideas narrowly:

| Abstract biological role | Software mechanism |
|---|---|
| variation | Mutator creates one legal child |
| heritable continuity | unchanged genome loci pass from parent to child |
| expressed behavior | Candidate Runner emits probability forecasts |
| environmental assay | Observer reveals cases and Forecast Assay measures them |
| differential retention | Selection Gate chooses parent or child |
| another generation | caller places returned `next_parent.genome` into a new mutation request |

Laboratory directed evolution motivates the generate-screen-retain loop shape.
It does not prove that this mutation representation, fixture assay, or strict
pairwise rule improves software on future tasks. Calling the controller an
organism, natural selection, or autonomous self-evolution would be wrong.

The Price equation makes the separation between selection and transmission
explicit:

$$
\bar w\,\Delta\bar z
=\operatorname{Cov}(w_i,z_i)+\mathbb E[w_i\Delta z_i].
$$

Here $z_i$ is a parent trait, $w_i$ is descendant contribution, and
$\Delta z_i$ is within-lineage trait change. The covariance term describes
differential selection; the expectation term describes transmission change.
The controller does not calculate this population equation. It has one parent,
one child, and a deterministic retention gate. The equation is design rationale
for keeping mutation and selection as separately inspectable transitions.

## One-generation mathematics

Let $c_t$ be the parent, $Q_{\theta_t}(\cdot\mid c_t)$ the caller-declared
finite mutation distribution, and $u_t\in[0,1)$ the caller-declared draw.
Mutator realizes

$$
c'_t=T(c_t,Q_{\theta_t},u_t).
$$

Writing $c'_t\sim Q_{\theta_t}(\cdot\mid c_t)$ describes the mutation kernel
before a draw is chosen. The executable request is deterministic because it
contains $u_t$. Neither the controller nor Mutator generates hidden
randomness.

For each requested probe or case $x_i$, Candidate Runner emits complete
forecasts $q_{c_t}(\cdot\mid x_i,E)$ and
$q_{c'_t}(\cdot\mid x_i,E)$. Only after both responses exist does Observer
reveal $y_i$. The ordering invariant is

$$
q_{c_t,i},q_{c'_t,i}\quad\prec\quad y_i,
$$

where $\prec$ means “captured by this controller before.” This is a causal
call-order invariant inside the trusted local process, not a cryptographic
timestamp or proof about information a caller already knew.

Forecast Assay reports empirical mean logarithmic losses

$$
L_E(c_t)=-\frac1n\sum_{i=1}^{n}
\log_2q_{c_t}(y_i\mid x_i,E),
$$

$$
L_E(c'_t)=-\frac1n\sum_{i=1}^{n}
\log_2q_{c'_t}(y_i\mid x_i,E).
$$

Every term has a narrow meaning: $E$ is the declared evaluation identifier,
$x_i$ is the unique probe case, $y_i$ is the subsequently revealed target,
and $q_c(y_i\mid x_i,E)$ is the coordinate extracted from the candidate's
complete pre-reveal forecast.

For finite reports, Selection Gate computes

$$
\Delta_t=L_E(c_t)-L_E(c'_t)
$$

and, for a caller-declared threshold $\delta\ge0$, returns

$$
c_{t+1}=
\begin{cases}
c'_t,&\Delta_t>\delta,\\
c_t,&\text{otherwise}.
\end{cases}
$$

Equality retains the incumbent. The controller translates the selected content
identity into `next_parent`; it stores no lineage and never updates
$\theta_t$. If either report is infinite, Selection Gate applies its documented
extended-real ordering and does not form $+\infty-(+\infty)$.

For complete forecasts and a true target distribution $P_i$, the expected
per-case log loss satisfies

$$
\mathbb E_{Y_i\sim P_i}[-\log_2Q_i(Y_i)]
=H_2(P_i)+D_{\mathrm{KL},2}(P_i\Vert Q_i).
$$

This proper-scoring identity explains the choice of log loss. It does not turn
the two checked-in observations into proof of future performance.

## Identity and evidence bindings

The controller preserves these equalities:

$$
\begin{aligned}
\text{runner.parent.id}
&=\text{assay.incumbent.id}
=\text{mutation.parent.id},\\
\text{runner.child.id}
&=\text{assay.challenger.id}
=\text{mutation.child.id},\\
\text{selection.selected}
&\in\{\text{mutation.parent.id},\text{mutation.child.id}\}.
\end{aligned}
$$

Candidate Runner recomputes each genome's content digest. Selection Gate also
requires both reports to contain the same declared evaluation and exact set of
`(observation, target)` identifiers. These checks prevent accidental label
swaps and evidence mismatch. They do not authenticate the programs, prove model
provenance, or establish that an opaque evaluation string names trustworthy
data.

The controller also requires the parent and child `runner_model` values to be
equal for every probe and requires that value to remain unchanged across the
generation. A changed model makes the reports incomparable and fails closed.

## Why the software is designed this way

- **One generation per request:** repetition, budgets, mutation-policy updates,
  and stopping remain visible caller decisions instead of hidden optimizer
  state.
- **Subprocess composition:** every app is exercised through its documented
  standard-stream boundary. The controller cannot depend on convenient private
  imports that an external agent could not use.
- **Forecasts before reveal:** ordering prevents this implementation from using
  the returned Observer response to construct a forecast. The fixtures are
  public and `active_version` is a caller input, so this is not protection from
  a caller that already knows or leaks the answer.
- **Both candidates on the same evidence:** paired cases remove a gratuitous
  source of comparison noise and make evidence mismatch rejectable.
- **Forecast-envelope validation:** before reveal the controller checks a
  nonempty set of unique, normalized outcomes. After reveal it checks that the
  returned target is present. Candidate Runner owns completeness for its fixed
  model; the controller cannot prove completeness for an arbitrary domain.
- **Independent recomputation:** Selection Gate does not trust aggregate means;
  Candidate Runner does not trust candidate labels. Redundant checks are small
  and protect different boundaries.
- **Fail closed:** a failed component, incomplete identification, identity
  mismatch, or unknown selected candidate produces no retention decision.
- **No persistent lineage:** a lineage store would add recovery, concurrency,
  branching, and trust semantics unrelated to demonstrating one transition.

## Falsifiable hypotheses

### Composition hypothesis

For every successful version 1 generation:

1. Mutator returns distinct parent and child content identities;
2. both nonempty, unique, normalized forecast envelopes are captured before
   each corresponding Observer reveal;
3. the revealed target occurs in both normalized forecasts;
4. both assay reports use the exact Mutator identities and aligned cases;
5. Selection Gate's selected identity is parent or child; and
6. `next_parent` contains exactly the selected identity and genome.

An accepted response violating any item falsifies the controller's composition
claim. A component error must also falsify success rather than silently retain
the incumbent.

### Checked-in `v3` prediction

The example mutates only `hypothesis_probability_bps` from 5000 to 7500 while
keeping hypothesis `v3`. For each of the two `v3` read results,

$$
q_{\text{parent}}(y_i)=\frac23,
\qquad
q_{\text{child}}(y_i)=\frac56.
$$

Therefore

$$
L_E(\text{parent})=-\log_2(2/3)\approx0.584963,
$$

$$
L_E(\text{child})=-\log_2(5/6)\approx0.263034,
$$

$$
\Delta=\log_2(5/4)\approx0.321928>0.05.
$$

The falsifiable prediction is that the controller identifies `v3` in the two
declared probes, promotes the child, and returns the child as `next_parent`.
This is an algebraic fixture result, not adaptation evidence: the request was
constructed with the public answer in view.

The complementary `v4` regression test raises confidence in the wrong specific
hypothesis. One probe shares `v3`'s result while the other does not; the worse
mean causes parent retention. Together the tests show that the gate follows the
declared evidence rather than treating confidence itself as quality.

### External empirical hypothesis

A complete repeated-loop hypothesis must be tested outside this controller:

> Under predeclared environments, paired initial states, identical candidate and
> compute budgets, and untouched final observations, caller-driven repetition
> using the strict log-loss gate produces lower final test mean log loss than a
> measurement-independent retention baseline using the same mutation mechanism,
> matched exogenous draws where applicable, and proposal budget.

For paired run $j$, define

$$
D_j=L_{\text{test},\text{gated},j}
    -L_{\text{test},\text{control},j}.
$$

The directional claim is $\mathbb E[D_j]<0$. $D_j$ is defined only when both
final losses are finite; an experiment permitting infinities must predeclare an
extended-real comparison or separate catastrophic-failure outcome rather than
subtracting two infinities. Because retention changes later parents, matched
random streams need not produce identical realized proposals; identical
proposals require a predeclared common off-policy stream or proposal tree. The
experiment must also predeclare a paired estimator and one-sided interval or
test rule. Failure to meet that rule is failure to support the claim; an
interval wholly at or above zero is evidence against it under the declared
design. Repeatedly selecting on the same small fixture set cannot test this
claim.

## Limitations

- The controller supports one fixed Candidate Runner model over four public
  fixtures; it is not an arbitrary program or model executor.
- `active_version`, mutation support, draw, probes, threshold, and repetition
  are caller inputs. A caller can deliberately make the demonstration easy,
  impossible, or biased.
- Development loss monotonicity does not imply fresh-data generalization,
  safety, usefulness, or a global optimum.
- The strict pairwise rule can reject an intermediate regression needed to
  reach a better distant candidate.
- The evaluation identifier and candidate IDs are content/alignment mechanisms,
  not signatures or trusted provenance.
- There is no statistical uncertainty estimate, population diversity,
  recombination, parallel evaluation, checkpoint, rollback, deployment, or
  security sandbox.

## Primary sources

- R. C. Lewontin, “The Units of Selection,” 1970, states the abstract
  conditions for evolution by natural selection:
  [Annual Reviews](https://www.annualreviews.org/content/journals/10.1146/annurev.es.01.110170.000245).
- G. R. Price, “Selection and Covariance,” 1970, supplies the selection versus
  transmission decomposition used as design rationale:
  [Nature](https://www.nature.com/articles/227520a0).
- K. Chen and F. H. Arnold, “Tuning the Activity of an Enzyme for Unusual
  Environments,” 1993, demonstrates sequential variation and screening in
  laboratory directed evolution:
  [PNAS](https://pmc.ncbi.nlm.nih.gov/articles/PMC46772/).
- C. E. Shannon, “A Mathematical Theory of Communication,” 1948, supplies
  self-information and entropy:
  [part I](https://doi.org/10.1002/j.1538-7305.1948.tb01338.x) and
  [part II](https://doi.org/10.1002/j.1538-7305.1948.tb00917.x).
- T. Gneiting and A. E. Raftery, “Strictly Proper Scoring Rules, Prediction,
  and Estimation,” 2007, gives the proper-scoring basis for logarithmic loss:
  [JASA](https://www.tandfonline.com/doi/abs/10.1198/016214506000001437).
- A. P. Dawid, “Statistical Theory: The Prequential Approach,” 1984, motivates
  forecast-before-observation evaluation:
  [JRSS A](https://rss.onlinelibrary.wiley.com/doi/10.2307/2981683).
- G. C. Cawley and N. L. C. Talbot, “On Over-fitting in Model Selection and
  Subsequent Selection Bias in Performance Evaluation,” 2010, supports the
  fresh-evaluation limitation:
  [JMLR](https://www.jmlr.org/papers/v11/cawley10a.html).
