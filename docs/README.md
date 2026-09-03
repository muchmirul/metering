# Metering documentation

[`PLAN.md`](../PLAN.md) is the normative scope and behavior contract. Most
remaining documents explain implemented boundaries without expanding that
contract. Documents with proposed later phases identify those phases separately
from current implementation claims.

- [Current capability map](capabilities.md) gives users and coding agents a
  concise implemented/not-implemented boundary and operational checklist.
- [Six-stage Darwinian coding process](coding-process.md) is the short user
  guide for `[1/6]` through `[6/6]`, status commands, interruption handling, and
  the projection-versus-authority boundary.
- [System foundations, design rationale, and hypotheses](foundations.md)
  connects the information theory, Bayesian observation model, proper scoring,
  biology analogy, content identity, software boundaries, and falsifiable
  claims used across the repository.
- [Theory and measurement boundary](theory.md) derives the four public
  information measures and records their numerical conventions.
- [Measurement history](history.md) specifies the opt-in Git-backed
  `metering-history` command, committed schema, replay checks, and limitations.
- [Source-only control-plane architecture](source-architecture.md) documents
  the package namespaces, narrow shared mechanics, public owner contracts,
  read-only replay/pure planning split, thin sequencers, and dependency tests.
- [Minimal information-guided evolution kernel](evolution-kernel.md) explains
  how the six repository-local applications execute one generation and how the
  optional source-only driver performs explicit bounded recurrence.
- [Agent-artifact evolution protocol](agent-evolution.md) specifies the additive
  schema version 2 candidate, proposer, runner, evaluator, assay, selection, and
  one-generation boundaries, plus the source-only bounded recurrence driver,
  constructed live-Pi acceptance, additive Git source/model-output artifact
  bridge, and persistence and isolation limits.
- [Deterministic search and evolution design](deterministic-search-evolution.md)
  covers the implemented source-only Population Archive and bounded Population
  Driver—canonical records, a rebuildable SQLite index, named evidence, Pareto
  retention, exact parent allocation, typed skill recombination, and bounded
  Git-code mutation/evaluation recurrence plus the typed recursive harness,
  reviewed OCI kernel, receipts, and protected final composition—while separating
  parked adaptive-policy and co-evolution directions.
- [Evolutionary Harness](../apps/harness/README.md) specifies the nine-locus
  candidate, runtime identity, recursive action loop, kernel conformance,
  resource receipts, coding workspace ABI, one-command reference experiment,
  and offline verifier.
- [Darwinian coding agent architecture and threat model](darwinian-coding-agent.md)
  specifies separate Level-1 solution and Level-2 harness evolution,
  archive-in/archive-out Docker workspaces, evidence visibility, immutable Git
  heredity, capability-first final allocation, protected sealing, trust zones,
  residual risks, and bounded improvement claims.
- [Agent connectors](../connectors/README.md) documents the fixed Pi and Prime
  Agent translations, the shared internal Metering skill, and the explicit live
  harness conformance path.
- [Example applications](../apps/README.md) indexes each non-packaged
  application and its local architecture, foundations, and protocol documents.

The installed Python API remains only `ProbabilityError` and the four named
measures. The history command is a separate explicit filesystem boundary, and
all population behavior remains in source-only applications excluded from the
wheel package.
