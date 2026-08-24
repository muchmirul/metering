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
  how the six repository-local applications execute one generation while an
  external caller retains iteration, policy adaptation, budgets, and stopping.
- [Example applications](../apps/README.md) indexes each non-packaged
  application and its local architecture, foundations, and protocol documents.

The installed Python API remains only `ProbabilityError` and the four named
measures. The history command is a separate explicit filesystem boundary, and
the applications are source-only examples excluded from the wheel package.
