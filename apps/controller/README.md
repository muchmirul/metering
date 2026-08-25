# Evolution Controller

`controller.py` executes one complete, auditable generation across Mutator,
Candidate Runner, Observer, Forecast Assay, and Selection Gate.

```text
parent genome
    -> Mutator creates one child
    -> Candidate Runner forecasts for parent and child
    -> Observer reveals each shared probe result
    -> Forecast Assay measures both candidates
    -> Selection Gate chooses one candidate
    -> controller returns that candidate as next_parent
```

This is source-only example code. It is not part of the installed `metering`
package and does not turn Metering into an optimizer.

## Run the complete example

From the repository root:

```bash
uv run python apps/controller/controller.py \
  < apps/controller/example-request.json \
  > /tmp/metering-generation.json
```

Inspect the main result:

```bash
uv run python - <<'PY'
import json

with open("/tmp/metering-generation.json") as stream:
    report = json.load(stream)

print({
    "identified": report["observer"]["finish"]["snapshot"]["name"],
    "incumbent_mean": report["incumbent_report"]["measurement"]["aggregate"][
        "mean_target_surprisal_bits"
    ],
    "challenger_mean": report["challenger_report"]["measurement"]["aggregate"][
        "mean_target_surprisal_bits"
    ],
    "decision": report["selection"]["decision"],
    "next_parent": report["next_parent"]["candidate_id"],
})
PY
```

The checked-in request produces approximately:

```text
identified:       v3
incumbent mean:   0.5849625007211563 bits
challenger mean:  0.2630344058337938 bits
decision:         promote_challenger
```

## Run an agent-skill generation

Schema version 2 compares a content-identified default agent or parent skill
with one caller-proposed challenger over identical finite task documents:

```bash
uv run python apps/controller/controller.py \
  < apps/controller/agent-skill-example-request.json
```

The example request's runner and evaluator are deterministic protocol test
doubles. A real request can use the checked-in text-only Pi adapter or reviewed
Pi, Prime Agent, task-runner, and hidden-verifier adapters. The controller uses Mutator artifact IDs,
Candidate Runner submissions and committed forecasts, Observer's post-run
trusted evaluation, Forecast Assay reports, and Selection Gate's explicit task
policy before returning `next_parent`.

Pi users can copy
[`skills/metered-self-evolve`](skills/metered-self-evolve/SKILL.md) into
`~/.pi/agent/skills/` and invoke it explicitly as
`/skill:metered-self-evolve`. See the complete
[agent-skill evolution protocol](../../docs/agent-evolution.md).

## Input

The strict version 1 request contains:

```json
{
  "schema_version":1,
  "active_version":"v3",
  "evaluation":"observer-fixtures/config-port/holdout-v1",
  "mutation_request":{"...":"complete Mutator version 1 request"},
  "probes":[
    {"operation":"read","path":"config/mode.txt"},
    {"operation":"read","path":"service/port.txt"}
  ],
  "required_improvement_bits":0.05
}
```

- `active_version` is controller-owned Observer configuration, not candidate
  input.
- `evaluation` is copied into both Forecast Assay requests.
- `mutation_request` is sent through the public Mutator standard-stream
  protocol.
- `probes` must be unique, advertised by Observer, supported by Candidate
  Runner, and sufficient to identify exactly one fixture on the final probe.
- `required_improvement_bits` is Selection Gate's non-negative strict
  threshold.

See [`example-request.json`](example-request.json) for the complete executable
input.

## Process and ordering guarantee

For each probe the controller performs these operations in order:

1. Ask Candidate Runner for the incumbent's complete forecast.
2. Ask Candidate Runner for the challenger's complete forecast.
3. Only then send `observe` to Observer.
4. Encode the revealed result as the exact target string.

The controller carries Mutator's exact parent and child content IDs into the
runner and Forecast Assay. Candidate Runner independently verifies that each ID
matches its genome. Selection Gate then recomputes the assay reports and checks
that both candidates used identical evidence.

The applications are invoked as subprocesses through their documented JSON
standard-stream boundaries. Controller does not import their private modules.

## Output

A successful response contains:

- `mutation`: complete Mutator response;
- `observer.initial_state` and `observer.finish`;
- `cases`: every probe, both complete pre-reveal forecasts, and the subsequent
  Observer response;
- `incumbent_report` and `challenger_report`: complete Forecast Assay reports;
- `selection`: complete Selection Gate response; and
- `next_parent`: the selected content ID and genome.

The report is audit data for one process execution. It is not automatically
persisted. Redirect it to a caller-owned path if retention is required.

Use `--jsonl` for multiple independent generation requests in one process. Each
line still creates fresh component processes and retains no parent or lineage
state between requests.

## Errors

Malformed controller input returns `invalid_request`. A rejected component,
timeout, malformed component response, failed identity binding, forecast/evidence
mismatch, or incomplete Observer run returns `controller_error`.

One-shot errors are canonical JSON on standard error with exit status 2. JSONL
recoverable errors are aligned response lines on standard output.

## Deliberate limits

The controller runs exactly one generation per request. It has no hidden
randomness, mutation-policy adaptation, multi-generation lineage, persistent
state, installation, rollback, deployment, parallel evaluation, or security
sandbox. Schema version 1 callers choose the fixture, mutation distribution,
draw, probes, and forecast threshold. Schema version 2 callers choose the skill
artifacts, external commands, finite tasks, timeouts, and task policy.

Version 2 adapter commands execute arbitrary caller-approved programs with the
current user's permissions. Those adapters—not Controller—must isolate
workspaces, hidden tests, credentials, networks, tools, models, and non-time
budgets. Process ordering proves only what this trusted controller invoked. The
checked-in fixture and skill demonstrations prove protocol composition, not
generalization or real-world improvement.

## Documentation

- [Architecture](docs/architecture.md)
- [Mathematical, biological, and technical foundations](docs/foundations.md)
- [Agent protocol](docs/agent-protocol.md)
- [Evolution-kernel composition](../../docs/evolution-kernel.md)
