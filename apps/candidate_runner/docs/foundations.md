# Candidate Runner foundations, design rationale, and hypotheses

## Exact role

Candidate Runner is a finite **forecast-expression boundary**. A Mutator genome
declares one probability distribution over Observer's four fixture versions.
For one unrevealed probe, the runner maps that distribution to a complete
distribution over possible probe results.

In a loose directed-evolution analogy, the genome is a genotype and the emitted
forecast is one observable phenotype. The analogy stops there: the process has
no organism, development, reproduction, population, learning, or biological
fitness. Its operative foundations are finite probability, deterministic
pushforward distributions, Shannon entropy, prequential forecast ordering, and
content identity.

## Version-distribution equation

Let the fixture-version set be

$$
\mathcal V=\{v1,v2,v3,v4\}.
$$

A genome names one hypothesis $h\in\mathcal V$ and an integer confidence in
basis points. Define

$$
c=\frac{\text{hypothesis\_probability\_bps}}{10000},
\qquad 0.25\le c\le1.
$$

The runner constructs

$$
P_c(V=v)=
\begin{cases}
c,&v=h,\\
(1-c)/3,&v\ne h.
\end{cases}
$$

`V` is the candidate's latent fixture hypothesis. The lower bound $c\ge1/4$
ensures the named version is at least as probable as each individual
alternative. The four terms sum to one by construction:

$$
c+3\frac{1-c}{3}=1.
$$

This equality is exact over real numbers. In double precision, repeated
representation of $(1-c)/3$ can leave a last-place normalization residual; the
runner passes the constructed values to Metering, which accepts only totals
within its fixed $10^{-12}$ absolute tolerance and does not renormalize them.
This is a deliberately narrow family of probability models. The runner does
not estimate $c$, infer it from observations, or silently accept another family.

## Probe forecasts as pushforward distributions

For a supported probe $q$, let $f_q(v)$ be Observer's deterministic result
for version $v$. The random result is

$$
R_q=f_q(V).
$$

Several versions can produce the same result. The probability of result $r$
is therefore the sum of their version probabilities:

$$
P_c(R_q=r\mid q)
=\sum_{v\in\mathcal V}
  \mathbf 1[f_q(v)=r]P_c(V=v).
$$

This construction is called the pushforward of $P_c(V)$ through $f_q$.
It explains why Candidate Runner groups canonical result strings and uses
`math.fsum`: probabilities belonging to the same observable result must be
combined without changing their meaning.

The runner then asks Metering for

$$
H_2(R_q)=-\sum_r P_c(R_q=r\mid q)
                 \log_2P_c(R_q=r\mid q).
$$

Forecast entropy is uncertainty over the result before reveal. It is not the
loss after reveal and is not a quality score. A confidently wrong forecast can
have low entropy.

### Concrete fixture calculation

For hypothesis `v3`, the mode probe returns `fast` for `v3` and `v4`. Thus

$$
P_c(\text{fast})=c+\frac{1-c}{3}=\frac{1+2c}{3},
$$

$$
P_c(\text{safe})=2\frac{1-c}{3}.
$$

At $c=0.5$, these probabilities are $2/3$ and $1/3$, giving

$$
H_2(R_q)
=-\frac23\log_2\frac23-\frac13\log_2\frac13
\approx0.918296\text{ bits}.
$$

The listing probe has one possible result for every version, so its result
entropy is exactly zero even though the latent version distribution is not
certain. This is another reason not to treat entropy as candidate quality.

## Relation to post-reveal scoring

Candidate Runner emits a complete forecast before reveal. If Observer later
reveals result $y$, Forecast Assay can measure its realized logarithmic loss:

$$
\ell(c;q,y)=-\log_2P_c(R_q=y\mid q).
$$

For a true result distribution $P$ and candidate forecast $Q$, expected log
loss satisfies

$$
\mathbb E_{Y\sim P}[-\log_2Q(Y)]
=H_2(P)+D_{\mathrm{KL},2}(P\Vert Q).
$$

This gives a sound expected scoring interpretation only for a complete,
normalized forecast fixed before $Y$ is revealed. Candidate Runner supplies
the complete forecast and receives no active version or target. Evolution
Controller enforces the call order inside its trusted process. Neither app
provides a cryptographic proof of timing outside that process.

## Content identity

Candidate Runner independently checks the Mutator formula

$$
\text{candidate\_id}
=\mathrm{SHA256}\!\left(\mathrm{UTF8}\!\left(
C_{\mathrm{runner}}\!\left(\left\{
\text{genome}:g,
\text{genome\_schema}:\texttt{flat-json-atoms-v1},
\text{schema\_version}:1
\right\}\right)
\right)\right),
$$

where $g$ is the supplied genome and $C_{\mathrm{runner}}$ is Candidate
Runner's candidate-ID canonical JSON serialization. It matches Mutator's
candidate schema and encoding; it is not a repository-wide serializer. The
check prevents an accepted request from attaching one candidate ID to
different genome content.

The digest is a content identifier under the collision-resistance assumption of
SHA-256. It is not an author identity, signature, execution attestation, or
proof that a forecast was emitted by trusted code.

## Why the software uses this narrow design

- **One explicit model family:** the fixture example is small enough to inspect
  completely; a generic model adapter would hide rather than explain how its
  probabilities were constructed.
- **No active-version input:** the candidate/environment boundary prevents the
  runner from directly reading the answer it is meant to forecast.
- **Complete forecast output:** normalization and target support can be checked
  before the revealed coordinate is extracted for Forecast Assay.
- **Memoryless requests:** each response is a pure function of genome and probe,
  so there is no hidden cross-case learning or state to reproduce.
- **Duplicated fixture mapping:** importing Observer internals would let the
  candidate cross its environment boundary. Public integration tests instead
  make mapping drift fail visibly.
- **Public Metering call:** the app reuses the named entropy measure without
  creating another implementation or a new generic score.
- **Integer basis points:** the version 1 genome avoids ambiguous floating-point
  candidate identity while still exposing a finite confidence catalogue.

## Falsifiable hypotheses

### Implementation hypothesis

For every accepted version 1 request:

1. the candidate ID equals the canonical genome digest;
2. the four version probabilities follow the equation above and their
   floating-point total satisfies Metering's documented normalization
   tolerance without repair;
3. each result probability is the documented binary64 `math.fsum` aggregation
   of the pushforward terms for the declared probe;
4. result targets are complete, unique, and canonically ordered;
5. reported entropy agrees with Metering; and
6. no active fixture or revealed result is needed to construct the response.

A counterexample to any item falsifies the implementation. Tests compare the
duplicated fixture model with Observer's public behavior for every version and
supported read probe.

### Fixed-model prediction

For `v3`, increasing confidence from $c=0.5$ to $c=0.75$ changes the
probability of both checked-in `v3` read results from $2/3$ to $5/6$. On
those two cases the realized mean log loss must therefore change from

$$
-\log_2(2/3)\approx0.584963
$$

to

$$
-\log_2(5/6)\approx0.263034\text{ bits}.
$$

This prediction is falsified by a different complete forecast or realized loss
under the fixed fixture mapping. It says only that confidence moved toward the
known `v3` fixture in this toy model; it is not evidence of learning or
generalization.

### Explicit non-hypothesis

The design does **not** hypothesize that lower forecast entropy, higher genome
confidence, or a rarer mutation causes better future prediction. Any such claim
requires revealed outcomes, a predeclared sampling design, fresh evaluation,
and comparison with a baseline.

## Limitations

- The model covers exactly four public fixtures and three probes.
- Every request derives a fixed version distribution from its supplied genome;
  forecasts do not condition on earlier probes or requests.
- The fixed mapping can drift from Observer despite tests; it is not shared
  runtime state.
- A content hash does not authenticate execution or establish provenance.
- The process has no arbitrary candidate runtime, training, calibration check,
  causal model, network access, mutation, selection, persistence, or stopping
  rule.

## Primary sources

- C. E. Shannon, “A Mathematical Theory of Communication,” 1948, supplies the
  finite-discrete entropy foundation:
  [part I](https://doi.org/10.1002/j.1538-7305.1948.tb01338.x) and
  [part II](https://doi.org/10.1002/j.1538-7305.1948.tb00917.x).
- T. Gneiting and A. E. Raftery, “Strictly Proper Scoring Rules, Prediction,
  and Estimation,” 2007, gives the proper-scoring interpretation of logarithmic
  loss: [JASA](https://www.tandfonline.com/doi/abs/10.1198/016214506000001437).
- A. P. Dawid, “Statistical Theory: The Prequential Approach,” 1984, motivates
  forecast-then-observe evaluation:
  [JRSS A](https://rss.onlinelibrary.wiley.com/doi/10.2307/2981683).
- NIST, *Secure Hash Standard (SHS), FIPS 180-4*, specifies SHA-256:
  [FIPS 180-4](https://csrc.nist.gov/pubs/fips/180-4/upd1/final).
