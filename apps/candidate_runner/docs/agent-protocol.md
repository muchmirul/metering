# Candidate Runner agent protocol

This page specifies fixture-model schema version 1. External agent-adapter
schema version 2 is specified in the
[agent-artifact evolution protocol](../../../docs/agent-evolution.md) and uses the
same one-shot and JSONL transports.

## Transport

Default mode reads one strict UTF-8 JSON object from standard input, writes one
canonical JSON object to standard output, and exits with status 0. Request or
probability failures write one canonical error to standard error and exit with
status 2.

`--jsonl` reads independent requests one per line and flushes one response or
recoverable error per line on standard output. End-of-file exits with status 0,
and no candidate state survives between lines. `--jsonl` is the only supported
argument.

## Version 1 request

```json
{
  "schema_version":1,
  "candidate_id":"3a756397c3adc6c065efa2563fdb00ebf46c878936476082c3311898d51793fa",
  "genome":{
    "hypothesis":"v3",
    "hypothesis_probability_bps":5000
  },
  "probe":{
    "operation":"read",
    "path":"config/mode.txt"
  }
}
```

Every object uses exact keys.

| Field | Contract |
|---|---|
| `schema_version` | Integer `1` |
| `candidate_id` | Lowercase 64-character Mutator candidate ID matching `genome` |
| `genome.hypothesis` | One of `v1`, `v2`, `v3`, or `v4` |
| `genome.hypothesis_probability_bps` | Integer from `2500` through `10000` |
| `probe` | Exact `list` or supported `read` Observer probe |

The accepted probes are:

```jsonl
{"operation":"list"}
{"operation":"read","path":"config/mode.txt"}
{"operation":"read","path":"service/port.txt"}
```

## Response

```json
{
  "candidate_id":"3a756397c3adc6c065efa2563fdb00ebf46c878936476082c3311898d51793fa",
  "forecast":{
    "entropy":{
      "base":2.0,
      "infinite":false,
      "measure":"entropy",
      "value":0.9182958340544894
    },
    "outcomes":[
      {
        "probability":0.6666666666666666,
        "target":"{\"kind\":\"text\",\"text\":\"fast\\n\"}"
      },
      {
        "probability":0.3333333333333333,
        "target":"{\"kind\":\"text\",\"text\":\"safe\\n\"}"
      }
    ]
  },
  "genome":{
    "hypothesis":"v3",
    "hypothesis_probability_bps":5000
  },
  "probe":{
    "operation":"read",
    "path":"config/mode.txt"
  },
  "runner_model":"observer-fixture-hypothesis-v1",
  "schema_version":1
}
```

`forecast.outcomes` is sorted by canonical target string. It is complete and
normalized. `forecast.entropy` is Shannon entropy in bits measured by Metering.
The target strings are canonical JSON encodings of possible Observer result
objects.

## Errors

```json
{"error":{"code":"invalid_request","message":"..."}}
```

`invalid_request` covers transport, schema, candidate-ID, genome, and probe
failures. `invalid_probability` is reserved for a generated distribution
rejected by Metering. The runner never repairs malformed input or a failed
identity binding.
