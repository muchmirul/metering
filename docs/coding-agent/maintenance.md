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

## Correctness and reliability owners

The subsequent behavior fixes are separate from the earlier mechanical refactor:

- `preflight.py` privately validates operator profiles before new Level-1 runs;
  it returns no protected contents and never executes a candidate.
- `checks.py` defines the pure, versioned stdout contract. Writers record raw
  execution, not pass decisions; evaluator and replay each derive outcomes from
  those bytes and the bound operator expectation. Legacy argv checks stay weaker.
- Runtime start/resume share `_run_protected_final()`, whose first effect is the
  durable development-only allocation; only then may protected bytes be copied.
- `artifacts/git/git_patch.py` generates raw-byte patches and verifies selected
  trees using a disposable clone/index. Replay checks v2 bytes and applied trees;
  v1 retains its old text-transport compatibility path.
- `apps/population_driver/diagnostics.py` records non-authoritative Controller
  failure diagnostics; `apps/_support/diagnostics.py` bounds/redacts excerpts.
- `apps/_support/bounded_process.py` drains model-client pipes under their existing
  byte/time limits. It adds no search policy or accounting authority.

New contract/patch versions do not change installed APIs, numerical behavior,
selection, stopping, or search-budget rules. Profile authoring and new Level-1
execution now fail earlier on malformed protected inputs; valid historical runs
need no migration. See [task profiles](task-profile.md) for assurance limitations.

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

These remain follow-up work, not guarantees of the refactor or first hardening increment:

- model-weight and sampling identity beyond the existing runtime labels;
- portable verification without the original absolute run/provenance paths;
- streaming limits for general application/kernel transports beyond model clients;
- archive size limits and preinstalled runtime dependencies;
- license selection by the copyright owner; and
- legacy exit-status-only evaluator false positives and broader check quality; and
- archive champion retention and generated-draw policies (policy changes remain parked).

Each behavior/security fix needs its own reproduction, acceptance test, and
compatibility decision. Do not bundle it invisibly into code movement.

## Delegated-job maintenance

The session-toggle architecture is replaced by session-owned submission records
in `population_evolution_extension.ts`. They are orchestration diagnostics, not
new experiment evidence. Only validated launch acknowledgement binds job ID/root;
monitor/progress/verification never discover the latest run. Failed newer requests
cannot inherit older results. Restoration never dispatches; forks inherit no
ownership. Old activation records/messages impose no ordinary-tool restrictions.

`connectors.fixed.pi.runtime review` is a read-only execution-approval boundary:
exact runtime/Pi/configuration identities, explicit compatible verified reused
harness and finite budgets. New Pi jobs neither guess a seal nor implicitly fund
Level 2 or restart a model service. Controller/config paths remain operator-managed;
use a stable separate reviewed installation. Pi pinning is not an immutable
controller snapshot or host sandbox. Historical worker/evidence/replay contracts
and the installed package remain unchanged.

Deployed deterministic job tests replace mode tests and exercise actual ordinary
Pi tools, fresh caps, cancellation/failure/uncertain acknowledgement, restoration,
identity-specific views/verification, and initial/steady-state monitor races using
test-owned boundary doubles. They do not prove live inference acceptance.

## Regression checks

```bash
uv run --extra test pytest -q tests/test_agentvolve_jobs.py tests/test_agentvolve_pi_extension.py tests/test_pi_runtime_resolution.py
uv run --extra test pytest -q tests/test_architecture.py tests/test_experiment_boundaries.py
uv run --extra test pytest -q tests/test_coding_agent.py tests/test_harness_evolution.py
uv run --extra test pytest -q tests/test_agentvolve_hardening.py tests/test_coding_output_checks.py tests/test_bounded_model_transport.py
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

The original decomposition preserved command paths, public measurement APIs,
numerical behavior, record identities, protocol versions, selection policy,
budgets, retry rules, and package boundaries. The later hardening explicitly adds
an operator preflight command, versioned output checks/receipts and patches, and
bounded diagnostics/transport behavior as described above; it is not merely code
movement.
