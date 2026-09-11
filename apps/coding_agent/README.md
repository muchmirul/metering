# Agentvolve application

**Agentvolve** is the user-facing name for the two-level coding evolution
workflow. `apps/coding_agent/` remains the compatibility-stable implementation
path for Level-1 solution evolution. It receives a caller-owned validated repository
task and a verified sealed Level-2 harness, creates
immutable Git descendants, evaluates them in fresh containers, asks Population
to retain and allocate candidates, runs one protected final assay, and returns a
selected commit and patch. The task profile may use numeric limit-only stopping
or evaluator-verified goal-or-limit stopping; a finite maximum is always
required.

It never modifies the source repository, installs the result, or changes
Metering's installed API. Interactive Pi submits delegated jobs, not a session
mode; historical activation records impose no restrictions on ordinary tools.
`/limit` sets the next `/goal` cap; typed model-facing starts can supply goal, cap,
wall budget, and destination together. Complete validated data queues preparation
without save/start approval dialogs. These paths derive a run profile only from a
validated configured profile and clean Git `HEAD`; user-message plus source-grounded
task generation retains a human-readable fixed-validation record, not model-owned
evaluation authority. Casual sessions need no repository/path setup: when no project
is selected, an explicit fresh-workspace request creates a private Git seed
containing the validated TASK.md and empty output files, then registers the task. It never implements a solution during preparation. Existing
projects are never initialized or committed automatically. Bounded fixed input
inspection reads pinned Git files and explicit local/public-URL documents, never
source instructions. Optional reviewed context binds the brief, source snapshots
and read-only paths into the task and proposer input; old profiles retain their
identities. See [source grounding](../../docs/coding-agent/task-profile.md#source-grounded-preparation).
Fixed preflight
rejects development wall budgets that cannot reserve even one generation. Task
validation records the unchanged reservation calculation and returns the required
`max_wall_seconds` for conversational correction on a new explicit attempt. A stop before an archive exists
reports the Driver reason without attempting protected-final selection; an
available archive still permits final work after budget stopping.

Pi submissions require an explicit compatible verified sealed harness and a
separate reviewed worker configuration/runtime. No implicit Level-2 setup,
newest-harness guess or shared model-service restart occurs. Progress and
verification track only an acknowledged job ID/root; failed newer requests never
inherit old results. Reload/resume does not restart work; history selection does
not rebind ownership. The unchanged legacy worker CLI/replay remain available.
Use a separate reviewed stable controller installation: version/configuration
isolation is not an immutable deployment or sandbox for ordinary host Pi.

## Documentation

Use the dedicated [Agentvolve documentation](../../docs/coding-agent/README.md):

- [component map](../../docs/coding-agent/components.md);
- [simple architecture and execution flow](../../docs/coding-agent/how-it-works.md);
- [six-stage workflow](../../docs/coding-agent/workflow.md);
- [operations and commands](../../docs/coding-agent/operations.md);
- [Trace Viewer: graph, Git files, history, and exports](../../docs/coding-agent/trace-viewer.md);
- [goal-or-limit stopping policies](../../docs/coding-agent/stopping.md);
- [task-profile reference](../../docs/coding-agent/task-profile.md); and
- [architecture and threat model](../../docs/coding-agent/architecture.md).

Level-2 harness implementation details are in the
[harness README](../harness/README.md).

The directory name, `darwinian-coding-*` schemas, and `darwinian_coding` tool
retain their identities. The Pi command surface is `/goal`, `/limit`, `/history`, `/progress`, and
`/agentvolve-stop`; old slash commands and low-level tool actions were removed. Existing task profiles, run receipts, shared engines, and worker CLI
recovery/verification remain compatible; no run migration is required.

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

## Source entry points

`apps/coding_agent/solution_experiment.py` provides `fixture`, `pi`, `status`,
`resume`, `retry`, and `verify` operations. New run roots are required for
`fixture` and `pi`; selected code is never applied automatically.

`python -m apps.coding_agent.agentvolve_worker` provides detached full-workflow
`start`, `resume`, `retry`, `stop`, and `verify` operations, plus `close` for
explicitly ending inactive work as incomplete without altering its evidence.
Read-only `registry` and `control` commands return in-session recovery choices.
`stop` validates worker/effect process identity, uses bounded TERM/KILL escalation,
and records a non-success terminal state while preserving evidence.
The additive `closed.json` orchestration record permanently prevents workflow
continuation, not experimental replay through existing compatibility entrypoints.
Commands emit one bounded response; canonical status and logs live under the
workflow root. Start discloses unmanaged legacy unfinished runs without blocking
on or changing them. Current unfinished workflows still require recovery or closure.
`python -m apps.coding_agent.operator_view` exposes read-only `progress` and
`history` JSON for Pi or another future coding-agent adapter.
`python -m apps.coding_agent.trace_server launch RUNS RUN_NAME` explicitly opens
an optional, finite-lived loopback trace service. Build its pinned frontend once
with `npm ci --prefix apps/coding_agent/trace_ui` and
`npm run build --prefix apps/coding_agent/trace_ui`; Pi opens it with **g** from
progress/history. The terminal browser remains available with **t**. See the
[operations guide](../../docs/coding-agent/operations.md) for exact commands.

## Modules

| Module | Responsibility |
|---|---|
| `agentvolve_worker.py` | detached six-stage workflow jobs, process lock/liveness, and final workflow report |
| `operator_view.py` | read-only progress/history, lineage, bounded candidate diffs, and stage reports |
| `candidate_view.py` | terminal candidate trees, reports, and recorded loop steps |
| `trace_labels.py` | stable depth/branch display aliases without changing candidate identity |
| `trace_view.py` | bounded evidence snapshots, graph/file-history projections, and CSV export |
| `file_view.py` | file inventories, exact blobs, diff pages, and separate rename inference |
| `git_inventory.py`, `inspection_git.py` | bounded Git byte transport and verified commit/tree-to-file mapping |
| `trace_server.py` | explicit capability-scoped, finite-lived loopback service; no worker/evaluator routes |
| `trace_ui/` | separately built TypeScript/Cytoscape.js UI and real-browser tests |
| `process_tracker.py` | projection-only `[n/6]` status |
| `protocol.py` | task and protected-final profile validation |
| `preflight.py` | private operator preparation before Level-1 inference, without executing checks |
| `checks.py` | versioned external stdout comparison; explicit legacy exit-status semantics |
| `task_profile_tool.py` | reviewed session-draft registration, private empty-workspace preparation, and goal/limit profile derivation |
| `task_sources.py` | bounded inert Git/local/public-HTTP input snapshots; no candidate/check execution |
| `task_context.py` | pure source/brief context validation and read-only write-path separation |
| `harness_workspace_editor.py` | verified harness materialization and isolated mutation |
| `candidate_runner.py` | fresh-container solution execution |
| `solution_evaluator.py` | receipt/contract binding and externally derived outcomes |
| `evaluator.py` | independent Level-2 coding-workspace checks |
| `evidence_adapter.py` | Controller evidence to Population coordinates |
| `final_assay.py` | capability-first allocation, protected checks, and seal |
| `experiment_config.py` | fixed commands, budgets, Driver request, and runtime identity |
| `experiment_artifacts.py` | canonical documents, Git import, harness provenance, and explicit final-profile read/copy |
| `experiment_runtime.py` | Level-1 execution, publication, resume/retry, and final sealing |
| `experiment_receipts.py` | read-only execution and retry receipt validation |
| `experiment_replay.py` | phased independent offline verification |
| `solution_experiment.py` | compatibility CLI, public operation exports, and status projection |
| `validate_solution.py` | host-side syntax and content validation |
| `fixtures/` | deterministic CI profiles and proposal transport |

New runs preflight protected structure without exposing it; final allocation
precedes runtime protected copying. Opt-in `stdout-json-v1` checks use v2 evaluation
receipts, while legacy checks retain exit-status semantics and an assurance
warning. New selected v2 patches preserve bytes and must reproduce the selected
Git tree in a disposable index. V1 replay remains available without migration.
The multi-task live acceptance gate requires stdout contracts for development
and protected checks; historical exit-status-only tasks cannot satisfy that gate.
Explicit Pi configuration creates a missing private run registry and validates
mode 0700 without repairing existing directories. Any filesystem enforcing these
permissions is supported; no manual ext4-specific setup is required. `pi-v1`
keeps its raw JSON-event-stream cap. `pi-v2` incrementally validates and discards
transient framing while separately bounding every event and the retained final
action. Connector version is runtime identity, so v2 needs a new compatible
Level-2 seal rather than relabelling or retrying a v1 run.
These are correctness changes, not a claim that arbitrary checks prove a goal.

The entrypoint's public operation/error imports and recorded command paths are
unchanged. Internal modules import the owning implementation instead of the
CLI. See the [maintenance guide](../../docs/coding-agent/maintenance.md) for
boundaries, regression checks, and known accounting limitations.
