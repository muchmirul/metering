# Candidate Runner

`candidate_runner.py` supports two source-only execution boundaries. Schema
version 1 gives one concrete meaning to the fixture Mutator genome. Schema
version 2 materializes a content-identified Agent Skills artifact and invokes a
caller-selected external agent adapter before trusted evaluation.

It is not part of the installed `metering` package.

## Model

The exact version 1 genome is:

```json
{"hypothesis":"v3","hypothesis_probability_bps":5000}
```

- `hypothesis` is one of `v1`, `v2`, `v3`, or `v4`.
- `hypothesis_probability_bps` is an integer from `2500` through `10000`.

The runner assigns `hypothesis_probability_bps / 10000` probability to the
named version and divides the remaining probability equally among the other
three versions. It then maps those version probabilities through the declared
Observer fixture model and sums versions that produce the same probe result.

For example, a `v3` hypothesis with probability `0.5` assigns probability
`2/3` to reading `fast\n` from `config/mode.txt`: `v3` contributes `0.5` and
`v4` contributes one-third of the remaining `0.5`.

The fixed model covers exactly:

```jsonl
{"operation":"list"}
{"operation":"read","path":"config/mode.txt"}
{"operation":"read","path":"service/port.txt"}
```

The runner asks Metering to validate and measure the entropy of every generated
result distribution. Forecast entropy describes uncertainty over probe results;
it does not establish candidate quality.

## Run

A candidate ID is the Mutator content ID for the exact genome. The controller
normally obtains it from Mutator and submits:

```bash
printf '%s\n' \
  '{"schema_version":1,"candidate_id":"3a756397c3adc6c065efa2563fdb00ebf46c878936476082c3311898d51793fa","genome":{"hypothesis":"v3","hypothesis_probability_bps":5000},"probe":{"operation":"read","path":"config/mode.txt"}}' \
  | uv run python apps/candidate_runner/candidate_runner.py
```

The response contains the complete normalized forecast:

```json
{
  "candidate_id":"3a756397c3adc6c065efa2563fdb00ebf46c878936476082c3311898d51793fa",
  "forecast":{
    "entropy":{"base":2.0,"infinite":false,"measure":"entropy","value":0.9182958340544894},
    "outcomes":[
      {"probability":0.6666666666666666,"target":"{\"kind\":\"text\",\"text\":\"fast\\n\"}"},
      {"probability":0.3333333333333333,"target":"{\"kind\":\"text\",\"text\":\"safe\\n\"}"}
    ]
  },
  "genome":{"hypothesis":"v3","hypothesis_probability_bps":5000},
  "probe":{"operation":"read","path":"config/mode.txt"},
  "runner_model":"observer-fixture-hypothesis-v1",
  "schema_version":1
}
```

`target` is the canonical JSON encoding of the possible Observer
`observed_result`. This gives the controller an exact, unambiguous lookup key
after reveal.

Use `--jsonl` for multiple independent requests. One response or recoverable
error is flushed per input line; the runner retains no state.

## Binding and limitations

The runner independently recomputes the documented Mutator candidate-ID formula
and rejects a candidate ID that does not match the supplied genome. That binds
the forecast to content, but it is not a signature or proof of trusted
execution.

The fixture mapping is deliberately duplicated as the candidate's declared
model. The runner never reads Observer's active sandbox. Tests compare this
model with the public Observer behavior so drift fails visibly.

Schema version 1 supports only this finite demonstration genome and probe
catalogue. Each request derives its distribution from the supplied genome and
does not condition on an earlier request.

Schema version 2 calls an explicit adapter command without a shell. The adapter
receives a temporary skill path (or `null` for the default agent), candidate ID,
and public task document. It returns one JSON submission and a complete
normalized forecast over evaluator-owned outcomes. Candidate Runner validates
that forecast through Metering before Observer invokes the evaluator. This is
the Pi and external-command integration seam; agent SDKs do not enter Metering.

The checked-in `pi_text_adapter.py` is a concrete read-only Pi integration for
text-response tasks. It disables discovered skills, context, extensions, tools,
and session persistence. Because Pi normally discloses full skill text through
the disabled `read` tool, the adapter explicitly injects the verified
materialized `SKILL.md` into Pi's system prompt while registering that skill.
Referenced scripts and assets are not exposed. Pin the Pi model and provider in
the runner environment or a reviewed wrapper command. The adapter requires Pi
to return a strict JSON submission and forecast. It is not suitable for coding
tasks that need tools or a mutable workspace. Tool-enabled Pi and other runners
implement the same adapter JSON boundary externally.

Adapter commands execute with caller permissions. They own agent configuration,
workspace isolation, tools, model budgets, and submission semantics. See the
[agent-skill protocol](../../docs/agent-evolution.md).

## Documentation

- [Architecture](docs/architecture.md)
- [Mathematical and technical foundations](docs/foundations.md)
- [Agent protocol](docs/agent-protocol.md)
