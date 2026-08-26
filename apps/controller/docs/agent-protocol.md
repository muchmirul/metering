# Evolution Controller agent protocol

This page specifies fixture generation schema version 1. General agent-artifact
generation schema version 2 is specified in the
[agent-artifact evolution protocol](../../../docs/agent-evolution.md) and uses the
same one-shot and JSONL transports. Bounded recurrence is an outer
[Evolution Driver](../../evolution_driver/README.md), not Controller state.

## Transport

Default mode reads one strict UTF-8 JSON object, executes one generation, writes
one canonical JSON report to standard output, and exits with status 0. Failures
write one canonical error to standard error and exit with status 2.

`--jsonl` accepts independent generation requests one per line and flushes one
report or recoverable error per line. Each line starts fresh component processes;
no candidate or lineage state survives between requests. `--jsonl` is the only
supported argument.

## Version 1 request

```json
{
  "schema_version":1,
  "active_version":"v3",
  "evaluation":"observer-fixtures/config-port/holdout-v1",
  "mutation_request":{
    "schema_version":1,
    "catalogue":{
      "loci":[
        {
          "locus":"hypothesis",
          "alleles":["v1","v2","v3","v4"]
        },
        {
          "locus":"hypothesis_probability_bps",
          "alleles":[2500,5000,7500]
        }
      ]
    },
    "parent_genome":{
      "hypothesis":"v3",
      "hypothesis_probability_bps":5000
    },
    "mutation_distribution":[
      {
        "locus":"hypothesis_probability_bps",
        "allele":7500,
        "probability":1
      }
    ],
    "draw":0
  },
  "probes":[
    {"operation":"read","path":"config/mode.txt"},
    {"operation":"read","path":"service/port.txt"}
  ],
  "required_improvement_bits":0.05
}
```

The outer request uses exact keys.

| Field | Contract |
|---|---|
| `schema_version` | Integer `1` |
| `active_version` | One of `v1`, `v2`, `v3`, or `v4` |
| `evaluation` | Non-empty identifier echoed through both assay reports |
| `mutation_request` | Complete Mutator version 1 request |
| `probes` | Non-empty array of unique Observer probe objects |
| `required_improvement_bits` | Finite non-negative JSON number |

The component protocols perform their own strict validation. In particular, the
Mutator result must use the exact Candidate Runner genome schema, and all probes
must be both advertised by Observer and supported by Candidate Runner.

## Response

The canonical response has these top-level fields:

```json
{
  "schema_version":1,
  "evaluation":"observer-fixtures/config-port/holdout-v1",
  "runner_model":"observer-fixture-hypothesis-v1",
  "mutation":{"...":"complete Mutator response"},
  "observer":{
    "active_version":"v3",
    "initial_state":{"...":"complete Observer state response"},
    "finish":{"...":"complete Observer finish response"}
  },
  "cases":[
    {
      "observation":"probe-1:{\"operation\":\"read\",\"path\":\"config/mode.txt\"}",
      "probe":{"operation":"read","path":"config/mode.txt"},
      "incumbent_forecast":{"...":"complete Candidate Runner response"},
      "challenger_forecast":{"...":"complete Candidate Runner response"},
      "observer_response":{"...":"subsequent Observer observe response"},
      "target":"{\"kind\":\"text\",\"text\":\"fast\\n\"}"
    }
  ],
  "incumbent_report":{"...":"complete Forecast Assay response"},
  "challenger_report":{"...":"complete Forecast Assay response"},
  "selection":{"...":"complete Selection Gate response"},
  "next_parent":{
    "candidate_id":"HEX_SHA256",
    "genome":{"...":"selected genome"}
  }
}
```

Ellipses above document nested component envelopes; the executable response
contains the complete objects without placeholders. See
[`../example-request.json`](../example-request.json) and run the command for one
canonical full report.

The array order records process order. Inside each case, both runner responses
were obtained before `observer_response`.

## Errors

Outer transport and schema failures use:

```json
{"error":{"code":"invalid_request","message":"..."}}
```

Execution and composition failures use:

```json
{"error":{"code":"controller_error","message":"..."}}
```

A component failure is not converted into a selection or implicit incumbent
retention. In JSONL mode either error is an aligned response on standard output
and later lines remain independent.
