# Mathematical foundation and hypothesis

## Scope

This document describes the deterministic greedy maximum-predicted-result-
entropy reference policy.
The external-agent JSONL protocol is implemented separately, but its agent owns
probe selection and is not covered by the policy hypothesis below.

The shortest accurate name for the inference architecture is **finite,
noiseless Bayesian hypothesis identification with greedy Shannon-entropy query
selection**. For this fixture, whose useful probes have two possible results,
it is also an instance of generalized binary search or restricted twenty
questions. The implementation permits multi-valued results, so “binary search”
is not a complete name for the general mechanism.

Folder identity is a separate layer. Canonical regular-file manifests and
SHA-256 produce a content `tree_id`; hashing that ID with the parent snapshot ID
produces a lineage-specific `snapshot_id`. Those hashes identify modeled
content and ancestry. They do not supply probabilities, authenticate an author,
or justify the probe policy.

## Declared model

Let:

- $V$ be the unknown active version;
- $C$ be the finite set of remaining candidate versions;
- $q$ be one allowed probe; and
- $R_q=f_q(V)$ be that probe's result.

The current demo makes five material assumptions:

1. **Closed world:** the active sandbox is regular-file-manifest-equivalent to
   one registered fixture under the identity definition below.
2. **Uniform belief:** every remaining candidate has probability $1/|C|$.
3. **Deterministic, noiseless observations:** $f_q(v)$ always returns the same
   result for the same version and probe.
4. **Stationary state:** the sandbox, fixtures, and available observations do
   not change during a run.
5. **Equal observation cost:** selection values uncertainty reduction only;
   reads have no distinct time, money, or risk cost.

The uniform prior is a declared belief, not evidence about real version
frequency. `--active` selects a fixture directly; it does not sample a version
from that prior.

Before emitting `identified`, the controller requires the canonical sandbox
regular-file-manifest hash to equal the selected version's `tree_id`. Thus an
extra, missing, renamed, or byte-changed regular file rejects the closed-world
hypothesis instead of being silently ignored. Empty directories and filesystem
metadata are outside this identity.

A probe partitions the candidates into result cells:

$$
C_{q,r}=\{v\in C:f_q(v)=r\}.
$$

`outcomes()` constructs the predicted result distribution. Under the current
uniform belief,

$$
P(R_q=r)=\frac{|C_{q,r}|}{|C|}.
$$

After the active sandbox returns $r$, exact Bayesian conditioning is

$$
P(V=v\mid R_q=r,q)
=\frac{P(R_q=r\mid V=v,q)P(V=v)}
       {\sum_{u\in C}P(R_q=r\mid V=u,q)P(V=u)}.
$$

`P(R_q=r | V=v,q)` is the observation likelihood. In this app it is the
indicator $\mathbf 1[f_q(v)=r]$. Combined with the uniform prior, the general
equation reduces to

$$
P(V=v\mid R_q=r)=
\begin{cases}
1/|C_{q,r}|, & v\in C_{q,r},\\
0, & v\notin C_{q,r}.
\end{cases}
$$

That is why `run()` can implement the posterior as exact candidate filtering.
This compressed candidate-set representation is correct only because the prior
is uniform and the observation is deterministic.

## Why result entropy is the selection rule

For predicted result probabilities $p_r$, `probe_score()` asks Metering for
Shannon entropy in bits:

$$
H(R_q)=-\sum_r p_r\log_2 p_r.
$$

In general,

$$
I(V;R_q)
=H(R_q)-H(R_q\mid V)
=H(V)-\sum_rP(r)H(V\mid R_q=r).
$$

Because the result is a deterministic function of the version,
$H(R_q\mid V)=0$. Therefore, in this app,

$$
I(V;R_q)
=H(R_q)
=H(V)-\mathbb{E}_{r}[H(V\mid R_q=r)].
$$

`run()` chooses the probe with maximum $H(R_q)$. Under the declared model,
this exactly maximizes the expected reduction in candidate entropy for the
**next** observation. This is the finite deterministic case of one-step
Bayesian experimental design. Computing mutual information separately would
add machinery but return the same score here.

This equality is a mathematical identity under the stated assumptions, not an
empirical hypothesis and not evidence of intelligence, learning, or semantic
understanding.

## Why realized entropy reduction equals surprisal here

Suppose $n$ uniform candidates exist before a probe and the observed result
matches $k$ of them. Then

$$
P(r)=\frac{k}{n},\qquad
H(V)=\log_2 n,\qquad
H(V\mid r)=\log_2 k.
$$

Consequently,

$$
H(V)-H(V\mid r)
=\log_2\frac{n}{k}
=-\log_2 P(r).
$$

The right-hand side is the result's self-information, or surprisal. The demo
therefore predicts that each emitted candidate-entropy reduction equals its
emitted observed surprisal. Metering still reports `entropy` and
`self_information` under their separate names because this pointwise equality
does not hold in general for a nonuniform belief or noisy observation model.

For every successful observation under the version 1 model, the protocol
invariant can be written compactly as

$$
C'=C_{q,r},\qquad P(r)=\frac{|C'|}{|C|},
$$

$$
H_{\mathrm{before}}=\log_2|C|,
\qquad H_{\mathrm{after}}=\log_2|C'|,
$$

$$
I(r)=\log_2\frac{|C|}{|C'|}
=H_{\mathrm{before}}-H_{\mathrm{after}}.
$$

An accepted `observe` response that violates these relations falsifies the
implemented uniform deterministic update.

## Content, lineage, and catalogue identity

Let $F(S)$ be the regular files below sandbox root $S$, `bytes(p)` the
complete file bytes, `rel_S(p)` its POSIX relative path, and $J$ the app's
canonical JSON encoding. For each file define the exact manifest object

$$
m_S(p)=\{\text{path}:\mathrm{rel}_S(p),
          \text{sha256}:\mathrm{SHA256}(\mathrm{bytes}(p)),
          \text{size}:|\mathrm{bytes}(p)|\}.
$$

If $p_1,\ldots,p_k$ are ordered by their relative paths, the manifest and
content ID are

$$
M(S)=[m_S(p_1),\ldots,m_S(p_k)],
$$

$$
\mathrm{tree\_id}(S)
=\mathrm{SHA256}(\mathrm{UTF8}(J(M(S)))).
$$

Two sandboxes are equivalent for version 1 identity exactly when

$$
S\equiv_M V\quad\Longleftrightarrow\quad M(S)=M(V).
$$

This is regular-file manifest equivalence, not literal filesystem equality:
permissions, timestamps, empty directories, and other metadata are not hashed.
Symlinks are rejected rather than followed.

Lineage and observation-catalogue identities bind different objects. For
parent snapshot ID $p$, tree ID $t$, and canonical probe documents
$q_1,\ldots,q_m$:

$$
\mathrm{snapshot\_id}
=\mathrm{SHA256}(\mathrm{UTF8}(J(\{
\text{parent\_snapshot\_id}:p,\text{tree\_id}:t\}))),
$$

$$
\mathrm{catalogue\_id}
=\mathrm{SHA256}(\mathrm{UTF8}(J(\{
\text{probes}:[q_1,\ldots,q_m]\}))).
$$

`tree_id` binds modeled regular-file content, `snapshot_id` binds that content
to one parent, and `catalogue_id` binds allowed observation definitions. Under
the collision-resistance assumption of SHA-256 they expose accidental changes;
none establishes authorship, authenticity, probability, or policy.

## Implemented-system hypothesis

The fixture matrix is:

| Version | `config/mode.txt` | `service/port.txt` |
|---|---|---|
| `v1` | `safe` | `8000` |
| `v2` | `safe` | `9000` |
| `v3` | `fast` | `8000` |
| `v4` | `fast` | `9000` |

The falsifiable hypothesis for the code as it exists is:

> Given an active sandbox regular-file-manifest-equivalent to one of `v1`
> through `v4`, a uniform prior, deterministic noiseless reads, and the current
> fixed fixtures, the reference policy identifies the correct snapshot in
> exactly two delivered
> read observations, and every selected probe maximizes current result entropy.

This entails concrete predictions:

- the initial candidate entropy is 2 bits;
- the listing has result entropy 0 bits;
- the mode and port reads each split the four candidates 2-to-2 and score 1 bit;
- stable catalogue order breaks the initial tie in favor of the mode read;
- the other read splits either surviving pair 1-to-1 and scores 1 bit;
- candidate entropy follows $2\rightarrow1\rightarrow0$ bits;
- each delivered result has surprisal 1 bit; and
- total delivered surprisal is 2 bits.

The hypothesis is falsified if any fixture is misidentified, needs other than
two reads, selects a lower-scoring probe, or violates either measured entropy
identity above. The focused application test checks those conditions for all
four active fixtures.

Within this fixed catalogue, two observations are minimal. Four equiprobable
versions begin with 2 bits of entropy, while every available probe has at most
two results on these fixtures and can deliver at most 1 bit.

## What this does not establish

Maximum result entropy is one-step optimal under this model. It is not generally
a proof of the globally shortest or cheapest decision tree. That broader
problem depends on the allowed probes, prior probabilities, branch structure,
and probe costs; optimal binary decision-tree construction is hard in general.

The current fixture also provides no evidence for a claim that entropy-guided
external agents handle realistic evolving folders with fewer or cheaper
observations. Testing that would require a declared corpus, external agent or
comparison policies, cost metric, noisy or out-of-catalogue cases, and repeated
runs. None belongs in this fundamental reference example yet.

A concrete external research hypothesis, not tested here, would be:

> On a preregistered corpus of finite, stationary, equal-cost identification
> tasks, greedy maximum-result-entropy selection uses fewer mean observations
> than fixed catalogue order or uniformly random available-probe selection.

The corpus, baseline tie behavior, random seeds, repeated-run count, and mean and
worst-case probe metrics must be declared in advance. The four symmetric
fixtures cannot support that comparative claim.

If a later protocol accepts nonuniform beliefs, noisy likelihoods, or unequal
probe costs, the controller must represent and update those quantities
explicitly. Silently reusing `matching_versions / remaining_versions` would be
mathematically wrong.

The external-agent JSONL mode also has no termination guarantee: an agent may
repeatedly choose an uninformative probe. Stable catalogue order resolves
reference-policy ties reproducibly, not scientifically. The materialized
sandbox is not an atomic snapshot locked against concurrent mutation, and final
manifest verification is not general time-of-check/time-of-use protection.

## Why the software uses this design

- Finite registered fixtures allow exact PMFs without estimation, smoothing, or
  invented probabilities.
- Deterministic observations make candidate filtering an exact posterior
  representation under the uniform model.
- Result entropy reuses one public Metering primitive; a separate mutual-
  information calculation would duplicate it for this deterministic channel.
- Immutable probe catalogues keep action meaning stable during a session.
- The public Metering subprocess boundary demonstrates the same integration an
  external tool can use without importing private package modules.
- External agents own probe choice; Observer owns sandbox validity, probability
  construction, conditioning, and completion checks.
- Final manifest verification prevents identification from resting only on a
  partial observation path.

A global decision-tree optimizer returns the same two-read tree for these
fixtures but adds machinery. The narrow useful mechanism is therefore the
greedy one-step rule with explicit assumptions and regression-tested identities.

## Primary sources

- C. E. Shannon, “A Mathematical Theory of Communication,” 1948, defines the
  finite-discrete entropy and conditional-information foundation used here:
  [part I](https://doi.org/10.1002/j.1538-7305.1948.tb01338.x) and
  [part II](https://doi.org/10.1002/j.1538-7305.1948.tb00917.x).
- D. V. Lindley, “On a Measure of the Information Provided by an Experiment,”
  1956, formulates information from prior-to-posterior change and its use in
  experiment selection: [Project Euclid](https://projecteuclid.org/journals/annals-of-mathematical-statistics/volume-27/issue-4/On-a-Measure-of-the-Information-Provided-by-an-Experiment/10.1214/aoms/1177728069.full).
- R. D. Nowak, “The Geometry of Generalized Binary Search,” 2011, describes
  greedy balanced querying over a finite hypothesis space and states the
  conditions needed for stronger query-complexity guarantees:
  [author manuscript](https://nowak.ece.wisc.edu/GBS_arxiv_v3.pdf) and
  [DOI](https://doi.org/10.1109/TIT.2011.2169298).
- L. Hyafil and R. L. Rivest, “Constructing Optimal Binary Decision Trees is
  NP-Complete,” 1976, establishes why one-step greedy selection must not be
  called a general global optimizer: [DOI](https://doi.org/10.1016/0020-0190(76)90095-8).
- NIST, *Secure Hash Standard (SHS), FIPS 180-4*, specifies SHA-256, used only
  for the app's content and lineage identifiers:
  [FIPS 180-4](https://csrc.nist.gov/pubs/fips/180-4/upd1/final).
