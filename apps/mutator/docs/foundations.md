# Mutator foundations, design rationale, and hypotheses

## Biological role and its limit

Evolution by natural selection requires variation, differential retention or
reproduction, and heritable relation between parent and offspring. Mutator
implements only variation plus exact inheritance of every unchanged accepted
JSON atom.

The closest engineering analogy is laboratory directed evolution:

```text
generate variant -> assay variant -> retain or reject -> repeat
```

This application implements only `generate variant`. It contains no phenotype
assay, reproductive weight, population, selection, or repetition.

The Price equation helps separate transmission change from differential
selection:

$$
\bar w\,\Delta\bar z
=\mathrm{Cov}(w_i,z_i)+\mathbb E[w_i\Delta z_i].
$$

Here $z_i$ is a parent trait, $w_i$ is descendant contribution, and
$\Delta z_i$ is within-lineage trait change. Mutator is loosely analogous to
the transmission/variation term. It computes neither the population covariance
nor biological fitness, so the equation is responsibility-splitting rationale,
not an implemented measure.

## Legal one-locus neighborhood

Let a flat genome be $c=(c_1,\ldots,c_d)$, and let $C(a)$ be the app's
canonical JSON spelling of atom $a$. Catalogue locus $\ell$ has a finite legal
allele set $A_\ell$. The legal one-step neighborhood is

$$
\mathcal S(c)=\{(\ell,a):a\in A_\ell,\ C(a)\ne C(c_\ell)\}.
$$

For supported mutation $s=(\ell,a)$, define its transition by

$$
[T_s(c)]_r=
\begin{cases}
a,&r=\ell,\\
c_r,&r\ne\ell.
\end{cases}
$$

The child therefore has canonical-atom Hamming distance one from the parent:

$$
d_H^C(c,T_s(c))
=\sum_{r=1}^{d}\mathbf 1[C(c_r)\ne C([T_s(c)]_r)]=1.
$$

Canonical comparison matters because JSON Boolean `true` and JSON number `1`
are distinct legal atoms even though some host-language equality operators
treat them as equal.

This is a causal and maintenance boundary, not a claim that biology mutates one
site at a time. A one-locus transition is inspectable, its legal alternatives
are finite, and unchanged values have unambiguous inheritance. Recombination or
multi-locus changes need a different explicit protocol because they change
credit-assignment and identity semantics.

The catalogue describes everything legal; the mutation distribution describes
what has positive policy support in this request. A legal catalogue mutation
may be omitted from the support and thereby receive probability zero.

## Mutation kernel and explicit draw

For parent $c$ and caller-owned policy parameters $\theta$, an abstract
mutation kernel is

$$
Q_\theta(c'\mid c).
$$

The request supplies its finite positive support explicitly as canonically
ordered mutations $s_1,\ldots,s_k$ with probabilities
$q_1,\ldots,q_k$. For the caller's draw $u\in[0,1)$, define cumulative mass

$$
F_j=\sum_{r=1}^{j}q_r
$$

and select

$$
J=\min\{j:u<F_j\},
\qquad c'=T_{s_J}(c).
$$

The strict upper-bound comparison gives half-open intervals and makes boundary
behavior explicit. Metering accepts a total within its documented absolute
tolerance of one without renormalizing. If floating-point cumulative mass does
not cover the supplied draw, Mutator rejects the request; it does not silently
assign a residual tail to the final mutation.

There is no internal random-number generator. Before a draw is supplied, one
may write $c'\sim Q_\theta(\cdot\mid c)$. Once the request contains $u$, the
program is a deterministic transition. The caller can use a seeded generator,
a hardware source, or systematic search without changing Mutator's contract.

## Entropy and selected-mutation surprisal

For supported mutation $s_j$, Metering reports

$$
I_2(s_j)=-\log_2q_j.
$$

This is the selected event's self-information or surprisal. Across an exact
finite mutation PMF, expected surprisal is entropy:

$$
H_2(Q)=\sum_{j=1}^{k}q_jI_2(s_j)
=-\sum_{j=1}^{k}q_j\log_2q_j.
$$

For an exactly normalized distribution,

$$
0\le H_2(Q)\le\log_2k,
$$

with the upper bound at the uniform distribution. The implementation measures
the supplied floating-point values under Metering's documented normalization
tolerance; it never edits them to force the exact mathematical bound.

Neither equation contains an assay result. Consequently:

```text
high mutation entropy does not imply productive exploration
high selected-mutation surprisal does not imply novelty or value
rare does not mean good
```

Quality can be investigated only after expressing the child in a declared
environment and evaluating it under a separately declared criterion.

## Content and transition identity

For canonical JSON serialization $C$, a candidate content identity is

$$
\text{candidate\_id}(c)
=\mathrm{SHA256}(\mathrm{UTF8}(C(\{
\text{genome}:c,
\text{genome\_schema}:\texttt{flat-json-atoms-v1},
\text{schema\_version}:1
\}))).
$$

`catalogue_id` similarly binds the normalized catalogue and schema.
`mutation_id` binds schema version, catalogue ID, parent candidate ID, locus,
before value, and after value. It identifies a declared parent-to-child
transition, not the sampling event: draw and mutation probability are not part
of that digest.

These hashes make replay, comparison, and cross-process binding explicit under
the collision-resistance assumption of SHA-256. They are not signatures,
timestamps, author identities, lineage storage, or proof of trusted execution.

## Why the software uses this narrow design

- **Flat JSON atoms:** strings, safe integers, Booleans, and null have portable
  canonical identities without a code loader or recursive object semantics.
- **Exactly one locus:** the smallest nontrivial heritable change is easy to
  inspect and test.
- **Caller-supplied probability mass over explicit positive support:** mutation
  policy stays visible; legal but omitted mutations have zero support, and the
  app neither invents missing mass nor estimates a distribution.
- **Caller-supplied draw:** replay does not depend on hidden process randomness.
- **Canonical ordering:** semantically reordered catalogues and support arrays
  select the same interval and produce the same identities.
- **Separate entropy and surprisal:** distribution spread and realized event
  rarity remain correctly named instead of becoming a vague exploration score.
- **No assay or gate:** variation cannot quietly decide that its own child is
  beneficial.

## Falsifiable hypotheses

### Implementation hypothesis

For every accepted version 1 request:

1. the child differs from the parent at exactly one catalogue locus;
2. the replacement is a legal non-parent allele with positive supplied support;
3. every unchanged locus retains the same accepted JSON atom after canonical
   serialization;
4. the selected canonical support interval contains the supplied draw;
5. entropy and surprisal equal Metering's public results;
6. content and transition IDs follow their documented canonical formulas; and
7. semantically reordered catalogue and support arrays produce the same output.

A counterexample to any item falsifies the implementation claim. These are
tested software invariants, not evidence that mutation improves a candidate.

### External one-locus-loop hypothesis

A defensible directional hypothesis for a complete external system is:

> Under a predeclared catalogue, mutation mechanism, assay, retention rule,
> initial state, and proposal/compute budget, a loop using Mutator's one-locus
> proposals produces lower final mean log loss on untouched observations than a
> predeclared measurement-independent retention baseline.

For paired run $j$, define

$$
D_j=L_{\text{test},\text{mutator-loop},j}
    -L_{\text{test},\text{control},j},
$$

with $H_1:\mathbb E[D_j]<0$ and $H_0:\mathbb E[D_j]\ge0$ when both paired final
losses are finite. An experiment permitting infinities must predeclare an
extended-real comparison or a separate catastrophic-failure outcome rather
than subtracting two infinities. The experiment must declare the reachable
graph, proposal policy, baseline, matched exogenous draws where applicable,
environment sampling, stopping rule, fresh evaluation, and a one-sided
interval or test rule before running. Failure to meet that rule is failure to
support $H_1$; an interval wholly at or above zero is evidence against it under
the declared design.

Reachability is a necessary structural condition, not proof of improvement. A
strict gate can fail even when a better distant candidate exists if every path
requires an intermediate measured regression. Different retention paths can
also produce different later parents, so identical proposals require a
predeclared common off-policy stream or proposal tree. Mutator alone cannot run
this experiment.

### Explicit non-hypothesis

There is no hypothesis that increasing $H_2(Q)$ or selecting a higher-surprisal
mutation improves discovery. Those measurements describe the declared mutation
policy, not its consequences.

## Limitations

- Version 1 supports only flat JSON-atom genomes and one-locus replacement.
- JSON strings are not Unicode-normalized; distinct code-point sequences remain
  distinct content.
- There is no recombination, epistasis model, population, phenotype execution,
  mutation-policy learning, selection, lineage persistence, or stopping rule.
- One-step inspectability does not solve long-horizon credit assignment.
- Hash identity relies on canonical content and collision resistance; it does
  not establish provenance or authenticity.

## Primary sources

- C. E. Shannon, “A Mathematical Theory of Communication,” 1948, supplies the
  entropy and self-information definitions:
  [part I](https://doi.org/10.1002/j.1538-7305.1948.tb01338.x) and
  [part II](https://doi.org/10.1002/j.1538-7305.1948.tb00917.x).
- R. C. Lewontin, “The Units of Selection,” 1970, states the abstract conditions
  for evolution by natural selection:
  [Annual Reviews](https://www.annualreviews.org/content/journals/10.1146/annurev.es.01.110170.000245).
- G. R. Price, “Selection and Covariance,” 1970, separates differential
  selection from transmission change:
  [Nature](https://www.nature.com/articles/227520a0).
- K. Chen and F. H. Arnold, “Tuning the Activity of an Enzyme for Unusual
  Environments,” 1993, demonstrates sequential mutation and screening in
  laboratory directed evolution:
  [PNAS](https://pmc.ncbi.nlm.nih.gov/articles/PMC46772/).
- NIST, *Secure Hash Standard (SHS), FIPS 180-4*, specifies SHA-256:
  [FIPS 180-4](https://csrc.nist.gov/pubs/fips/180-4/upd1/final).
