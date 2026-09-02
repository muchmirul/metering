# Population Driver foundations

## Implemented recurrence

Let $`P_t`$ be the canonical Population state after completed round $`t`$,
$`A_t`$ its fresh development Pareto archive, and $`u_t=p_t/q_t`$ the
caller-supplied exact allocation draw. Population Archive orders the $`n_t`$
member candidate IDs and chooses

$$
i_t=\left\lfloor\frac{p_t n_t}{q_t}\right\rfloor,
\qquad c_t=A_t[i_t].
$$

For the first round, $`c_1`$ is the declared seed. Controller applies one fixed
external mutation operator $`M`$ and evaluates the parent and child on the same
identified development experiment:

$$
c'_t=M(c_t,\theta,t,h_{t-1}),
$$

$$
(o_t,o'_t)=R(c_t,c'_t,e_{dev}),
$$

where $`\theta`$ is the content-identified fixed proposal command/context and
$`h_{t-1}`$ contains only the prior Controller selection aggregate. The proposer
receives neither protected case evidence nor final evidence.

The driver records both observations as unique Population replicates and asks
Population Archive to derive the next state and archive:

$$
P_t=\operatorname{Append}(P_{t-1},c'_t,o_t,o'_t),
$$

$$
A_t=\operatorname{Pareto}_{\pi}(P_t,e_{dev}).
$$

If another round is permitted, the next parent is the exact allocation from
$`A_t`$, not Controller's pairwise selected head. Controller selection remains
recorded evidence about the evaluated pair. Population allocation supplies the
multi-candidate reproductive transition.

## Biological analogy and its limit

The immutable Git tree is the genome, runner/evaluator output is phenotype
evidence under one environment, the fixed Pi/Qwen call is mutation, hard
protected/resource admission is viability, Pareto retention is a bounded
multi-objective archive, and exact allocation is reproduction. Model weights do
not change. This is Darwinian code search by an external mutation operator, not
weight training and not a claim that software is literally an organism.

The analogy does not establish open-ended evolution, general intelligence,
semantic correctness, or improvement outside the identified experiment. New
code can regress. Rejected and infeasible children remain evidence rather than
being relabeled as success.

## Separate coordinates, no generic fitness

For candidate $`c`$ under development experiment $`e`$, Population Archive
retains separately named task, reliability, behavior novelty, forecast-loss,
optional information, and resource coordinates subject to hard survival:

$$
F(c;e)=(S,Q,R,N,L,I,C_1,\ldots,C_k).
$$

No weighted sum turns this vector into a generic fitness, quality, or
intelligence score. Controller's pass-count policy answers only its pairwise
retention question. Population's Pareto policy and uniform allocation answer
different, explicit questions.

## Bounds and failure semantics

For each resource coordinate $`j`$, a new round is admitted only when

$$
C^{used}_j+2B_j\le C^{max}_j,
$$

where $`B_j`$ is the declared per-candidate experiment budget. The factor two
accounts for Controller's matched incumbent and challenger executions. Physical
enforcement remains the runner sandbox's responsibility.

Configured component timeouts are durable reservations. If $`T_C`$ is the
outer Controller timeout and $`T_E`$ the evidence-adapter timeout, an initial
round reserves $`T_C+T_E`$; every explicitly approved Controller retry reserves
another $`T_C`$. A round starts only when the cumulative reservation fits
`max_wall_seconds`. This bound does not pretend that measured wall time is
replayable or that an operating system cannot violate a caller's infrastructure
policy.

A pending intent precedes every Controller attempt. Let $`I_t`$ identify its
complete Controller request and Population starting head. A completed round is
admissible only if immutable receipts and Population records replay from
$`I_t`$. Absence of a valid Controller receipt is indeterminate, so ordinary
resume does not repeat the call. A caller must authorize a new attempt with the
same intent identity and a recorded reason.

## Final-evidence noninterference

Search uses only $`e_{dev}`$. A final experiment $`e_{final}`$ is not a driver
request field, archive source, allocation input, or proposer-feedback source.
Population Archive enforces:

$$
\operatorname{FirstFinalRun}(P)\Rightarrow
\neg\operatorname{SearchTransition}(P).
$$

The driver checks that seal before every new round. Final evidence can therefore
be reported after search but cannot alter later mutation, retention, or parent
allocation in the same population state.

## Falsifiable implementation hypotheses

### H1: allocation controls recurrence

**Claim.** For every completed round after the first, the Controller parent is
exactly the candidate selected by the preceding canonical Population allocation
record.

**Falsifier.** A valid driver state whose next Controller receipt names another
parent.

### H2: completed replay is call-free

**Claim.** Resuming or verifying completed state performs no proposal, candidate
execution, evaluator, or evidence-adapter call and does not require SQLite.

**Falsifier.** Deleting or corrupting `population.sqlite` changes recurrence, or
verified completed resume increments an external adapter-call counter.

### H3: indeterminate model calls require approval

**Claim.** A pending Controller intent without a valid receipt is never repeated
by ordinary `run`.

**Falsifier.** Idempotent resume invokes the proposer before a matching explicit
`retry` request is recorded.

### H4: partial post-Controller work is replay-safe

**Claim.** Once a Controller receipt is durable, evidence adaptation and
Population ingestion can resume without another model call, and a partial
Population suffix must exactly match the expected round prefix.

**Falsifier.** Recovery repeats Controller, silently accepts unrelated Population
records, or creates duplicate candidate/run identities.

### H5: final evidence cannot affect search

**Claim.** The first final Population run prevents every later automatic round.

**Falsifier.** A proposal, development run, archive, or allocation occurs after
the seal, or final report content appears in proposer context.

### H6: supervision is not capability creation

**Claim.** The driver improves provenance, bounded allocation, retention, and
replay compared with an unsupervised mutation loop.

**Falsifier.** It cannot reconstruct candidate/evidence/policy identity or obey
its declared bounds. Higher task capability is a separate empirical hypothesis;
the architecture alone cannot establish it.

## Executable mechanism witness

The deterministic integration test realizes this recurrence over a real Git
lineage for the identified task $`f(l,r)=l+r`$. Its seed computes subtraction,
the first mutation computes addition, and the second mutation computes
multiplication. Matched development evidence retains addition, exact allocation
uses it as the second parent, and the fresh archive excludes both incorrect
programs as dominated. This witnesses H1--H4 for one executable fixture while
making no claim about an external model's mutation distribution or protected
final performance. See
[`tests/test_darwinian_code_evolution.py`](../../../tests/test_darwinian_code_evolution.py).

The implementation's load/verify, plan, effect, and store split is documented in
the [source-only architecture](../../../docs/source-architecture.md). It changes
neither these equations nor the schema-version-1 state identities.

## Security non-claim

Canonical JSON, SHA-256 links, Git object identities, subprocess argument
separation, process-group cleanup, and timeouts detect specific composition
errors. They do not isolate a malicious model or executable candidate. A real
run requires caller-provided container/VM confinement and immutable execution
receipts. A writer able to consistently replace all local ledgers and receipts
can replace local history; external witnessing is outside this application.
