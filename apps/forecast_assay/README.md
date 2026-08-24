# Forecast assay

`forecast_assay.py` is an agent-facing probabilistic screening assay, not an
autonomous evolution system. It measures caller-supplied pre-reveal forecasts;
it does not create mutations.

```text
agent mutates, models, and commits forecasts
                    |
                    v
environment reveals targets
                    |
                    v
          forecast assay measures
                    |
                    v
agent compares, selects, and repeats
```

The application contains no neural architecture, environment, mutation
generator, selection policy, loop, memory, or stopping rule. An agent owns all
of those decisions.

## Documentation

- [Architecture](docs/architecture.md) explains the responsibility boundary
  and why the adapter stays this small.
- [Biological and mathematical foundations](docs/foundations.md) names the
  paradigm, derives the measured quantity, and states a testable hypothesis.
- [Agent protocol](docs/agent-protocol.md) specifies the implemented one-shot
  and JSONL transports, request, response, infinity representation, and errors.

## Request

Each assay request is one strict JSON object:

```json
{"candidate":"forecast-17","evaluation":"weather-station-a/holdout-v1","observations":[{"observation":"day-001","target":"rain","target_probability":0.5},{"observation":"day-002","target":"rain","target_probability":0.25},{"observation":"day-003","target":"dry","target_probability":1.0}]}
```

- `candidate` is an opaque non-empty identifier chosen by the agent.
- `evaluation` is an opaque non-empty identifier for one fixed environment and
  evaluation set.
- Every `observation` is a unique case identifier within that evaluation.
- `target` names the outcome that occurred.
- `target_probability` is the probability the candidate assigned to that
  target before it was revealed.

In this concrete example, the candidate first emitted normalized forecasts
over `{rain, dry}`. It assigned rain probabilities `0.5`, `0.25`, and `0.0` to
the three days. After the weather was revealed as rain, rain, and dry, the agent
extracted the corresponding target probabilities `0.5`, `0.25`, and `1.0`. In
notation, each input is
`q_candidate(target | observation, evaluation)`.

The application does not estimate, normalize, smooth, or repair these
probabilities, and it cannot verify that the complete forecasts were normalized
or committed before reveal. Those are caller obligations.

Run it from the repository root:

```bash
printf '%s\n' \
  '{"candidate":"forecast-17","evaluation":"weather-station-a/holdout-v1","observations":[{"observation":"day-001","target":"rain","target_probability":0.5},{"observation":"day-002","target":"rain","target_probability":0.25},{"observation":"day-003","target":"dry","target_probability":1.0}]}' \
  | uv run python apps/forecast_assay/forecast_assay.py
```

To reuse one process for multiple independent candidate requests, start JSONL
mode and write one compact request per line:

```bash
uv run python apps/forecast_assay/forecast_assay.py --jsonl
```

It flushes one report or error per input line and continues after malformed
requests. JSONL mode retains no candidate state and does not compare reports.

## Response

The command returns the candidate identifier, the self-information of each
target outcome in bits, and their arithmetic mean:

```json
{"candidate":"forecast-17","evaluation":"weather-station-a/holdout-v1","measurement":{"aggregate":{"infinite":false,"mean_target_surprisal_bits":1.0,"sample_count":3},"base":2.0,"metering_measure":"self_information","outcomes":[{"infinite":false,"observation":"day-001","target":"rain","target_probability":0.5,"value_bits":1.0},{"infinite":false,"observation":"day-002","target":"rain","target_probability":0.25,"value_bits":2.0},{"infinite":false,"observation":"day-003","target":"dry","target_probability":1.0,"value_bits":0.0}]}}
```

The arithmetic mean is application-owned aggregation, not a fifth Metering
measure or a general score. If any supplied target probability is zero, its
self-information and the aggregate are represented with `"infinite":true` and
a null value rather than invalid JSON. Accepted negative zero is emitted as
`0.0`, the same canonical representation as zero.

Invalid UTF-8, malformed JSON, duplicate or extra keys, unsupported arguments,
and invalid probabilities fail explicitly. In default one-shot mode they exit
with status 2 and one canonical JSON error on standard error. In `--jsonl` mode
a bad line returns that error on standard output and processing continues so
request/response alignment is preserved. Number parsing rejects a JSON number
if conversion to double precision would change whether it is exactly zero or
exactly one.

## Agent responsibility

An agent submits one request per candidate. Two reports are comparable only when
their `evaluation` identifiers and exact sets of `(observation, target)` pairs
match. Use a separate invocation for each environment so a pooled mean cannot
hide an environment-specific regression. Every observation is weighted equally.

The agent must still define:

- what it observed;
- how its model constructed every target probability;
- what was mutated;
- how candidates are compared;
- whether a mutation is retained; and
- when to continue or stop.

Lower mean target surprisal for caller-declared outcomes does not establish
general adaptation, correctness, meaning, understanding, intelligence, or
usefulness.

## Compatibility

This repository-local protocol is unversioned. `--jsonl` is additive: the
existing no-argument one-shot command, schemas, measurements, and errors are
unchanged. Metering's installed Python and JSON interfaces are unchanged.
