# External-agent protocol

## Status

This repository-local protocol is implemented by
`apps/forecast_assay/forecast_assay.py`. It is not part of Metering's installed
Python API or `metering` JSON command. The request and report schema is
unversioned, so an integration should pin the repository revision.

Forecast assay supports two transports over the same strict schema:

- the default mode handles one request and exits; and
- `--jsonl` handles any number of independent requests in one process.

The JSONL mode adds transport persistence only. It does not add candidate
memory, comparison, selection, mutation, or cross-request state.

## One-shot transport

Without arguments:

- standard input contains one UTF-8 JSON object followed by end-of-file;
- standard output contains one canonical JSON report on success;
- standard error contains one canonical JSON error on failure; and
- success exits with status 0 while request or probability failure exits with
  status 2.

Example:

```bash
printf '%s\n' \
  '{"candidate":"forecast-17","evaluation":"weather-station-a/holdout-v1","observations":[{"observation":"day-001","target":"rain","target_probability":0.5}]}' \
  | uv run python apps/forecast_assay/forecast_assay.py
```

## JSONL transport

Start the persistent transport with:

```bash
uv run python apps/forecast_assay/forecast_assay.py --jsonl
```

The process then follows these rules:

- standard input receives exactly one UTF-8 JSON request per line;
- standard output returns exactly one canonical report or error per input line;
- every output line is flushed before the next request is read;
- requests are processed sequentially and independently;
- malformed lines do not terminate the process;
- an empty input stream is valid; and
- end-of-file exits with status 0.

Per-line errors go to standard output to preserve request/response alignment.
Standard error is reserved for a fatal stream failure. A recoverable error does
not alter later requests because the process retains no application state.
Blank lines, pretty-printed multi-line objects, and multiple objects on one line
are invalid requests.

`--jsonl` is the only supported argument. Other arguments are rejected with the
one-shot error behavior.

## Request

Every request has exactly three keys:

```json
{
  "candidate":"forecast-17",
  "evaluation":"weather-station-a/holdout-v1",
  "observations":[
    {"observation":"day-001","target":"rain","target_probability":0.5},
    {"observation":"day-002","target":"rain","target_probability":0.25},
    {"observation":"day-003","target":"dry","target_probability":1.0}
  ]
}
```

| Field | Contract |
|---|---|
| `candidate` | Non-empty JSON string; opaque candidate identifier |
| `evaluation` | Non-empty JSON string identifying one fixed environment and evaluation set |
| `observations` | Non-empty JSON array of observation objects |

Every observation has exactly these keys:

| Field | Contract |
|---|---|
| `observation` | Non-empty JSON string, unique within the request |
| `target` | Non-empty JSON string naming the revealed outcome |
| `target_probability` | Finite JSON probability in `[0,1]` |

The probability must be the coordinate
`q_candidate(target | observation, evaluation)` from a normalized predictive
distribution committed before the target was revealed. The adapter receives
only the realized coordinate, so it cannot verify the complete distribution or
forecast timing.

Identifiers are echoed but not interpreted. Booleans are not probabilities.
The adapter does not normalize, clip, smooth, weight, or repair values. Invalid
UTF-8, duplicate keys, missing or extra keys, non-finite numbers, malformed
JSON, empty observations, and duplicate observation identifiers are rejected.
A decimal token is also rejected if conversion to double precision would change
whether it is exactly zero or exactly one.

## Finite response

For the three-observation example, the canonical response is:

```json
{"candidate":"forecast-17","evaluation":"weather-station-a/holdout-v1","measurement":{"aggregate":{"infinite":false,"mean_target_surprisal_bits":1.0,"sample_count":3},"base":2.0,"metering_measure":"self_information","outcomes":[{"infinite":false,"observation":"day-001","target":"rain","target_probability":0.5,"value_bits":1.0},{"infinite":false,"observation":"day-002","target":"rain","target_probability":0.25,"value_bits":2.0},{"infinite":false,"observation":"day-003","target":"dry","target_probability":1.0,"value_bits":0.0}]}}
```

`measurement.outcomes` preserves request order. Each `value_bits` is the
self-information of its target probability. The aggregate is the equally
weighted arithmetic mean; `sample_count` is its denominator.

Reports are comparable only when `evaluation` and the exact set of
`(observation, target)` pairs match. Order may differ because identifiers
establish correspondence. Use a separate request for each environment; the
protocol has no cross-environment weighting rule.

## Infinite response

A zero target probability is valid and has infinite self-information. JSON
cannot encode infinity, so the outcome and aggregate use null values:

```json
{"candidate":"impossible-target","evaluation":"eval","measurement":{"aggregate":{"infinite":true,"mean_target_surprisal_bits":null,"sample_count":1},"base":2.0,"metering_measure":"self_information","outcomes":[{"infinite":true,"observation":"case-1","target":"yes","target_probability":0.0,"value_bits":null}]}}
```

Negative zero is emitted as `0.0`, giving mathematically identical zero inputs
one response representation.

## Errors

An envelope or JSON failure has code `invalid_request`:

```json
{"error":{"code":"invalid_request","message":"duplicate key: candidate"}}
```

A rejected target probability has code `invalid_probability`:

```json
{"error":{"code":"invalid_probability","message":"observations[0].target_probability: probability must be a real number"}}
```

In one-shot mode the error is written to standard error and exits with status
2. In JSONL mode it is the response line on standard output and processing
continues. Message wording is diagnostic; agents should branch on `error.code`.

## Compatibility

The default one-request command, request schema, success report, numerical
behavior, and one-shot error behavior are unchanged. `--jsonl` is an additive
transport. Existing callers do not need to migrate unless they want to reuse
one process for multiple independent assays.
