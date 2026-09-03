# Agentvolve application

**Agentvolve** is the user-facing name for the two-level coding evolution
workflow. `apps/coding_agent/` remains the compatibility-stable implementation
path for Level-1 solution evolution. It receives an operator-approved repository
task and a verified sealed Level-2 harness, creates
immutable Git descendants, evaluates them in fresh containers, asks Population
to retain and allocate candidates, runs one protected final assay, and returns a
selected commit and patch. The task profile may use numeric limit-only stopping
or evaluator-verified goal-or-limit stopping; a finite maximum is always
required.

It never modifies the source repository, installs the result, or changes
Metering's installed API.

## Documentation

Use the dedicated [Agentvolve documentation](../../docs/coding-agent/README.md):

- [component map](../../docs/coding-agent/components.md);
- [simple architecture and execution flow](../../docs/coding-agent/how-it-works.md);
- [six-stage workflow](../../docs/coding-agent/workflow.md);
- [operations and commands](../../docs/coding-agent/operations.md);
- [task-profile reference](../../docs/coding-agent/task-profile.md); and
- [architecture and threat model](../../docs/coding-agent/architecture.md).

Level-2 harness implementation details are in the
[harness README](../harness/README.md).

The existing directory name, `darwinian-coding-*` schemas, `darwinian_coding`
tool, and `/evolve-*` commands are retained so existing task profiles, run
receipts, imports, and operator workflows do not break.

## Boundary

```text
verified selected-harness.json + canonical task profile
                         ↓
immutable solution commits + fresh independent checks
                         ↓
Population allocation + protected final seal
                         ↓
selected-solution.json + selected.patch
```

Harness/runtime policy, evaluator commands, task permissions, Population policy,
and Docker security do not mutate with solution code. Sessions, transcripts,
kernel state, and unexported files are not inherited.

## Source entry point

`apps/coding_agent/solution_experiment.py` provides `fixture`, `pi`, `status`,
`resume`, `retry`, and `verify` operations. New run roots are required for
`fixture` and `pi`; selected code is never applied automatically. See the
[operations guide](../../docs/coding-agent/operations.md) for exact commands.

## Modules

| Module | Responsibility |
|---|---|
| `process_tracker.py` | projection-only `[n/6]` status |
| `protocol.py` | task and protected-final profile validation |
| `harness_workspace_editor.py` | verified harness materialization and isolated mutation |
| `candidate_runner.py` | fresh-container solution execution |
| `solution_evaluator.py` | execution-receipt validation |
| `evaluator.py` | independent Level-2 coding-workspace checks |
| `evidence_adapter.py` | Controller evidence to Population coordinates |
| `final_assay.py` | capability-first allocation, protected checks, and seal |
| `solution_experiment.py` | Level-1 sequencing, resume/retry, and offline verification |
| `validate_solution.py` | host-side syntax and content validation |
| `fixtures/` | deterministic CI profiles and proposal transport |
