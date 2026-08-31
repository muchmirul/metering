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

## Source-only evolution applications

The currently implemented agent-artifact path is:

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

The separate source-only Population Archive can record multiple normalized
candidates, identified experiments and replicates, named development evidence,
a bounded Pareto archive, and exact uniform parent allocations. Its SQLite index
is derived from a canonical hash-linked ledger and is never selection authority.
Typed recombination is implemented only for complete `agent-skill-v1` file loci.
The first final run seals every later search transition. The application does
not execute the allocated parent or automatically connect it to another
generation.

Implemented candidate forms are:

- default-agent configuration;
- one complete `SKILL.md` artifact; and
- immutable `git-candidate-v1` trees with optional external-output receipts.

A Git candidate may be configuration-only when its fixed external executor
interprets the configured entrypoint. Candidate identity must bind configuration
independently of evaluation evidence. Do not include mutable scores in a
candidate tree and then treat the resulting commit as the same candidate.

## Not implemented

Do not claim or infer these capabilities from the current repository:

- autonomous population execution or recursive agent trees;
- weighted reproductive scores or learned parent-allocation policy;
- behavior-bucket retention beyond the implemented Pareto archive;
- Price-equation attribution or proposal-yield evaluation;
- arbitrary Git recombination or evaluator/test coevolution;
- automatic candidate installation, deployment, or rollback;
- a sandbox supplied by Metering;
- model training or environment-specific benchmark integration;
- full-context agent adoption or ambient agent memory.

Only the Population Archive mechanisms documented above are current runtime
behavior. Adaptive mutation, co-evolution, and automatic population execution
remain proposals unless `PLAN.md`, tests, and implementation are updated
together.

## Agent and trust checklist

Before running an application workflow:

1. Read `PLAN.md` and the relevant app protocol.
2. Identify the exact Metering executable/version and current source state.
3. Declare the probability meaning and construction.
4. Keep candidate configuration separate from evaluation results.
5. Pin candidate, task suite, evaluator, runner, budget, and connector identities.
6. Keep protected evaluator material and credentials outside candidate access.
7. Use a reviewed container or VM for untrusted executable candidates.
8. Treat Git hashes as identity/integrity, not authorship or correctness.
9. Recompute measurements; never trust a committed result merely because Git
   accepts it.
10. Report task, safety, cost, and forecast measurements separately.

## Documentation order

- [`PLAN.md`](../PLAN.md): normative scope and acceptance behavior.
- [`theory.md`](theory.md): four measurement definitions and numerical rules.
- [`history.md`](history.md): Git history schema and replay verification.
- [`agent-evolution.md`](agent-evolution.md): current one-generation artifact
  protocol.
- [`../apps/evolution_driver/README.md`](../apps/evolution_driver/README.md):
  bounded single-head recurrence.
- [`../artifacts/git/README.md`](../artifacts/git/README.md): immutable Git
  candidates and external-output receipts.
- [`../connectors/README.md`](../connectors/README.md): fixed connector and trust
  boundaries.
