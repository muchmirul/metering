# Population-search foundations, claims, and falsifiers

This document separates mathematical identities, deterministic implementation
claims, and external empirical hypotheses for the source-only Variant Search
application. It does not change the installed `metering` package or assign a
universal biological meaning to software artifacts.

## Mechanism boundary

The application receives already identified candidates and already produced
evaluation evidence. It stores ancestry and evidence, applies caller-declared
comparison and allocation rules, and resolves caller-supplied draws. It does not
produce the random source, construct the evaluator, execute candidates, or infer
what any metric means.

For one run law, write the logical state as

\[
S_t=(R_t,E_t,P_t,L_t,\Lambda),
\]

where \(R_t\) is the candidate registry and parent graph, \(E_t\) is immutable
evidence, \(P_t\) is the active pool, \(L_t\) is the hash-linked event sequence,
and \(\Lambda\) is the fixed caller-declared law. SQLite materializes this
state; canonical logical content, rather than SQLite page layout, defines the
reported state identity.

## Mathematical identities

### Normalized allocation

For non-negative declared masses \(a_i\), not all zero,

\[
p_i=\frac{a_i}{\sum_j a_j},
\qquad
p_i\ge0,
\qquad
\sum_i p_i=1.
\]

The implementation uses finite double-precision inputs and explicitly rejects
non-finite or zero-total mass.

### Weighted moments

For a normalized allocation \(p_i\),

\[
\mu_x=\sum_i p_i x_i,
\]

\[
\operatorname{Var}_p(x)=\sum_i p_i(x_i-\mu_x)^2,
\]

\[
\operatorname{Cov}_p(x,y)
=\sum_i p_i(x_i-\mu_x)(y_i-\mu_y).
\]

Covariance is association under declared weights, not causal attribution by
itself.

### Pareto dominance

For caller-declared objective directions, \(a\) dominates \(b\) exactly when
\(a\) is no worse on every objective and strictly better on at least one. This
is an ordering relation, not a claim that the objectives are complete or
correct.

### Declared scalarization and softmax

When one bounded ordering is required, the caller supplies every direction
\(d_k\in\{-1,+1\}\) and non-negative weight \(w_k\):

\[
s(c)=\sum_k w_kd_km_k(c).
\]

For explicit selection pressure \(\beta\ge0\),

\[
p_i
=\frac{\exp(\beta(s_i-\max_j s_j))}
{\sum_j\exp(\beta(s_j-\max_k s_k))}.
\]

Subtracting the maximum is numerically stable and does not change the exact
softmax ratio. The metric scales and weights remain experiment policy.

### Replicator update

For current allocation \(p_i\) and caller-derived non-negative contribution
factors \(q_i\),

\[
p'_i=\frac{p_iq_i}{\sum_jp_jq_j}.
\]

This applies differential future allocation. It does not define how capability,
safety, novelty, cost, or descendant yield should be converted into \(q_i\).

### Shannon entropy of reproductive allocation

The application reports the named Metering quantity

\[
H(P)=-\sum_i p_i\log_2p_i.
\]

It describes concentration of the declared active allocation. It is not itself
fitness, diversity quality, or intelligence. A uniform allocation over \(n\)
candidates has \(\log_2n\) bits; a point mass has zero bits.

### Price-equation accounting

For trait \(z_i\), contribution \(w_i\), average descendant change
\(\Delta z_i\), and declared population weights,

\[
\Delta\bar z
=
\frac{\operatorname{Cov}(w,z)}{\mathbb E[w]}
+
\frac{\mathbb E[w\Delta z]}{\mathbb E[w]}.
\]

The implementation names the first term `allocation_effect` and the second
`change_effect`. This is an accounting identity. Calling either term a causal
mechanism requires additional experimental assumptions.

## Deterministic draw rule

For a caller-supplied \(r\in[0,1)\), candidates are ordered explicitly and the
selected index is the first cumulative interval containing \(r\). Multiple
parents are drawn without replacement by removing the selected candidate and
renormalizing the remaining mass.

Determinism means the same canonical state, request, and draws produce the same
logical response. It does not mean the external source that generated a draw was
fair, unpredictable, or trustworthy.

## Heredity and recombination

The registry permits zero parents for a seed and one or two distinct parents for
a descendant. Generation is constrained by

\[
g(c)=
\begin{cases}
0,&\operatorname{parents}(c)=\varnothing,\\
1+\max_{p\in\operatorname{parents}(c)}g(p),&\text{otherwise}.
\end{cases}
\]

The Git recombiner implements path-level heredity only. Unique files are
inherited, identical files use the first parent, and every conflicting shared
path requires an explicit source parent. A two-parent Git commit records exact
source ancestry. This does not establish semantic compatibility or beneficial
recombination.

## Integrity model

Each candidate and evidence document is content-identified with the repository's
canonical JSON SHA-256 convention. Each state-changing event binds its event
kind, payload, and previous event ID:

\[
e_t=\operatorname{SHA256}
(\operatorname{CanonicalJSON}(k_t,u_t,e_{t-1})).
\]

`verify` checks SQLite integrity, foreign keys, candidate and evidence hashes,
generation rules, normalized pool mass, event-chain continuity, and agreement
between the latest pool event and the materialized pool table.

This detects inconsistent or accidental modification. An actor with full write
authority can replace the database and recompute all hashes. Authentication,
signing, replication, and append-only storage remain caller responsibilities.

## Tested implementation hypotheses

The automated tests are intended to falsify these bounded claims:

1. registering the same exact candidate/evidence twice is idempotent;
2. changing persisted manifest content without changing its identity is detected;
3. candidates failing a required constraint cannot enter the active pool;
4. Pareto-front calculation respects declared objective directions;
5. active weights remain normalized after softmax and replicator updates;
6. explicit parent draws are replayable and select distinct parents when two are
   requested;
7. Git recombination preserves unique files, applies every declared conflict
   choice, records both Git parents, and rejects an omitted conflict choice.

A failing test or a successful malformed request falsifies the corresponding
implementation claim.

## External empirical hypotheses

The repository does not yet establish these claims:

- retaining a population improves fresh-task performance over the single-head
  driver under equal compute;
- allocation entropy predicts useful behavioral diversity;
- two-parent path recombination produces useful children more often than mutation
  alone;
- a declared scalarization preserves the user's actual long-run objective;
- contribution-factor updates improve future proposal yield;
- Pi/Qwen proposals transfer beyond the development evaluator.

Testing them requires matched budgets, multiple seeds, versioned environments,
and a final evaluator that remains outside reproductive feedback. Reusing the
same final suite turns it into development evidence.

## Primary references

- Claude E. Shannon, “A Mathematical Theory of Communication,” 1948.
  <https://doi.org/10.1002/j.1538-7305.1948.tb01338.x>
- Richard C. Lewontin, “The Units of Selection,” 1970.
  <https://doi.org/10.1146/annurev.es.01.110170.000245>
- George R. Price, “Selection and Covariance,” 1970.
  <https://doi.org/10.1038/227520a0>
- Peter D. Taylor and Leo B. Jonker, “Evolutionarily Stable Strategies and Game
  Dynamics,” 1978. <https://doi.org/10.1016/0025-5564(78)90077-9>
- Manfred Eigen, “Selforganization of Matter and the Evolution of Biological
  Macromolecules,” 1971. <https://doi.org/10.1007/BF00623322>
- Kalyanmoy Deb et al., “A Fast and Elitist Multiobjective Genetic Algorithm:
  NSGA-II,” 2002. <https://doi.org/10.1109/4235.996017>
