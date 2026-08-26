# Selection gate agent protocol

This page specifies forecast-loss schema version 1. Task-pass and safety policy
schema version 2 is specified in the
[agent-artifact evolution protocol](../../../docs/agent-evolution.md) and uses the
same one-shot and JSONL transports.

## Transport

Default mode reads one strict UTF-8 JSON object from standard input and returns
one canonical JSON object on standard output with exit status 0. Request or
report errors are written to standard error with exit status 2 and leave
standard output empty.

`--jsonl` processes independent comparison requests one per line. It flushes one
decision or error per line and continues after recoverable line errors. No
incumbent is retained between requests. Per-line errors use standard output to
preserve alignment; end-of-file, including an empty stream, exits with status
0. Blank lines, multi-line requests, multiple objects on one line, and invalid
UTF-8 lines are recoverable errors. A fatal input stream failure writes one
canonical error to standard error and exits with status 2.

`--jsonl` is the only supported argument. Any other argument is an
`invalid_request` error on standard error with exit status 2.

## Request

```json
{
  "schema_version": 1,
  "incumbent_report": {
    "schema_version": 1,
    "candidate": "parent-id",
    "evaluation": "weather/holdout-v1",
    "measurement": {
      "aggregate": {
        "infinite": false,
        "mean_target_surprisal_bits": 1.0,
        "sample_count": 1
      },
      "base": 2.0,
      "metering_measure": "self_information",
      "outcomes": [
        {
          "infinite": false,
          "observation": "case-1",
          "target": "rain",
          "target_probability": 0.5,
          "value_bits": 1.0
        }
      ]
    }
  },
  "challenger_report": {"...": "same Forecast Assay schema"},
  "required_improvement_bits": 0.05
}
```

Both reports must be complete Forecast Assay schema version 1 reports with
exact envelopes. Candidate identifiers must differ. Evaluation identifiers and
exact sets of `(observation, target)` pairs must match. Outcome array order may differ.

Candidate identifiers are opaque labels, not proof of model execution. When
composing with Mutator, the external controller must use the exact Mutator
`parent.candidate_id` and `child.candidate_id` values in the corresponding
Forecast Assay requests and verify that it executed those genomes. Selection
Gate verifies report mathematics and evidence alignment, not that external
binding. [`apps/controller/controller.py`](../../controller/controller.py)
implements that binding for the fixed Candidate Runner demonstration.

`required_improvement_bits` is a finite non-negative JSON number. Its conversion
to double precision must remain finite and may not turn an exact positive value
into zero. The finite decision uses exact floating-point
`improvement > threshold`; report-verification tolerance is not added to the
threshold.

## Verification

For every outcome the gate calls:

```text
self_information(target_probability, base=2)
```

It verifies the reported value and infinity flag, then recomputes the equally
weighted arithmetic mean. Finite serialized values must agree within fixed
absolute and relative tolerance `1e-12`.

The gate rejects missing, additional, duplicated, or differently targeted
observations; unsupported Forecast Assay report versions; altered sample counts;
forged means; unsupported measure names; and bases other than two.

## Response

```json
{
  "schema_version": 1,
  "decision": "promote_challenger",
  "reason": "required_improvement_exceeded",
  "incumbent": "parent-id",
  "challenger": "child-id",
  "selected": "child-id",
  "evaluation": "weather/holdout-v1",
  "evidence_id": "HEX_SHA256",
  "comparison": {
    "incumbent": {
      "infinite": false,
      "mean_target_surprisal_bits": 1.0
    },
    "challenger": {
      "infinite": false,
      "mean_target_surprisal_bits": 0.8
    },
    "mean_improvement_bits": 0.2,
    "required_improvement_bits": 0.05,
    "sample_count": 1
  }
}
```

Decision values are exactly:

```text
promote_challenger
retain_incumbent
```

Reason values are exactly:

```text
required_improvement_exceeded
required_improvement_not_exceeded
finite_challenger_beats_infinite_incumbent
infinite_challenger_rejected
both_reports_infinite
```

When an infinite comparison makes subtraction undefined,
`mean_improvement_bits` is null.

## Errors

```json
{"error":{"code":"invalid_request","message":"..."}}
```

`invalid_request` covers transport, schema, report integrity, evidence alignment,
threshold, and malformed numeric-field errors. `invalid_probability` is reserved
for a probability rejection raised by Metering after request decoding. No
invalid report is converted into `retain_incumbent`; invalid evidence fails
explicitly. In one-shot mode errors use standard error and exit with status 2.
In JSONL mode recoverable line errors use standard output and later lines remain
usable.

## Compatibility

Selection Gate request schema version 1 now requires embedded Forecast Assay
report schema version 1. Earlier unversioned reports must be regenerated or
migrated by adding the version only after verifying that their remaining shape
and measurements match Forecast Assay version 1.
