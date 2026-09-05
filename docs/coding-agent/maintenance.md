# Agentvolve maintenance boundaries

Agentvolve is a source-only application, not part of the installed four-measure
API. Maintain its experiment composition separately from the measurement
package. This is a code-organization boundary, not a new package, registry, or
plugin framework.

## Experiment ownership

Both `apps/harness/` and `apps/coding_agent/` separate:

- `experiment_config.py`: fixed commands, existing budgets, and Driver requests;
- `experiment_runtime.py`: initialization, execution, publication, and retries;
- `experiment_receipts.py`: independent receipt validation; and
- `experiment_replay.py`: read-only verification phases.

The coding application also has `experiment_artifacts.py` for canonical
documents, immutable Git import, harness provenance, and explicit final-profile
copy/read operations. The original `experiment.py` / `solution_experiment.py`
entrypoints retain command dispatch, status projection, and public operation
and exception imports. Private helpers and test-patching seams belong to their
implementation modules, not the CLI.

The dependency direction is explicit:

```text
compatibility CLI -> runtime -> replay
                       |          |
                       +-> configuration, artifact and receipt owners
```

Internal owners do not import the CLI. Replay cannot launch a model, run an
assay, publish a result, or update status. It may make temporary Git checkouts
outside a run. Reading a run's protected-final profile cannot silently copy or
reveal the operator's original profile; the runtime owns that separate effect.

Keep independent replay calculations independent of their writers. Sharing a
writer's implementation is not a substitute for checking its recorded result.

## Cost-accounting ownership and remaining concern

The current Level-1 accounting has two distinct evidence streams:

| Evidence | Current owner/use |
|---|---|
| Mutation model calls, tokens, and resource cost | `harness_workspace_editor.py` writes mutation receipts; the mutation replay phase checks their binding |
| Candidate execution resource cost | `candidate_runner.py` writes evaluation receipts; `evidence_adapter.py` supplies Population coordinates; development/final replay reconciles those costs |
| Candidate-cost budget and timeout reservations | Population Driver, using the existing request from `experiment_config.py` |

**Population's candidate-cost total is not total search cost.** Mutation inference
is recorded separately and is not added to that total. Orchestration and
indeterminate failed inference also cannot be assumed free. The decomposition
does not fix this accounting limitation or introduce new budget enforcement.

A follow-up behavior change needs an explicit versioned accounting contract:
keep candidate execution cost separate from search expenditure, count retries
without double charging on resume, distinguish observed costs from unknown or
reserved costs, and preserve old run replay. Do not insert mutation cost into a
candidate's Pareto coordinates as a shortcut: that changes selection as well as
accounting.

## Other follow-up concerns

These are not addressed by the internal refactor:

- model-weight and sampling identity beyond the existing runtime labels;
- portable verification without the original absolute run/provenance paths;
- streaming output enforcement instead of post-buffer checks;
- archive size limits and preinstalled runtime dependencies;
- license selection by the copyright owner; and
- the separately reviewed evaluator false-positive, archive champion retention,
  generated draw, and CRLF patch defects.

Each behavior/security fix needs its own reproduction, acceptance test, and
compatibility decision. Do not bundle it invisibly into code movement.

## Regression checks

```bash
uv run --extra test pytest -q tests/test_architecture.py tests/test_experiment_boundaries.py
uv run --extra test pytest -q tests/test_coding_agent.py tests/test_harness_evolution.py
uv run --extra lint ruff check .
uv run --extra test pytest -q
```

Architecture tests guard the entrypoint and replay dependency direction.
Boundary tests exercise CLI compatibility and explicit final-profile loading.
The end-to-end fixture test blocks runtime/publication effects during offline
verification and compares all run-file hashes before and after verification.
Existing tests still exercise immutable ancestry, allowed paths, final sealing,
tampering, and reserved retries. A passing fixture is not live sandbox or model
acceptance; use the separately configured three-task acceptance in the
[operations guide](operations.md) for workflow behavior changes.

Command paths, public measurement APIs, numerical behavior, record identities,
protocol versions, selection policy, budgets, retry rules, and package
boundaries are unchanged by this decomposition. Existing runs require no
migration for it.
