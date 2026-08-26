# Metering documentation

[`PLAN.md`](../PLAN.md) is the normative scope and behavior contract. The
remaining documents explain the implemented boundaries without expanding that
contract:

- [System foundations, design rationale, and hypotheses](foundations.md)
  connects the information theory, Bayesian observation model, proper scoring,
  biology analogy, content identity, software boundaries, and falsifiable
  claims used across the repository.
- [Theory and measurement boundary](theory.md) derives the four public
  information measures and records their numerical conventions.
- [Measurement history](history.md) specifies the opt-in `metering-history`
  command, on-disk schema, integrity checks, and limitations.
- [Minimal information-guided evolution kernel](evolution-kernel.md) explains
  how the six repository-local applications execute one generation and how the
  optional source-only driver performs explicit bounded recurrence.
- [Agent-artifact evolution protocol](agent-evolution.md) specifies the additive
  schema version 2 candidate, proposer, runner, evaluator, assay, selection, and
  one-generation boundaries, plus the source-only bounded Pi recurrence driver,
  constructed live-Pi acceptance, additive Git source/model-output artifact
  bridge, and persistence and isolation limits.
- [Example applications](../apps/README.md) indexes each non-packaged
  application and its local architecture, foundations, and protocol documents.

The installed Python API remains only `ProbabilityError` and the four named
measures. The history command is a separate explicit filesystem boundary, and
the applications are source-only examples excluded from the wheel package.
