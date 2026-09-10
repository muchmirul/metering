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
  byte/time limits. `pi-v1` keeps the complete-stream behavior. `pi-v2` uses the
  helper's trusted line filter to validate all JSONL records and retain only the
  authoritative assistant event, with per-record and retained-output caps. It adds
  no search policy or accounting authority.

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

`workflow_configure` records directly reviewed existing paths for this session,
without environment mutation, a second interactive Pi, or process restart. `/goal`
offers configuration when defaults are absent. Restoration never launches and
malformed/latest version-1 records fail closed; changes affect future jobs only.
Version-2 records bind an owner-controlled 0700 run registry as well as worker
runtime/harness/configuration. Configured review and start refuse permission-
incapable filesystems before creating a workflow; never remove the privacy check. The normal
route uses bounded read-only discovery and labelled choices before full seal
verification, not mandatory path typing. Missing setup yields actionable preparation
instructions; advanced inputs support correction/cancellation. No implicit
credential copying, newest-run selection or service/model loading is allowed.
`connectors.fixed.pi.runtime review-configured` is a read-only execution-approval boundary:
exact runtime/Pi/configuration identities, explicit compatible verified reused
harness and finite budgets. New Pi jobs neither guess a seal nor implicitly fund
Level 2 or restart a model service. Configured CLI dispatch rechecks the strict
approved document before creating a v2 workflow request with command/version/runtime
and models hash binding. Only explicitly selected bounded models/auth files are
copied privately for the job; models remain hash-bound, auth can refresh. Recovery
uses the job-owned binding; offline replay needs neither credentials nor a live Pi.
Controller/runtime/harness paths remain operator-managed; use a stable separate
reviewed installation. This limited copy is not a controller snapshot or host
sandbox. Legacy v1 jobs, experiment/evidence/replay and the installed package remain unchanged.

Deployed deterministic job tests replace mode tests and exercise actual ordinary
Pi tools, fresh caps, cancellation/failure/uncertain acknowledgement, restoration,
identity-specific views/verification, and initial/steady-state monitor races using
test-owned boundary doubles. `tests/test_agentvolve_session_configuration.py`
covers same-process configuration/delegation, unchanged interactive environment,
future-only selection, private registry routing, corruption and session races. The worker configuration tests
cover private bounded copies, command/models binding, recovery with conflicting
ambient settings, and offline verification without credentials or a live Pi.
They do not prove live inference acceptance.

## Regression checks

```bash
uv run --extra test pytest -q tests/test_agentvolve_jobs.py tests/test_agentvolve_pi_extension.py tests/test_pi_runtime_resolution.py
uv run --extra test pytest -q tests/test_architecture.py tests/test_experiment_boundaries.py
uv run --extra test pytest -q tests/test_coding_agent.py tests/test_harness_evolution.py
uv run --extra test pytest -q tests/test_agentvolve_hardening.py tests/test_coding_output_checks.py tests/test_bounded_model_transport.py
uv run --extra lint ruff check src apps connectors artifacts tests
uv run --extra test pytest -q
```

The Ruff command must match CI's full scope, not just edited files. The previously
reported green pytest suite did not catch five E701 violations in the deployed-job
tests; those stopped CI before any test/build step. Both gates are mandatory.

After deterministic checks, run the [separately approved live gate](operations.md#standard-local-model-end-to-end-acceptance)
with `METERING_REQUIRE_AGENTVOLVE_E2E=1`. Missing approval/configuration/model/image/
profiles or a registry blocker must fail the gate, not silently skip it. Preflight
all profiles before the first dispatch and preserve any failed run at its original
paths. Hosted model-free CI is not live-model acceptance. A readiness check is not
inference success or a guarantee that a shared model remains loaded.

`tests/test_agentvolve_ui.py` deploy-loads Pi to check silent startup/reload,
restored failures, preparation cancellation, active-job display, terminal clearing,
error-notification deduplication and session-switch cleanup. Use only the owned
status/widget keys when clearing UI; never delete session evidence or suppress
ordinary tools. Idle UI must not become an activation flag or worker stop action.

Source-grounding regressions also cover directory references: metadata filtering
must remove them from the drafter's local-file allowlist before inference. Do not
fix a directory-read failure by recursively reading it, weakening the bounded
regular-file reader, retrying model output automatically or fabricating sources.

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
