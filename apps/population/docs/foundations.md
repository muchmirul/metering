# Population archive foundations and hypotheses

## Boundary

The Population Archive is a trusted, source-only application. It composes
caller-owned candidate artifacts and evaluator evidence without changing
Metering's four-measure package. Mathematical identities, deterministic
implementation claims, and empirical search claims remain distinct.

It does not execute candidates, estimate probabilities, decide what task success
means, or establish that retained candidates generalize.

## Identity and replay

A candidate ID is the existing digest of normalized artifact content. An
experiment binds the task set, evaluator, runtime, behavior vocabulary, role,
and resource budget. A run identity is:

$$
r=\operatorname{SHA256}(c,e,k,\text{schema}),
$$

where $k$ is a unique replicate occurrence ID. Seed and runtime settings remain
recorded evidence but cannot replace $k$: a nondeterministic runtime can produce
distinct observations when rerun with the same seed.

Each canonical record hashes its complete body and predecessor. Every run also
binds a URI and SHA-256 receipt for caller-owned detailed evaluator evidence
without embedding protected cases. Replay checks the hash chain and every
derived result, but does not fetch or authenticate the external URI. This
detects accidental or partial modification. It does not authenticate a writer
who can replace the complete ledger and its external checkpoints.

SQLite is a normalized cache. The implementation's consistency requirement is:

$$
\operatorname{Index}(\operatorname{Replay}(L))=D,
$$

where $L$ is the canonical ledger and $D$ is every represented database row.
Selection never reads $D$.

## Named evidence

For replicate $j$ with $n_j$ task cases, task rate is:

$$
Q_j=\frac{\operatorname{passed}_j}{n_j}.
$$

For supplied pre-reveal target probabilities, empirical logarithmic loss is:

$$
L=-\frac{1}{\sum_j n_j}\sum_{j,i}\log_2 q_{j,i}(y_{j,i}).
$$

Metering computes each self-information term. A zero target probability makes
$L$ positive infinity; the application does not clip it.

Reliability is the explicit archive policy:

$$
R=\bar Q-\kappa s_Q.
$$

Here $s_Q$ is sample standard deviation for at least two replicates and is
defined as zero for exactly one replicate. This is a deterministic conservative
heuristic, not a confidence bound.

An optional coherent finite information model supplies outcome probabilities
$P(O=o)$ and posteriors $P(H\mid O=o)$ whose mixture recovers the supplied prior.
The application constructs the joint:

$$
P(O=o,H=h)=P(O=o)P(H=h\mid O=o)
$$

and asks Metering for $I(O;H)$. The experiment identity explicitly declares
whether this is a retention objective; missing evidence cannot silently alter
the objective set. The application does not call expected entropy reduction and
realized evidence the same quantity.

Resource cost remains the vector:

$$
C=(C_{actions},C_{energy},C_{gpu},C_{memory},C_{storage},C_{tokens},C_{wall}).
$$

No universal conversion between these coordinates is introduced.

## Novelty and Pareto retention

For aggregate behavior distributions over the experiment's fixed aligned
vocabulary, directed novelty is:

$$
N(c)=\min_{a\in\mathcal F\setminus\{c\}}
D_{\mathrm{KL}}(P_c\Vert P_a).
$$

The reference set contains other feasible candidates only. A singleton set has
novelty zero by application convention. Support mismatch can produce positive
infinity and is retained explicitly.

Protected admission is hard:

$$
\mathcal F=\{c:\text{protected}\land\text{safety}\land\text{budget}\}.
$$

The app computes non-dominance over separately directed task, reliability,
novelty, log-loss, optional information, and resource coordinates. It does not
compute a weighted sum or generic fitness score. Capacity truncation uses one
fixed, documented lexicographic policy, and all retained members are finally
ordered by immutable candidate ID.

Final-role experiments are structurally barred from archive construction and
parent allocation. The first final run also seals all later candidate,
development-run, archive, allocation, and recombination transitions in that
ledger while permitting additional runs of already declared final experiments.
Thus final evidence cannot precede a later selection transition in this
application.

## Exact parent draw

For $n>0$ archive members sorted by candidate ID and rational draw
$u=p/q\in[0,1)$, parent index is:

$$
i=\left\lfloor\frac{pn}{q}\right\rfloor.
$$

Each member has exact probability $1/n$. Integer arithmetic removes cumulative
ordering, floating boundary, and exponential-overflow ambiguity. The archive,
ordering, draw, probability, and selected identity are committed together.

## Typed recombination

For two skill artifacts, the locus set is the union of normalized regular-file
paths. An explicit choice function $K(\ell)$ names the parent supplying every
locus. Replay reconstructs:

$$
c'=\{\ell\mapsto c_{K(\ell)}[\ell]\},
$$

then recomputes the complete child identity. Both parents must contribute a
locus whose value differs from the other parent. This gives inspectable
provenance; it does not establish semantic compatibility or causal attribution.

## Falsifiable implementation hypotheses

### H1: ledger replay

**Claim.** Every accepted record has canonical encoding, a valid predecessor and
content hash, and a body reproduced from prior accepted state.

**Falsifier.** A malformed, reordered, hash-mismatched, duplicate-identity, or
semantically inconsistent record accepted by `verify`.

### H2: index reconstruction

**Claim.** Deleting and rebuilding SQLite reproduces every indexed fact, while a
changed row is rejected by `verify-index`.

**Falsifier.** A query or selection-relevant row that cannot be reconstructed
from the ledger, or an altered row accepted as equivalent.

### H3: protected final separation

**Claim.** No final-role experiment can produce an archive or parent allocation,
and no search transition can follow the first final run.

**Falsifier.** Any accepted archive derived from final-role runs or accepted
candidate, development, archive, allocation, or recombination event after final
evaluation starts.

### H4: replayable allocation

**Claim.** The same archive member IDs and rational draw always select the same
candidate independent of insertion or database order.

**Falsifier.** Two accepted replays select different identities from the same
recorded inputs.

### H5: population benefit

**External empirical hypothesis.** Under a predeclared task distribution and
matched proposal, execution, and evaluation budgets, this archive policy can
outperform single-head recurrence on untouched final evidence.

No repository test establishes H5. Failure to observe benefit is evidence
against that experiment's hypothesis, not an implementation failure.

## Sources

- C. E. Shannon, “A Mathematical Theory of Communication,” 1948, supplies the
  entropy and mutual-information definitions:
  <https://doi.org/10.1002/j.1538-7305.1948.tb01338.x>.
- S. Kullback and R. A. Leibler, “On Information and Sufficiency,” 1951,
  supplies directed relative entropy:
  <https://doi.org/10.1214/aoms/1177729694>.
- T. Gneiting and A. E. Raftery, “Strictly Proper Scoring Rules, Prediction,
  and Estimation,” 2007, gives the proper logarithmic-scoring interpretation:
  <https://doi.org/10.1198/016214506000001437>.
- K. Deb et al., “A Fast and Elitist Multiobjective Genetic Algorithm: NSGA-II,”
  2002, is background for explicit non-dominated retention; this application
  does not implement NSGA-II:
  <https://doi.org/10.1109/4235.996017>.
