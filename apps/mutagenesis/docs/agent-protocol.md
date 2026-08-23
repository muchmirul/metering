# Agent protocol

## Status

This document describes the protocol currently implemented by
`apps/mutagenesis/mutagenesis.py`.

It is a repository-local example protocol, not part of Metering's installed
Python API or `metering` JSON command. It is currently unversioned; an external
integration that depends on it should pin the repository revision.

## Transport

Each process handles exactly one request:

- standard input contains one JSON object followed by end-of-file;
- standard output contains one canonical JSON object on success;
- standard error contains one canonical JSON error on failure;
- success exits with status 0;
- request or probability failures exit with status 2; and
- command-line arguments are rejected.

Start a new process for each candidate. There is no JSON Lines session or
cross-request state.

## Request

The request has exactly two keys:

```json
{
  "candidate": "mutation-17",
  "target_probabilities": [0.5, 0.25, 1.0]
}
```

| Field | Contract |
|---|---|
| `candidate` | Non-empty JSON string; treated as an opaque identifier |
| `target_probabilities` | Non-empty JSON array of finite probabilities in `[0,1]` |

Each probability is the candidate model's probability for one target outcome
whose meaning and ordering are maintained by the agent. Booleans are not
probabilities. The adapter does not normalize counts or repair malformed
values.

Duplicate keys, missing keys, extra keys, non-finite numbers, malformed JSON,
an empty probability array, and unsupported arguments are rejected.

## Finite response

For the example request, the canonical response is:

```json
{"candidate":"mutation-17","measurement":{"aggregate":{"infinite":false,"mean_target_surprisal_bits":1.0},"base":2.0,"metering_measure":"self_information","outcomes":[{"infinite":false,"target_probability":0.5,"value_bits":1.0},{"infinite":false,"target_probability":0.25,"value_bits":2.0},{"infinite":false,"target_probability":1.0,"value_bits":0.0}]}}
```

`measurement.outcomes` preserves the request order. Each `value_bits` is the
self-information of the corresponding target probability. The aggregate is
the equally weighted arithmetic mean of those values.

## Infinite response

A zero target probability is valid and has infinite self-information:

```json
{"candidate":"impossible-target","target_probabilities":[0,0.5]}
```

The response uses legal JSON rather than an infinity number:

```json
{"candidate":"impossible-target","measurement":{"aggregate":{"infinite":true,"mean_target_surprisal_bits":null},"base":2.0,"metering_measure":"self_information","outcomes":[{"infinite":true,"target_probability":0.0,"value_bits":null},{"infinite":false,"target_probability":0.5,"value_bits":1.0}]}}
```

## Errors

An envelope or JSON failure has code `invalid_request`:

```json
{"error":{"code":"invalid_request","message":"duplicate key: candidate"}}
```

A rejected target probability has code `invalid_probability`:

```json
{"error":{"code":"invalid_probability","message":"target_probabilities[0]: probability must be a real number"}}
```

The message identifies the failing list position when probability validation
fails. Agents should branch on `error.code`; message wording is diagnostic.

## Example invocation

```bash
printf '%s\n' \
  '{"candidate":"mutation-17","target_probabilities":[0.5,0.25,1.0]}' \
  | uv run python apps/mutagenesis/mutagenesis.py
```

The response is a measurement report. It is not an instruction to retain,
deploy, or discard the candidate.
