# Documentation

[`PLAN.md`](../PLAN.md) is the normative implementation contract. These pages
explain the current system without expanding that scope.

## Start here

- [Capabilities](capabilities.md) — what is and is not implemented.
- [Metering theory](theory.md) — the four information measures and numerical
  rules.
- [Measurement history](history.md) — optional Git-backed recording and replay.
- [Agentvolve](coding-agent/README.md) — dedicated user guide.
- [Agentvolve component map](coding-agent/components.md) — Git, Pi, local model,
  llama.cpp, IPython, Docker, control-plane, and evidence responsibilities.
- [How Agentvolve works](coding-agent/how-it-works.md) — simple architecture and
  one-round flow.

## Agentvolve

- [Six-stage workflow](coding-agent/workflow.md)
- [Operations and commands](coding-agent/operations.md)
- [Task-profile reference](coding-agent/task-profile.md)
- [Architecture and threat model](coding-agent/architecture.md)
- [Evolutionary harness implementation](../apps/harness/README.md)
- [Agentvolve implementation](../apps/coding_agent/README.md)

## System design

- [Foundations](foundations.md) — equations, biological analogy, hypotheses, and
  research basis.
- [Source architecture](source-architecture.md) — ownership, dependency, replay,
  and persistence boundaries.
- [Evolution kernel](evolution-kernel.md) — one-generation application
  composition.
- [Agent-artifact protocol](agent-evolution.md) — candidate, proposer, runner,
  evaluator, assay, and selection schemas.
- [Deterministic search and evolution](deterministic-search-evolution.md) —
  Population, exact allocation, recurrence, and protected sealing.

## Source applications and connectors

- [Application index](../apps/README.md)
- [Connector index](../connectors/README.md)
- [Git artifact bridge](../artifacts/git/README.md)

The installed Python package remains limited to `ProbabilityError`, four named
information measures, strict JSON, and opt-in measurement history. Evolution
and coding behavior is source-only and excluded from the wheel.
