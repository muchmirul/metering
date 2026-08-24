# Selection gate agent protocol

## Transport

Default mode reads one strict UTF-8 JSON object from standard input and returns
one canonical JSON object. Request or report errors are written to standard
error with exit status 2.

`--jsonl` processes independent comparison requests one per line. It flushes one
decision or error per line and continues after recoverable line errors. No
incumbent is retained between requests.

## Request

```json
{
  "schema_version": 1,
  "incumbent_report": {
    "candidate": "parent-id",
    "evaluation": "weather/holdout-v1",
    "measurement": {
      "aggregate": {
        "infinite": false,
        "mean_target_surprisal_bits": 1.0,
        "sample_count": 2
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

Both reports must be complete canonical-shape Forecast Assay reports. Candidate
identifiers must differ. Evaluation identifiers and exact sets of
`(observation, target)` pairs must match. Outcome array order may differ.

`required_improvement_bits` is a finite non-negative number. The finite decision
uses exact floating-point `improvement > threshold`; report-verification
tolerance is not added to the threshold.

## Verification

For every outcome the gate calls:

```text
self_information(target_probability, base=2)
```

It verifies the reported value and infinity flag, then recomputes the equally
weighted arithmetic mean. Finite serialized values must agree within fixed
absolute and relative tolerance `1e-12`.

The gate rejects missing, additional, duplicated, or differently targeted
observations; altered sample counts; forged means; unsupported measure names;
and bases other than two.

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
    "sample_count": 2
  }
}
```

Decision values are exactly:

```text
promote_challenger
retain_incumbent
```

Reason values identify strict-threshold or infinity behavior. When an infinite
comparison makes subtraction undefined, `mean_improvement_bits` is null.

## Errors

```json
{"error":{"code":"invalid_request","message":"..."}}
```

`invalid_request` covers transport, schema, report integrity, evidence alignment,
and threshold errors. `invalid_probability` covers a target probability rejected
by Metering. No invalid report is converted into `retain_incumbent`; invalid
evidence fails explicitly.
