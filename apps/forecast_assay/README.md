# Forecast assay

`forecast_assay.py` is an agent-facing screening assay, not an autonomous
evolution system. Schema version 1 measures caller-supplied target forecasts.
Schema version 2 keeps trusted task pass and safety evidence separate while
measuring each candidate's committed pre-evaluation outcome forecast.

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
{"schema_version":1,"candidate":"forecast-17","evaluation":"weather-station-a/holdout-v1","observations":[{"observation":"day-001","target":"rain","target_probability":0.5},{"observation":"day-002","target":"rain","target_probability":0.25},{"observation":"day-003","target":"dry","target_probability":1.0}]}
```

- `schema_version` is the integer `1`.
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
  '{"schema_version":1,"candidate":"forecast-17","evaluation":"weather-station-a/holdout-v1","observations":[{"observation":"day-001","target":"rain","target_probability":0.5},{"observation":"day-002","target":"rain","target_probability":0.25},{"observation":"day-003","target":"dry","target_probability":1.0}]}' \
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

The command returns schema version 1, the candidate identifier, the
self-information of each target outcome in bits, and their arithmetic mean:

```json
{"candidate":"forecast-17","evaluation":"weather-station-a/holdout-v1","measurement":{"aggregate":{"infinite":false,"mean_target_surprisal_bits":1.0,"sample_count":3},"base":2.0,"metering_measure":"self_information","outcomes":[{"infinite":false,"observation":"day-001","target":"rain","target_probability":0.5,"value_bits":1.0},{"infinite":false,"observation":"day-002","target":"rain","target_probability":0.25,"value_bits":2.0},{"infinite":false,"observation":"day-003","target":"dry","target_probability":1.0,"value_bits":0.0}]},"schema_version":1}
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

The repository [Evolution Controller](../controller/README.md) implements those
bindings for one fixed Observer/Candidate Runner generation while leaving
repetition and policy changes to its caller.

Lower mean target surprisal for caller-declared outcomes does not establish
general adaptation, correctness, meaning, understanding, intelligence, or
usefulness.

## Agent-task reports

Schema version 2 accepts aligned task cases containing a complete normalized
candidate forecast and one evaluator result. It verifies the forecast's
reported entropy against Metering, then reports passed cases, safety failures,
evidence, and target self-information under separate names. Pass count
is evaluator-owned capability evidence; mean target surprisal is forecast
calibration evidence. Neither is relabeled as a universal score.

See the [agent-skill protocol](../../docs/agent-evolution.md).

## Compatibility

Schema version 2 is additive. Existing schema version 1 requests and reports,
one-shot and JSONL transport behavior, and Metering's installed interfaces are
unchanged.
