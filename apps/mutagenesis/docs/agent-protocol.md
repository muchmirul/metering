# Agent protocol

## Status

This document describes the protocol currently implemented by
`apps/mutagenesis/mutagenesis.py`.

It is a repository-local example protocol, not part of Metering's installed
Python API or `metering` JSON command. It is currently unversioned; an external
integration that depends on it should pin the repository revision.

## Transport

Each process handles exactly one request:

- standard input contains one UTF-8 JSON object followed by end-of-file;
- standard output contains one canonical JSON object on success;
- standard error contains one canonical JSON error on failure;
- success exits with status 0;
- request or probability failures exit with status 2; and
- command-line arguments are rejected.

Start a new process for each candidate. There is no JSON Lines session or
cross-request state. Canonical output sorts object keys, uses compact separators,
escapes non-ASCII characters, and never emits a non-finite JSON number.

## Request

The request has exactly three keys:

```json
{
  "candidate": "mutation-17",
  "evaluation": "weather-station-a/holdout-v1",
  "observations": [
    {"observation": "day-001", "target": "rain", "target_probability": 0.5},
    {"observation": "day-002", "target": "rain", "target_probability": 0.25},
    {"observation": "day-003", "target": "dry", "target_probability": 1.0}
  ]
}
```

| Field | Contract |
|---|---|
| `candidate` | Non-empty JSON string; treated as an opaque identifier |
| `evaluation` | Non-empty JSON string identifying one fixed environment and evaluation set |
| `observations` | Non-empty JSON array of observation objects |

Every observation object has exactly these keys:

| Field | Contract |
|---|---|
| `observation` | Non-empty JSON string, unique within the request |
| `target` | Non-empty JSON string naming the revealed outcome |
| `target_probability` | Finite JSON probability in `[0,1]` |

The probability must be the coordinate
`q_candidate(target | observation, evaluation)` from a normalized predictive
distribution committed before the target was revealed. The example represents
weather forecasts over `{rain, dry}` that were made first; the three later
reveals were rain, rain, and dry. The adapter receives only the three realized
coordinates, so it cannot verify the complete distributions or their timing.

The strings are identities, not semantics interpreted by the adapter. Booleans
are not probabilities. The adapter does not normalize counts, clip values, or
repair malformed input.

Invalid UTF-8, duplicate keys, missing keys, extra keys, non-finite numbers,
malformed JSON, an empty observation array, repeated observation identifiers,
and unsupported arguments are rejected. A JSON decimal is also rejected when
double-precision conversion would change exact nonzero to zero or exact
not-one to one.

## Finite response

For the example request, the canonical response is:

```json
{"candidate":"mutation-17","evaluation":"weather-station-a/holdout-v1","measurement":{"aggregate":{"infinite":false,"mean_target_surprisal_bits":1.0,"sample_count":3},"base":2.0,"metering_measure":"self_information","outcomes":[{"infinite":false,"observation":"day-001","target":"rain","target_probability":0.5,"value_bits":1.0},{"infinite":false,"observation":"day-002","target":"rain","target_probability":0.25,"value_bits":2.0},{"infinite":false,"observation":"day-003","target":"dry","target_probability":1.0,"value_bits":0.0}]}}
```

`measurement.outcomes` preserves the request order. Each `value_bits` is the
self-information of the corresponding target probability. The aggregate is
the equally weighted arithmetic mean of those values; `sample_count` is its
denominator.

An agent may compare separate reports only when `evaluation` and the exact set
of `(observation, target)` pairs match. Order may differ because the identifiers
establish correspondence. Run each environment as a separate evaluation; this
protocol has no cross-environment weighting rule.

## Infinite response

A zero target probability is valid and has infinite self-information:

```json
{"candidate":"impossible-target","evaluation":"eval","observations":[{"observation":"case-1","target":"yes","target_probability":0},{"observation":"case-2","target":"no","target_probability":0.5}]}
```

The response uses legal JSON rather than an infinity number:

```json
{"candidate":"impossible-target","evaluation":"eval","measurement":{"aggregate":{"infinite":true,"mean_target_surprisal_bits":null,"sample_count":2},"base":2.0,"metering_measure":"self_information","outcomes":[{"infinite":true,"observation":"case-1","target":"yes","target_probability":0.0,"value_bits":null},{"infinite":false,"observation":"case-2","target":"no","target_probability":0.5,"value_bits":1.0}]}}
```

JSON negative zero is mathematically zero and is emitted as `0.0`, so equivalent
zero inputs have one response representation.

## Errors

An envelope or JSON failure has code `invalid_request`:

```json
{"error":{"code":"invalid_request","message":"duplicate key: candidate"}}
```

A rejected target probability has code `invalid_probability`:

```json
{"error":{"code":"invalid_probability","message":"observations[0].target_probability: probability must be a real number"}}
```

The message identifies the failing observation position when probability
validation fails. Agents should branch on `error.code`; message wording is
diagnostic.

## Example invocation

```bash
printf '%s\n' \
  '{"candidate":"mutation-17","evaluation":"weather-station-a/holdout-v1","observations":[{"observation":"day-001","target":"rain","target_probability":0.5},{"observation":"day-002","target":"rain","target_probability":0.25},{"observation":"day-003","target":"dry","target_probability":1.0}]}' \
  | uv run python apps/mutagenesis/mutagenesis.py
```

The response is a measurement report. It is not an instruction to retain,
deploy, or discard the candidate.

## Compatibility

This change replaces the earlier positional `target_probabilities` request.
Callers must supply evaluation, observation, and target identities. Responses
now echo those identities and include aggregate `sample_count`. This protocol
is unversioned and repository-local; the installed Metering API and `metering`
JSON command are unchanged.
