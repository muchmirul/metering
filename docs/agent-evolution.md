# Agent-artifact evolution protocol

## Scope

Application schema version 2 executes one bounded comparison between an
incumbent agent configuration and one proposed skill or Git-backed artifact. It is an
additive, source-only application protocol. The installed `metering` package and
its JSON command are unchanged.

The reusable transition is:

```text
parent candidate + direct or proposer-produced challenger
    -> bind immutable skill or Git-backed artifacts
    -> run both through the same agent adapter on the same task cases
    -> reveal task results through a trusted evaluator adapter
    -> measure each committed outcome forecast
    -> compare explicit task pass and safety evidence
    -> return one selected next parent
```

The controller performs one generation. It does not repeat generations,
install the selected skill, or claim improvement outside the declared cases.
The optional Evolution Driver repeats this same transition along one selected
head under persistent generation and rejection limits plus a per-invocation
wall-clock limit. The separate bounded
[Population Driver](../apps/population_driver/README.md) uses Population
Archive's exact allocations as successive Git parents, records both Controller
reports as development replicates, and refreshes the Pareto archive. Neither
changes Controller semantics.

## Behavior-preserving decomposition

Schema version 2 was added without turning the public entry points into mixed
implementations:

- `apps/controller/controller.py` retains schema-version-1 fixture orchestration
  and dispatches schema-version-2 work to `agent_generation.py`;
- `component_runtime.py` owns Controller subprocess and component-response
  mechanics without owning application policy;
- `apps/observer/observer.py` remains the independently copyable fixture
  program, while `agent_evaluator.py` owns schema-version-2 external evaluation;
- Mutator keeps schema-version-1 genome mutation in its entrypoint and owns
  schema-version-2 direct/proposer artifact mutation in `agent_mutation.py`;
- Selection Gate keeps schema-version-1 forecast retention in its entrypoint and
  owns schema-version-2 task-evidence retention in `task_selection.py`, with
  shared report-number validation in `report_validation.py`.

These are internal ownership changes, not new public commands. Recorded
schema-version-1 fixture outputs and direct-challenger schema-version-2 outputs
remain byte-identical. The split centralizes transport mechanics while leaving
mutation, evaluation, measurement, and retention policy in their owning
applications.

## Candidate artifacts

Version 2 supports three candidate artifact schemas. Existing default and skill
forms are unchanged; the Git form is an additive external-output boundary.

A default agent with no candidate skill is:

```json
{"artifact_schema":"agent-default-v1"}
```

“Default” means the same pinned runner adapter, model, tools, context, and budget
without an explicit candidate skill. It does not mean whatever mutable global
configuration happens to be installed on a machine.

An Agent Skills directory is represented as canonical UTF-8 files:

```json
{
  "artifact_schema":"agent-skill-v1",
  "files":[
    {
      "content":"---\nname: example\ndescription: Example skill.\n---\n",
      "executable":false,
      "path":"SKILL.md"
    }
  ]
}
```

Paths are normalized relative POSIX paths. Absolute paths, `.` and `..`
components, backslashes, duplicate paths, missing or empty `SKILL.md`,
non-string content, and strings that cannot encode as UTF-8 are rejected.
Executable mode is represented explicitly.
Binary assets, symlinks, ownership, timestamps, and other filesystem metadata
are not represented in version 1.

An immutable Git-backed source/output candidate is:

```json
{
  "artifact_schema":"git-candidate-v1",
  "commit":"GIT_OBJECT_ID",
  "content_sha256":"PORTABLE_TREE_CONTENT_SHA256",
  "entrypoint":"adapter.py",
  "git_tree":"GIT_TREE_ID",
  "outputs":[
    {"kind":"model_checkpoint","name":"candidate","sha256":"SHA256","uri":"artifact://checkpoint"}
  ],
  "repository":"CALLER_APPROVED_REPOSITORY"
}
```

The repository-local bridge under [`artifacts/git/`](../artifacts/git/README.md)
verifies the commit, tree, regular-file modes, portable content hash, and
entrypoint. External outputs such as model checkpoints are represented by URI
and SHA-256 rather than embedded in JSON or ordinary Git. Branch names are not
part of identity. Candidate Runner sends this artifact to Git adapter protocol
version 2; default and skill adapters continue to receive protocol version 1.

The candidate ID for every artifact form is:

```text
SHA-256(canonical JSON of {
    "artifact": normalized artifact,
    "candidate_schema": "agent-candidate-v1"
})
```

Mutator schema version 2 has two strict request forms. The original form accepts
one parent artifact, one already-proposed challenger artifact, and explicit
proposal provenance. The proposal form accepts `parent_artifact`,
`proposal_context`, and exactly one proposer command with an integer timeout.
It sends the proposer only:

```json
{
  "context":{},
  "parent":{"artifact":{},"candidate_id":"HEX_SHA256"},
  "protocol_version":1
}
```

The proposer must return exactly:

```json
{
  "challenger_artifact":{
    "artifact_schema":"agent-skill-v1",
    "files":[
      {"content":"COMPLETE SKILL.md","executable":false,"path":"SKILL.md"}
    ]
  },
  "reason":"bounded reason"
}
```

For proposer-generated changes, parent and challenger may be a default artifact,
exactly one `SKILL.md`, or a normalized `git-candidate-v1`; the challenger may
not be default and must differ. Mutator records the proposer command digest as
provenance. It does not pass tasks, evaluator commands, submissions, or
protected evidence. Fixed Pi and Prime Agent skill proposers remain skill-only;
their Git-workspace proposers emit Git artifacts through the same Mutator
command boundary.

Concrete fixed skill proposers for Pi and Prime Agent live under
[`connectors/fixed/`](../connectors/fixed/README.md). Each disables tools,
context files, discovered resources, and sessions, then registers and injects
the verified current `SKILL.md`. Pin the complete harness command, including
model and provider, through its documented JSON command environment. A proposer
returns a full replacement, never a patch, and does not decide retention. The
former Pi path under `apps/mutator/` is a compatibility launcher.

## Agent adapter

Candidate Runner schema version 2 materializes a skill in a temporary directory
and calls one caller-selected command. Commands are JSON string arrays and are
executed directly without a shell.

Adapter request:

```json
{
  "candidate":{
    "candidate_id":"HEX_SHA256",
    "skill_path":"/temporary/path/or-null"
  },
  "protocol_version":1,
  "task":{"case_id":"case-1","input":{}}
}
```

`skill_path` is `null` for the default-agent artifact. The fixed Pi and Prime
Agent connectors omit `--skill` for that candidate and use
`--no-skills --skill PATH/SKILL.md` for a skill candidate. Another runner may
implement the same JSON boundary through a reviewed concrete public command.
Agent SDKs do not belong in Metering.

For `git-candidate-v1`, Candidate Runner uses adapter protocol version 2 and
passes the descriptor without resolving or executing it:

```json
{
  "candidate":{"artifact":{"artifact_schema":"git-candidate-v1"},"candidate_id":"HEX_SHA256"},
  "protocol_version":2,
  "task":{"case_id":"case-1","input":{}}
}
```

The checked-in Git resolver verifies one caller-allowed repository, immutable
commit/tree/content identities, regular-file constraints, and entrypoint before
delegating to a fixed executor. The executor owns sandboxing and external-output
digest verification. Its command and environment must be pinned by the caller;
the general application kernel does not authenticate remote stores or runtime
configuration.

For `evolutionary-harness-v1`, the repository now supplies that executor at
[`apps/harness/harness_runner.py`](../apps/harness/harness_runner.py). It verifies
a complete nine-locus manifest and canonical runtime identity, obtains strict
model actions through tool-free Pi or Prime Agent translations, executes
candidate bootstrap/cells only in a reviewed no-network OCI kernel, and emits a
content-addressed receipt. This is one concrete candidate form, not implicit
sandboxing for arbitrary Git entrypoints. See the
[typed harness contract](../apps/harness/README.md).

The adapter must emit exactly:

```json
{
  "forecast":{
    "outcomes":[
      {"outcome":"fail","probability":0.25},
      {"outcome":"pass","probability":0.75}
    ]
  },
  "submission":{}
}
```

The complete finite outcome forecast is committed before the evaluator runs.
Candidate Runner validates normalization through Metering and reports its
entropy. Adapter decimal tokens are rejected if double-precision conversion
would produce infinity, collapse nonzero to zero, or round a value distinct
from one to one. `submission` is caller-owned JSON passed to the evaluator.

For text-only Pi evaluations, use:

```json
{
  "command":[
    "uv","run","python",
    "connectors/fixed/pi/text_runner.py"
  ],
  "timeout_seconds":300
}
```

Its task input is exactly `{"prompt":"...","outcomes":["fail","pass"]}`. The
connector disables tools, context files, discovered resources, and session
persistence. Pi normally uses `read` for progressive skill disclosure, so this
tool-free connector registers the candidate skill and injects the complete,
verified materialized `SKILL.md` into Pi's system prompt. Referenced scripts and
assets are not exposed. Pin the complete Pi command through
`METERING_PI_COMMAND`. Prime Agent's fixed text runner accepts the same request
under `connectors/fixed/prime_agent/`. Neither can evaluate tool-using coding
tasks; those need a separately reviewed connector with isolated workspaces and
explicit tool and budget controls.

## Evaluator adapter

Observer `--evaluate` invokes a trusted evaluator only after both candidate
runs finish. The evaluator command owns hidden targets, verifiers, and the
meaning of task success.

Adapter request:

```json
{
  "case":{"case_id":"case-1","input":{}},
  "evaluation":"suite/holdout-v1",
  "protocol_version":1,
  "submissions":[
    {"candidate_id":"PARENT_SHA256","submission":{}},
    {"candidate_id":"CHALLENGER_SHA256","submission":{}}
  ]
}
```

It must return exactly one result for each candidate:

```json
{
  "results":[
    {
      "candidate_id":"PARENT_SHA256",
      "evidence":{},
      "outcome":"pass",
      "passed":true,
      "safety_passed":true
    },
    {
      "candidate_id":"CHALLENGER_SHA256",
      "evidence":{},
      "outcome":"fail",
      "passed":false,
      "safety_passed":true
    }
  ]
}
```

The evaluator, not Metering, defines `passed`, `safety_passed`, and evidence.
The reported outcome must appear in that candidate's committed forecast.

## Assay and selection

Forecast Assay schema version 2 reports separately:

- task case count;
- passed case count;
- safety failure count;
- each observed outcome and trusted evaluator evidence; and
- target self-information and mean target surprisal for the committed
  forecasts.

It reruns Metering over each outcome distribution and rejects a reported
forecast entropy that does not match those probabilities. Selection Gate
recomputes report summaries and target surprisal rather than trusting aggregate
fields.

Selection Gate schema version 2 verifies both reports and supports the explicit
`task-pass-count-v1` policy:

```json
{
  "type":"task-pass-count-v1",
  "minimum_pass_improvement":1,
  "reject_safety_regression":true
}
```

When enabled, any increase in safety failures rejects the challenger. Otherwise
the challenger must meet the declared integer pass-count improvement. Forecast
surprisal is retained as calibration evidence and is not used as a substitute
for task capability.

## Complete example

From the repository root:

```bash
uv run python apps/controller/controller.py \
  < apps/controller/agent-skill-example-request.json
```

The commands in this example request are deterministic test doubles. They prove
protocol composition only; they do not run a model or establish empirical agent
improvement. Replace its runner with a fixed Pi or Prime Agent connector, or a
separately reviewed external command, and replace the evaluator for a real
evaluation.

## Agent-internal Metering tool

The shared [`connectors/tools/metering`](../connectors/tools/metering/README.md)
skill lets either harness invoke Metering through its native tool surface while
preserving the public JSON boundary. The explicit live acceptance launches real
Pi and Prime Agent commands, verifies a `bash` or `ipython` tool event, and checks
the exact Metering receipt:

```bash
uv run python connectors/live_agent_acceptance.py --model llamacpp/local
```

This proves one internal-tool call for the selected model and installed harness
versions. It does not prove proposal quality, candidate promotion, or general
provider neutrality.

## Bounded recurrence

`apps/evolution_driver/evolver.py` wraps Controller without merging any of the
six stages. Its strict schema-version-1 request supplies an initial parent,
proposer command and approved context, the fixed generation configuration, and
positive integer generation, consecutive-rejection, and wall-clock limits.
Run the deterministic example with:

```bash
rm -f /tmp/metering-self-evolve.jsonl /tmp/metering-self-evolve.jsonl.lock
uv run python apps/evolution_driver/evolver.py \
  --state /tmp/metering-self-evolve.jsonl \
  < apps/evolution_driver/example-request.json
```

The state file starts with one request-bound run header and appends one complete
Controller request/result record only after successful validation. Records are
canonical, SHA-256 identified, and parent-linked. Resume verifies the chain and
reconstructs every expected recurrence request. A partial or conflicting ledger
fails visibly. The wall-clock limit is checked before each generation and does
not interrupt in-flight work; generation and rejection counts remain persistent
across resume. Proposer, runner, evaluator, and a derived Controller timeout
bound that in-flight work.

After each completed generation, the next proposal sees only the caller's
original context plus generation number and a fixed previous-selection summary:
decision, reason, aggregate comparison, and selected candidate ID. It does not
receive submissions, per-case evaluator evidence, or protected evaluator
assets. The selected head remains in the ledger and is not installed.

See [`apps/evolution_driver/README.md`](../apps/evolution_driver/README.md) for
the exact boundary and stopping statuses.

## Constructed empirical acceptance

`apps/evolution_driver/signal_relay_acceptance.py` exercises the concrete Pi
proposer and text runner against one development case, then compares the
original parent and selected head on two separately loaded final cases. The
strict Signal Relay evaluator computes exact answers after both submissions
exist. The proposer receives the transformation rule but no case payloads or
results. The final suite is not loaded until the development generation has
completed and cannot affect retention.

The command succeeds only when Selection Gate promotes a one-pass development
improvement with no safety regression and the same selected candidate improves
from zero to two passes on the final suite. Its deterministic fake-Pi regression
test covers the complete wiring; a real-Pi invocation records the pinned agent
configuration and exact evidence in its report.

This is a constructed acceptance test, not a benchmark or a general improvement
claim. Its final cases are withheld from the proposer for one run, not secret
from the operating-system user. Reusing the published suite destroys its status
as untouched evidence for subsequent claims.

## Trust and security boundary

Runner, evaluator, and proposer commands execute with the current user's
permissions. Temporary skill materialization is not a sandbox. Shared connector
code executes command arrays
without a shell, rejects malformed JSON process output, and on POSIX kills the
ordinary process group when a timeout expires. The persistent fixture Observer
uses the same process-group cleanup when aborted or when shutdown times out.
This cleanup is not an isolation
boundary: an adversarial process may deliberately escape its group. The
controller enforces equal task documents and timeout values, but an adapter must
enforce model settings, tool access, token or monetary budgets, workspace
isolation, network policy, seeds, and credential access.

For serious evaluations:

- isolate parent and challenger in separate containers, VMs, or disposable
  workspaces;
- keep evaluator code and hidden targets inaccessible to candidate runs;
- pin agent, model, tool, adapter, and task-suite versions;
- use identical cases and budgets;
- reserve untouched final cases rather than repeatedly selecting on one suite;
- retain the complete generation report outside the candidate workspace; and
- require explicit approval before installing `next_parent`.

Evolution Driver and Population Driver hashes detect accidental state
modification but do not authenticate their writers. Repeated selection adapts
to the development suite, so that suite is no longer an untouched test after
the first retained decision. Population Driver additionally treats the first
final Population run as a permanent search seal.

A selected challenger is better only under the declared evaluator, cases,
policy, and execution controls. The protocol cannot prove broader
generalization, unbiased judging, or safe autonomous self-modification.
