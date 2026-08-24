# Biological and mathematical foundations

## Short answer

Each request is a **one-shot probabilistic screening assay**. The executable
can handle one request and exit or stream independent requests with `--jsonl`.
It is not mutagenesis and it is not an evolutionary system. A complete
external agent could place this assay inside a **directed-evolution-inspired
variation-screen-retain loop**, but mutation, inheritance, selection, and
repetition would all belong to that agent.

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
| variation or mutation | external agent |
| heritable candidate representation | external agent |
| environment and observations | external agent |
| assay of a candidate phenotype | this application measures declared forecasts |
| retention, reproduction, or selection | external agent |
| repeated generations | external agent |

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
external agent: vary -> obtain pre-reveal forecasts -> observe -> call assay
                                                              |
                                                              v
forecast assay: validate -> measure target log loss -> report -> next line or exit
                                                              |
                                                              v
external agent: compare -> retain or reject -> repeat or stop
```

## Mathematical foundation

For candidate `c`, fixed evaluation `e`, observation `x_i`, revealed target
`y_i`, and the target probability supplied by the caller,

```text
p_i = q_c(y_i | x_i, e)
```

the app calls Metering's public measure at base 2:

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

For a true finite distribution `P` and a complete forecast distribution `Q`,
expected logarithmic loss decomposes as:

```text
E_P[-log2 Q(Y)] = H_2(P) + D_KL,2(P || Q)
```

Because KL divergence is nonnegative, expected log loss is minimized by
reporting `Q = P`. This is the strictly proper logarithmic-scoring result. It
applies only when `Q` is a coherent normalized distribution and is committed
before `Y` is revealed. The app receives only the realized target coordinate,
so it cannot verify either condition. Without precommitment, a caller can submit
probability `1` after every reveal and manufacture zero loss.

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

## Falsifiable hypothesis

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
cases. The hypothesis is falsified when the paired test difference is not below
zero, when environment-specific requirements fail, or when the advantage
disappears on fresh cases.

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
