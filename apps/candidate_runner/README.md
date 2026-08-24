# Candidate Runner

`candidate_runner.py` gives one concrete executable meaning to a narrow Mutator
genome. It produces a complete probability distribution over the results of one
public Observer probe without receiving the active version or the revealed
result.

It is source-only example code, not a generic model runtime and not part of the
installed `metering` package.

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

The runner supports only this finite demonstration genome and probe catalogue.
Each request uses the same genome distribution and does not condition on an
earlier observation. It does not execute arbitrary code, load models, learn
probabilities, mutate, observe, select, persist state, or prove that a caller
obtained the forecast before target reveal.

## Documentation

- [Architecture](docs/architecture.md)
- [Agent protocol](docs/agent-protocol.md)
