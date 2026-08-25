# Agent-skill evolution protocol

## Scope

Application schema version 2 executes one bounded comparison between an
incumbent agent configuration and one proposed skill artifact. It is an
additive, source-only application protocol. The installed `metering` package and
its JSON command are unchanged.

The reusable transition is:

```text
parent candidate + direct or proposer-produced challenger
    -> bind immutable skill artifacts
    -> run both through the same agent adapter on the same task cases
    -> reveal task results through a trusted evaluator adapter
    -> measure each committed outcome forecast
    -> compare explicit task pass and safety evidence
    -> return one selected next parent
```

The controller performs one generation. It does not repeat generations,
install the selected skill, or claim improvement outside the declared cases.
The optional Evolution Driver repeats this same transition under persistent
generation and rejection limits plus a per-invocation wall-clock limit, without
changing Controller semantics.

## Behavior-preserving decomposition

Schema version 2 was added without turning the public entry points into mixed
implementations:

- `apps/controller/controller.py` retains schema-version-1 fixture orchestration
  and dispatches schema-version-2 work to `agent_generation.py`;
- `component_runtime.py` owns Controller subprocess and component-response
  mechanics without owning application policy;
- `apps/observer/observer.py` remains the independently copyable fixture
  program, while `agent_evaluator.py` owns schema-version-2 external evaluation;
- Mutator keeps direct-challenger requests and adds a separate strict proposer
  path rather than weakening either request shape.

These are internal ownership changes, not new public commands. Recorded
schema-version-1 fixture outputs and direct-challenger schema-version-2 outputs
remain byte-identical. The split centralizes transport mechanics while leaving
mutation, evaluation, measurement, and retention policy in their owning
applications.

## Candidate artifacts

Version 2 supports two candidate artifact schemas.

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
components, backslashes, duplicate paths, missing or empty `SKILL.md`, and
non-string content are rejected. Executable mode is represented explicitly.
Binary assets, symlinks, ownership, timestamps, and other filesystem metadata
are not represented in version 1.

The candidate ID is:

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

For proposer-generated changes, both parent and challenger are restricted to a
default artifact or exactly one `SKILL.md`; the challenger must be a skill and
must differ. Mutator records the proposer command digest as provenance. It does
not pass tasks, evaluator commands, submissions, or protected evidence.

The checked-in `apps/mutator/pi_skill_proposer.py` is a concrete tool-free Pi
adapter. It disables tools, context files, discovered resources, and sessions,
then registers and injects the verified current `SKILL.md`. Pin model and
provider selection in its environment or a reviewed wrapper. It returns a full
replacement, never a patch, and does not decide retention.

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

`skill_path` is `null` for the default-agent artifact. A Pi adapter can omit
`--skill` for that candidate and use `--no-skills --skill PATH/SKILL.md` for a
skill candidate. Any other runner may implement the same JSON boundary using
its own public command. Agent SDKs do not belong in Metering.

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
entropy. `submission` is caller-owned JSON passed to the evaluator.

For text-only Pi evaluations, use:

```json
{
  "command":[
    "uv","run","python",
    "apps/candidate_runner/pi_text_adapter.py"
  ],
  "timeout_seconds":300
}
```

Its task input is exactly `{"prompt":"...","outcomes":["fail","pass"]}`. The
adapter disables tools, context files, discovered resources, and session
persistence. Pi normally uses `read` for progressive skill disclosure, so this
tool-free adapter registers the candidate skill and injects the complete,
verified materialized `SKILL.md` into Pi's system prompt. Referenced scripts and
assets are not exposed. Pin the Pi model and provider through the runner
environment or a reviewed wrapper command. The adapter therefore cannot
evaluate tool-using coding tasks. Such tasks need a separately reviewed adapter
with isolated workspaces and explicit tool and budget controls.

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
protocol composition only; they do not run Pi or establish empirical agent
improvement. Replace its runner with the checked-in text-only Pi adapter, or a
separately reviewed external adapter, and replace the evaluator for a real
evaluation.

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

## Trust and security boundary

Runner, evaluator, and proposer commands execute with the current user's
permissions. Temporary skill materialization is not a sandbox. Shared connector
code executes command arrays
without a shell, rejects malformed JSON process output, and on POSIX kills the
ordinary process group when a timeout expires. This cleanup is not an isolation
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

The Evolution Driver's hashes detect accidental state modification but do not
authenticate its writer. Repeated selection adapts to the generation suite, so
that suite is no longer an untouched test after the first retained decision.

A selected challenger is better only under the declared evaluator, cases,
policy, and execution controls. The protocol cannot prove broader
generalization, unbiased judging, or safe autonomous self-modification.
