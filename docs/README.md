# Metering documentation

[`PLAN.md`](../PLAN.md) is the normative scope and behavior contract for the
`metering` information-measurement package. The remaining documents explain the
implemented boundaries without changing its four-measure API:

- [Evo: the minimal transition kernel](evo.md) documents the separate one-file
  `evo` package: `Candidate`, `Verdict`, `Transition`, and `step`.
- [System foundations, design rationale, and hypotheses](foundations.md)
  connects the information theory, Bayesian observation model, proper scoring,
  biology analogy, content identity, software boundaries, and falsifiable
  claims used across the repository.
- [Theory and measurement boundary](theory.md) derives the four public
  information measures and records their numerical conventions.
- [Measurement history](history.md) specifies the opt-in `metering-history`
  command, on-disk schema, integrity checks, and limitations.
- [Information-guided evolution example](evolution-kernel.md) maps the six
  fixture applications onto the generic proposer-and-judge transition.
- [Example applications](../apps/README.md) indexes each non-packaged
  application and its local architecture, foundations, and protocol documents.

`metering` remains the optional deterministic instrumentation layer. `evo`
contains no measurement assumptions, I/O, persistence, or autonomous loop.
