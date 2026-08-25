# Bounded Evolution Driver

`evolver.py` is a source-only outer loop around the existing six-application
schema-version-2 Controller. It does not replace any stage:

```text
selected parent
    -> Mutator invokes one proposer for a complete SKILL.md
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

## Request

The strict driver schema version 1 request contains:

- `initial_parent_artifact`: `agent-default-v1` or exactly one non-executable
  `SKILL.md` in `agent-skill-v1`;
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
    "apps/mutator/pi_skill_proposer.py"
  ],
  "context":{},
  "timeout_seconds":300
}
```

Pin the Pi model and provider in the command's environment or a reviewed wrapper.
The tool-free adapter disables discovered resources, context files, tools, and
session persistence. It receives only the current parent and proposal context,
then returns one complete replacement `SKILL.md` and a reason.

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

This first recurrence evolves only one `SKILL.md` and one challenger at a time.
It has no candidate population, recursive agents, database, learned mutation
policy, automatic installation, production deployment, or rollback command.
The proposer receives a fixed aggregate of the previous selection, not case
submissions or evaluator evidence. Protected evaluator assets must still be
isolated by the caller. Reserve an untouched final evaluation before making any
broader improvement claim.
