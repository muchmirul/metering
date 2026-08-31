# Current capability map

This page is the short operational guide for users and coding agents. It
describes implemented behavior on `main`; it is not a roadmap. [`PLAN.md`](../PLAN.md)
remains normative when this summary and another document disagree.

## Installed package

| Capability | Status | Boundary |
|---|---|---|
| Self-information | Implemented | One caller-supplied probability |
| Shannon entropy | Implemented | One finite discrete distribution |
| KL divergence | Implemented | Two aligned finite distributions |
| Mutual information | Implemented | One finite rectangular joint distribution |
| Strict JSON command | Implemented | One request on stdin, one canonical result on stdout |
| Git measurement history | Implemented, opt-in | Separate `metering-history` command |
| Probability estimation or normalization | Not implemented | Caller responsibility |
| Generic information, fitness, or intelligence score | Not implemented | Deliberately absent |

The public Python API remains exactly:

```python
from metering import (
    ProbabilityError,
    entropy,
    kl_divergence,
    mutual_information,
    self_information,
)
```

The functions and ordinary `metering` command have no filesystem or network
effects and no runtime dependencies. `metering-history` is separate and requires
Git.

## Git-backed measurement history

Record one accepted configuration and exact named result:

```bash
history="$(mktemp -d)"
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | metering-history record "$history"
metering-history verify "$history"
```

The dedicated repository tracks only:

```text
measurement/pair/configuration.json
measurement/pair/result.json
measurement/provenance.json
```

Git supplies blob, tree, commit, parent, diff, checkout, and optional remote
mechanics. Metering does not copy its source code into the history. `verify`
runs `git fsck`, rejects dirty or malformed histories, and recomputes every
stored result with the current executable.

This proves committed byte identity and current replay agreement. It does not
prove authorship, protect against an authorized force-push, validate the caller's
probability model, or make a named measurement a universal score. Legacy
schema-version-1 `objects/` histories require the historical implementation.

## Source-only one-generation evolution

The implemented agent-artifact path is:

```text
one parent
    -> one proposed child
    -> matched parent/child execution
    -> independent task and safety evaluation
    -> named forecast measurements
    -> explicit pairwise retention
    -> one selected next parent
```

The optional Evolution Driver repeats this transition with generation,
consecutive-rejection, and wall-clock limits. It follows one selected head and
stores a separate canonical JSONL run ledger. It does not use the measurement
history as candidate lineage.

Implemented candidate forms are:

- default-agent configuration;
- one complete `SKILL.md` artifact; and
- immutable `git-candidate-v1` trees with optional external-output receipts.

A Git candidate may be configuration-only when its fixed external executor
interprets the configured entrypoint. Candidate identity must bind configuration
independently of evaluation evidence. Do not include mutable scores in a
candidate tree and then treat the resulting commit as the same candidate.

## Source-only population search

`apps/variant_search/` adds an optional deterministic population layer above the
one-generation tools. It is not installed in the wheel and does not invoke a
model, runner, evaluator, or deployment command.

| Capability | Status | Boundary |
|---|---|---|
| SQLite candidate registry | Implemented | Canonical candidate identity plus caller-declared manifest |
| One- and two-parent ancestry | Implemented | Zero parents for seeds; at most two distinct registered parents otherwise |
| Environment-bound evidence | Implemented | Exact candidate, fixed run law, environment, metrics, constraints, descriptors, and resources |
| Hard survival filtering | Implemented | Caller names required Boolean constraints |
| Pareto-front calculation | Implemented | Caller declares metric directions |
| Scalar tie policy | Implemented | Caller declares every weight; no repository fitness scalar |
| Reproductive distribution | Implemented | Stable softmax followed by optional replicator update |
| Parent selection | Implemented | Zero, one, or two explicit external draws; no hidden RNG |
| Population entropy | Implemented | Metering Shannon entropy over the active allocation |
| Price-equation accounting primitives | Implemented | Weighted moments and allocation/change decomposition |
| Deterministic Git path recombination | Implemented | Explicit source parent for every conflicting path; two-parent commit |
| Logical-state verification | Implemented | SQLite integrity, foreign keys, content identities, event chain, and pool normalization |

SQLite stores population indexing and evidence; Git continues to store exact
source artifacts. The database file's raw bytes are not identity. `state_id` is
derived from canonical logical state, and `verify` checks that the materialized
tables agree with the hash-linked event ledger.

The population tool can resolve parent identities for an external Pi, Prime
Agent, or other proposer. It does not contain Qwen, llama.cpp, provider SDKs,
prompt policy, benchmark policy, or a universal mapping from evidence to
fitness. The caller owns those experiment choices.

## Still not implemented

Do not claim or infer these capabilities from the current repository:

- learned or self-modifying mutation policy;
- proposal-yield or metaproductivity estimation across descendant lineages;
- automatic novelty descriptors or behavior-bucket definitions;
- evaluator/test coevolution;
- automatic candidate installation, production deployment, or rollback;
- a sandbox supplied by Metering;
- model training or environment-specific benchmark integration;
- full-context agent adoption or ambient agent memory;
- authorship authentication or protection against a fully authorized history or
  database rewrite; or
- a universal fitness, intelligence, usefulness, or meaning score.

The implemented recombiner is deliberately mechanical. A content-valid child
may fail to compile or behave correctly. It must pass through a trusted runner,
evaluator, assay, and selection policy before receiving future reproductive
weight.

## Agent and trust checklist

Before running an application workflow:

1. Read `PLAN.md` and the relevant app protocol.
2. Identify the exact Metering executable/version and current source state.
3. Declare the probability meaning and construction.
4. Keep candidate configuration separate from evaluation results.
5. Pin candidate, task suite, evaluator, runner, budget, connector, and
   population-law identities.
6. Keep protected evaluator material and credentials outside candidate access.
7. Use a reviewed container or VM for untrusted executable candidates.
8. Treat Git hashes as identity/integrity, not authorship or correctness.
9. Treat SQLite as a deterministic index and ledger, not an isolation boundary.
10. Recompute measurements and run `variant_search.py` with `verify` before
    trusting persisted population state.
11. Supply and record parent draws explicitly; do not hide randomness inside the
    population tool.
12. Keep a final evaluation outside reproductive feedback and report task,
    safety, cost, calibration, and generalization evidence separately.

## Documentation order

- [`PLAN.md`](../PLAN.md): normative scope and acceptance behavior.
- [`theory.md`](theory.md): four measurement definitions and numerical rules.
- [`history.md`](history.md): Git history schema and replay verification.
- [`evolution-kernel.md`](evolution-kernel.md): current one-generation artifact
  protocol.
- [`../apps/evolution_driver/README.md`](../apps/evolution_driver/README.md):
  bounded single-head recurrence.
- [`../apps/variant_search/README.md`](../apps/variant_search/README.md):
  deterministic population state, comparison, allocation, and parent selection.
- [`../artifacts/git/README.md`](../artifacts/git/README.md): immutable Git
  candidates, external-output receipts, and deterministic path recombination.
- [`../connectors/README.md`](../connectors/README.md): fixed connector and trust
  boundaries.
