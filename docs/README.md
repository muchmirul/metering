# Metering documentation

[`PLAN.md`](../PLAN.md) is the normative scope and behavior contract. Most
remaining documents explain the implemented boundaries without expanding that
contract. Documents explicitly marked as proposals describe possible future
composition and are not implementation claims.

- [Current capability map](capabilities.md) gives users and coding agents a
  concise implemented/not-implemented boundary and operational checklist.
- [System foundations, design rationale, and hypotheses](foundations.md)
  connects the information theory, Bayesian observation model, proper scoring,
  biology analogy, content identity, software boundaries, and falsifiable
  claims used across the repository.
- [Theory and measurement boundary](theory.md) derives the four public
  information measures and records their numerical conventions.
- [Measurement history](history.md) specifies the opt-in Git-backed
  `metering-history` command, committed schema, replay checks, and limitations.
- [Minimal information-guided evolution kernel](evolution-kernel.md) explains
  how the six repository-local applications execute one generation and how the
  optional source-only driver performs explicit bounded recurrence.
- [Agent-artifact evolution protocol](agent-evolution.md) specifies the additive
  schema version 2 candidate, proposer, runner, evaluator, assay, selection, and
  one-generation boundaries, plus the source-only bounded recurrence driver,
  constructed live-Pi acceptance, additive Git source/model-output artifact
  bridge, and persistence and isolation limits.
- [Deterministic search and evolution design proposal](deterministic-search-evolution.md)
  describes a non-normative population architecture built around immutable Git
  artifacts, a rebuildable SQLite index, named mathematical evidence,
  multi-objective retention, explicit parent allocation, recombination,
  protected evaluation, and resource accounting. It contains no implementation
  claim and does not change `PLAN.md`.
- [Agent connectors](../connectors/README.md) documents the fixed Pi and Prime
  Agent translations, the shared internal Metering skill, and the explicit live
  harness conformance path.
- [Example applications](../apps/README.md) indexes each non-packaged
  application and its local architecture, foundations, and protocol documents.

The installed Python API remains only `ProbabilityError` and the four named
measures. The history command is a separate explicit filesystem boundary, the
applications are source-only examples excluded from the wheel package, and the
design proposal does not alter current runtime behavior.
