# Biological and mathematical foundations

## Short answer

Each request is a **one-shot probabilistic screening assay**. The executable
can handle one request and exit or stream independent requests with `--jsonl`.
It is not mutagenesis and it is not an evolutionary system. A complete
caller can place this assay inside a **directed-evolution-inspired
variation-screen-retain loop**, but mutation, inheritance, selection, and
repetition all remain outside Forecast Assay. The checked-in composition assigns
those roles to other apps and still leaves repeated generations to its external
caller.

The mathematical foundation is **Shannon self-information** per revealed
target and its application-owned arithmetic mean, which is the **empirical mean
logarithmic loss**. It is not a neural architecture. A transformer may be one
kind of candidate being evaluated, but no neural structure is required by the
measurement.

## Biological paradigm

Literal mutagenesis means producing genetic mutations. Forecast assay does not
produce or alter anything; its name describes only the screening operation. In
an optional directed-evolution software analogy, responsibilities remain:

| Biological idea | Owner in this design |
|---|---|
| variation or mutation | Mutator or a standalone external caller |
| heritable candidate representation | Mutator plus the composing caller |
| environment and observations | Observer and Evolution Controller, or a standalone caller |
| assay of a candidate phenotype | this application measures declared forecasts |
| retention or selection | Selection Gate, composed by Evolution Controller, or a standalone caller |
| repeated generations | external caller |

Lewontin's minimal conditions for evolution by natural selection are variation,
differential survival or reproduction, and heritable correlation between
parent and offspring. The executable implements none of those conditions.
Calling its mean “biological fitness,” “natural selection,” “self-evolution,”
or “neuroevolution” would therefore claim machinery that is absent.

Directed evolution is the closer analogy for a caller-owned loop: generate
variants, screen them under a declared assay, retain according to an external
rule, and repeat. Laboratory directed evolution has demonstrated that repeated
mutation and screening can improve a selected property. That result motivates
the loop shape; it does not prove that any software mutation or selection rule
will improve predictive performance.

The accurate boundary is:

```text
caller or composing apps: vary -> obtain pre-reveal forecasts -> observe
                                                                    |
                                                                    v
forecast assay: validate -> measure target log loss -> report -> next line or exit
                                                                    |
                                                                    v
caller or composing apps: compare -> retain or reject -> repeat or stop
```

The checked-in Mutator, Candidate Runner, Observer, Selection Gate, and
Controller can fill those composing roles; a standalone caller can supply the
same responsibilities through the public boundary.

## Mathematical foundation

For candidate `c`, fixed evaluation `e`, observation `x_i`, revealed target
`y_i`, and the target probability supplied by the caller,

```text
p_i = q_c(y_i | x_i, e)
```

the caller's complete pre-reveal forecast must satisfy

```text
sum_y q_c(y | x_i, e) = 1.
```

Only the realized coordinate `p_i` is needed to compute that outcome's
logarithmic loss. This is why the request can stay small. The omitted
coordinates still matter to the scoring theorem, so the app cannot verify that
the original forecast was complete, normalized, or captured before reveal.

The app calls Metering's public measure at base 2:

```text
I_i = self_information(p_i, base=2) = -log2(p_i) bits
```

For `n` observations with finite results, the app then reports:

```text
L_n(c) = (1/n) sum_i I_i
       = -(1/n) sum_i log2 q_c(y_i | x_i, e)
```

`L_n` is empirical mean logarithmic loss, also called average negative
logarithmic score or mean target surprisal. It is equivalently the negative
base-2 logarithm of the geometric mean target probability. The arithmetic mean
is owned by this application; it is not a fifth Metering measure.

Explicitly,

```text
2^(-L_n(c)) = (product_i q_c(y_i | x_i, e))^(1/n).
```

If any delivered target was assigned probability zero, then

```text
L_n(c) = +infinity.
```

The app preserves that extended-real result rather than introducing a post-hoc
epsilon or clipping rule.

For heterogeneous cases, let `P_i` be the true target distribution for case
`i` and `Q_c,i` the candidate's complete forecast. Conditional on the submitted
cases, expected logarithmic loss decomposes as:

```text
E[L_n(c) | x_1, ..., x_n]
  = (1/n) sum_i [
      H_2(P_i) + D_KL,2(P_i || Q_c,i)
    ].
```

`H_2(P_i)` is the Bayes-optimal expected log loss relative to the declared
per-case distribution and conditioning information; additional predictors can
change that distribution. The term
`D_KL,2(P_i || Q_c,i)` is excess expected loss from forecast mismatch. Because
KL divergence is nonnegative, expected log loss is uniquely minimized by
reporting `Q_c,i = P_i`. This is the strictly proper logarithmic-scoring result.
It applies only when each `Q_c,i` is coherent, normalized, and committed before
`Y_i` is revealed. Without precommitment, a caller can submit probability `1`
after every reveal and manufacture zero loss.

`L_n` is always a deterministic equal-weight summary of the submitted rows.
Interpreting it as an estimate of future risk additionally needs a declared
sampling design. Independence is not needed to calculate the mean, but
correlation, adaptive case choice, and reuse affect its uncertainty and what
population it can represent.

The quantity should not be renamed:

- it is not entropy, because the app does not average over one supplied full
  distribution;
- it is not a KL-divergence call, because the app does not receive `P` and `Q`;
- it is a negative log-likelihood only when the supplied conditional
  probabilities jointly define the caller's likelihood model; and
- it does not by itself establish calibration, causal adaptation, usefulness,
  or generalization.

Changing the log base changes the unit, not candidate ordering. A zero target
probability has infinite loss. The app deliberately does not clip, smooth,
normalize, or silently repair it.

## Why the software uses this narrow design

- **Target-only input:** one realized probability is the smallest sufficient
  input for the named self-information call. The tradeoff is explicit: full-
  forecast normalization, support, and precommitment remain caller-owned and
  unverifiable at this boundary.
- **Equal weighting:** the app exposes the denominator and avoids silently
  inventing environment or importance weights.
- **No clipping or smoothing:** impossible-event forecasts remain visible and
  the caller's declared probability model is not rewritten.
- **Base 2:** results are auditable in bits; another base would only rescale all
  finite values by a positive constant.
- **Stateless one-shot and JSONL modes:** no earlier candidate can influence a
  later report; JSONL amortizes startup only.
- **Public Metering call:** one implementation owns the named
  `self_information` semantics.
- **Strict zero/one conversion checks:** numeric parsing cannot silently turn a
  finite loss into infinity or a positive loss into zero.

## Falsifiable hypotheses

### Implementation hypothesis

For every accepted request,

```text
value_bits_i = -log2(p_i)
finite aggregate = (1/n) sum_i value_bits_i
aggregate is infinite iff any p_i = 0.
```

The response must preserve the submitted identities and input order, reject
duplicate observation IDs, and remain independent of previous JSONL requests.
A counterexample falsifies this deterministic implementation claim.

### External adaptation hypothesis

The implementation alone has no “self-improvement” hypothesis because it does
not change candidates. A defensible hypothesis for a complete external loop is:

> Holding the initial candidates, variant generator, environment distribution,
> evaluation budget, and compute budget fixed, an agent that retains variants
> using lower development-set mean logarithmic loss will produce candidates
> with lower mean logarithmic loss on untouched, one-use held-out observations
> from the declared target environments than the same variant generator with a
> measurement-independent retention rule.

For repeated paired runs, let `L_test,metered` and `L_test,control` be the final
held-out losses. The directional hypotheses are:

```text
H1: E[L_test,metered - L_test,control] < 0
H0: E[L_test,metered - L_test,control] >= 0
```

A narrower parent-versus-mutant experiment can instead test the paired
difference `L_test,mutant - L_test,parent` under the same held-out cases. A
single lower development mean is not the hypothesis test.

The expectation is over repeated paired runs under the declared environment
and randomization procedure. The measurement-independent control retention
rule must be specified before running. Because `infinity - infinity` is
undefined, an experiment that can produce infinite final losses must also
predeclare a catastrophic-failure indicator or an extended-real ordering; it
must not invent epsilon clipping after seeing results.

The experiment must declare, before running:

1. the environments and their sampling distribution;
2. paired initial states, random seeds, variant budgets, and compute budgets;
3. a development set used for retention and a separate untouched test set;
4. forecasts committed before each target reveal;
5. the same `(evaluation, observation, target)` cases for every paired
   candidate;
6. a per-environment analysis and any weighting rule; and
7. repeated runs plus uncertainty for the paired loss difference.

If the claim is “improves in different environments,” a better pooled mean is
not sufficient: one large environment can hide regression in another. Report
each predeclared environment separately and define an explicit non-regression
tolerance if improvement is required across all of them.

Adaptive reuse of a finite evaluation set makes it part of training. That can
overfit the retention criterion, so final evidence requires fresh held-out
cases. The paired estimator and one-sided interval or test rule must be declared
before data are seen. Failure to meet that rule is failure to support the
directional hypothesis; an interval wholly at or above zero is evidence against
it under the declared design. Predeclared environment-specific requirements
must also be evaluated rather than replaced by a favorable pooled result.

## Refinement chosen for this app

The useful refinement is evidence identity, not more intelligence:

- every request names one fixed evaluation and unique observations;
- every target and identifier is echoed, so an agent can audit whether two
  candidate reports concern the same cases;
- callers use one request per environment, with observations weighted equally
  inside that request;
- strict number parsing rejects decimal-to-double conversion that changes
  exact zero or exact one; and
- canonical JSON remains valid even for escaped Unicode edge cases and parser
  failures.

The app still does not compare reports, run a statistical test, mutate a model,
choose a winner, or keep state. Those are policies, not irreducible measurement
operations.

The echoed identifiers support alignment but are not authenticated content.
The app cannot prove that a candidate label names the model that emitted the
probabilities or that an evaluation label names immutable evidence.

## Research sources

- U.S. National Library of Medicine, MeSH `Mutagenesis`, defines the literal
  biological term as generating genetic mutations: [NCBI MeSH](https://www.ncbi.nlm.nih.gov/mesh/68016296).
- R. C. Lewontin, “The Units of Selection,” 1970, states the minimal conditions
  for evolution by natural selection: [Annual Review DOI](https://doi.org/10.1146/annurev.es.01.110170.000245).
- K. Chen and F. H. Arnold, “Tuning the activity of an enzyme for unusual
  environments: sequential random mutagenesis of subtilisin E for catalysis in
  dimethylformamide,” 1993, is a primary directed-evolution mutation-and-screen
  demonstration: [PNAS full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC46772/).
- C. E. Shannon, “A Mathematical Theory of Communication,” 1948, defines the
  logarithmic information foundation and bit unit: [Bell System Technical
  Journal DOI](https://doi.org/10.1002/j.1538-7305.1948.tb01338.x).
- S. Kullback and R. A. Leibler, “On Information and Sufficiency,” 1951,
  supplies the divergence in the expected-log-loss decomposition:
  [DOI](https://doi.org/10.1214/aoms/1177729694).
- T. Gneiting and A. E. Raftery, “Strictly Proper Scoring Rules, Prediction,
  and Estimation,” 2007, gives the logarithmic score and its proper-scoring
  interpretation: [JASA DOI](https://doi.org/10.1198/016214506000001437).
- A. P. Dawid, “Statistical Theory: The Prequential Approach,” 1984, formalizes
  assessing forecasts sequentially against later observations:
  [JRSS A DOI](https://doi.org/10.2307/2981683).
- G. C. Cawley and N. L. C. Talbot, “On Over-fitting in Model Selection and
  Subsequent Selection Bias in Performance Evaluation,” 2010, analyzes
  overfitting a selection criterion: [JMLR full text](https://www.jmlr.org/papers/v11/cawley10a.html).
- C. Dwork et al., “The Reusable Holdout: Preserving Validity in Adaptive Data
  Analysis,” 2015, explains why adaptive holdout reuse threatens validity:
  [Science DOI](https://doi.org/10.1126/science.aaa9375).
