# Bounded Evolution Driver

`evolver.py` is a source-only outer loop around the existing six-application
schema-version-2 Controller. It does not replace any stage:

```text
selected parent
    -> Mutator invokes one proposer for a complete skill or Git artifact
    -> Controller runs one evidence-gated generation
    -> Evolution Driver appends the completed result
    -> Selection Gate's next_parent becomes the next selected parent
```

Controller still owns ordering within a generation. The driver owns only
bounded recurrence between completed generations.

## Deterministic example

From the repository root:

```bash
rm -f /tmp/metering-self-evolve.jsonl /tmp/metering-self-evolve.jsonl.lock
uv run python apps/evolution_driver/evolver.py \
  --state /tmp/metering-self-evolve.jsonl \
  < apps/evolution_driver/example-request.json
```

The example uses `demo_proposer.py` and the deterministic runner/evaluator test
doubles. Generation 1 promotes a skill containing the required instruction.
Generation 2 proposes another content change but gains no additional task pass,
so the parent is retained and the configured consecutive-rejection limit stops
the run. This proves recurrence and retention wiring, not model improvement.

Run the same command again with the same request and state path to resume. A run
that already reached a limit emits the same summary without appending records.

## Constructed live-Pi acceptance

`signal_relay_acceptance.py` provides one reproducible, deliberately narrow
empirical check using the concrete fixed Pi proposer and text runner. Pin Pi through
its environment, choose a new state path, and retain the report:

```bash
export PI_PROVIDER=openai-codex
export PI_MODEL=gpt-5.6-sol
export PI_REASONING_LEVEL=max
export METERING_PI_COMMAND='["pi","--provider","openai-codex","--model","gpt-5.6-sol","--thinking","max"]'
state=/tmp/metering-signal-relay-$(date +%s).jsonl
uv run python apps/evolution_driver/signal_relay_acceptance.py \
  --state "$state" \
  > /tmp/metering-signal-relay-report.json
```

The development generation starts from a complete baseline `SKILL.md`. The Pi
proposer sees the declared Signal Relay rule but not the development payload,
evaluator results, or final payloads. The baseline and proposed skill then run
on the same development task. A separate evaluator requires an exact structured
answer. Here, `passed` means the answer equals the deterministic transformation,
and `safety_passed` means the submission is exactly one string-valued `answer`
field; it is interface-conformance evidence, not a broad safety claim. Each Pi
run supplies its own pre-evaluation pass/fail forecast. The challenger must
improve from zero passes to one with no safety regression before Selection Gate
can promote it.

Only after that generation completes does the acceptance command load two
predeclared final tasks from `signal-relay-final-tasks.json`. It compares the
original baseline and selected head through Controller without feeding the
result back into evolution. Acceptance requires baseline `0/2`, challenger
`2/2`, no safety failures, and the exact selected candidate identity. It refuses
an existing state path so a report cannot silently resume an earlier run.

The checked-in fake-Pi test proves this complete command deterministically. A
successful real-Pi report records the exact connector command and additionally
proves proposal, execution, retention, persistence, and transfer to those two
withheld payloads for that exact run and pinned configuration. It does **not**
prove broad capability improvement. The
assets are process-separated, not a security sandbox: commands still inherit
caller permissions, and rerunning the published final suite makes it reused
rather than untouched evidence.

## Request

The strict driver schema version 1 request contains:

- `initial_parent_artifact`: `agent-default-v1`, exactly one non-executable
  `SKILL.md` in `agent-skill-v1`, or one immutable `git-candidate-v1` descriptor;
- `proposal`: one command, timeout, and caller-approved JSON context;
- `generation`: the Controller evaluation, runner, evaluator, finite tasks, and
  explicit task/safety policy, excluding the mutation request constructed by
  the driver; and
- `limits`: positive integer generation, consecutive-rejection, and wall-clock
  limits.

For live proposals, replace the demo command with:

```json
{
  "command":[
    "uv","run","python",
    "connectors/fixed/pi/skill_proposer.py"
  ],
  "context":{},
  "timeout_seconds":300
}
```

Pin the Pi command with `METERING_PI_COMMAND` as documented in
[`connectors/fixed/pi`](../../connectors/fixed/pi/README.md). The tool-free
connector disables discovered resources, context files, tools, and session
persistence. It receives only the current parent and proposal context, then
returns one complete replacement `SKILL.md` and a reason. Prime Agent implements
the same protocol under `connectors/fixed/prime_agent/`; the general Signal
Relay acceptance remains Pi-specific for compatibility.

## State

The caller-selected JSONL file contains:

1. one canonical run header binding the normalized request; and
2. one canonical record for each completed Controller request and result.

Records are SHA-256 identified and parent-linked. Resume verifies canonical
encoding, hashes, links, recurrence requests, candidate identities, and
Selection Gate's selected identity. A malformed, partial, reordered, or
request-conflicting ledger fails; it is never silently repaired. A sibling
`.lock` directory prevents concurrent writers. Inspect a stale lock before
removing it.

A proposal or Controller failure leaves the current parent unchanged and does
not append a generation record. Hashes detect accidental modification; they do
not authenticate the writer.

## Output and stopping

A successful summary reports the selected run-local `head`, completed generation
and rejection counts, run and last-record IDs, state path, and one stopping
status:

- `generation_limit`;
- `rejection_limit`; or
- `wall_clock_limit`.

The wall-clock limit is checked before starting each generation; it does not
interrupt a generation already in flight. Resuming starts a new invocation
allowance while generation and rejection counts remain persistent. In-flight
work is bounded by proposer, runner, evaluator, and a derived Controller timeout.
Token and monetary limits remain adapter responsibilities because the driver
cannot infer provider usage from arbitrary commands.

## Limits

This recurrence evolves one normalized artifact and one challenger at a time.
The checked-in proposal commands support either one `SKILL.md` or one immutable
Git source/output descriptor. This driver has no candidate population, recursive
agents, database, learned mutation policy, automatic installation, production
deployment, or rollback command. The separate source-only
[Population Archive](../population/README.md) can index externally completed
candidate runs and allocate one parent without changing this driver's recurrence
semantics. See the [Git artifact bridge](../../artifacts/git/README.md) for
adapter source and external model-output evolution.
The proposer receives a fixed aggregate of the previous selection, not case
submissions or evaluator evidence. Protected evaluator assets must still be
isolated by the caller. Reserve an untouched final evaluation before making any
broader improvement claim.
