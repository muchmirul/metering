# Selection gate

`selection_gate.py` verifies one incumbent and one challenger Forecast Assay
report and returns one deterministic retention decision. Schema version 1
selects on verified forecast loss. Schema version 2 selects on explicitly named
task pass and safety evidence while retaining forecast loss only as calibration
evidence.

```text
incumbent report + challenger report + required improvement
                              |
                              v
                        selection gate
                              |
                 promote challenger or retain incumbent
```

The application does not generate candidates, run evaluations, update mutation
probabilities, persist a lineage, or repeat generations.

## Run

Produce two complete reports with
[`apps/forecast_assay`](../forecast_assay), then submit them. This executable
example promotes `child-id` because its verified mean target surprisal improves
by more than `0.05` bits:

```bash
incumbent="$(
  printf '%s\n' \
    '{"schema_version":1,"candidate":"parent-id","evaluation":"weather/holdout-v1","observations":[{"observation":"case-1","target":"rain","target_probability":0.5}]}' \
    | uv run python apps/forecast_assay/forecast_assay.py
)"
challenger="$(
  printf '%s\n' \
    '{"schema_version":1,"candidate":"child-id","evaluation":"weather/holdout-v1","observations":[{"observation":"case-1","target":"rain","target_probability":0.75}]}' \
    | uv run python apps/forecast_assay/forecast_assay.py
)"
request="$(
  uv run python - "$incumbent" "$challenger" <<'PY'
import json
import sys

print(json.dumps({
    "schema_version": 1,
    "incumbent_report": json.loads(sys.argv[1]),
    "challenger_report": json.loads(sys.argv[2]),
    "required_improvement_bits": 0.05,
}, separators=(",", ":"), sort_keys=True))
PY
)"
printf '%s\n' "$request" \
  | uv run python apps/selection_gate/selection_gate.py
```

Use `--jsonl` for multiple independent comparisons in one process. One
canonical decision or error is flushed per line. No candidate state is retained.

## Decision rule

For finite verified mean target surprisals:

```text
mean_improvement_bits = incumbent_mean - challenger_mean
```

The challenger is promoted only when:

```text
mean_improvement_bits > required_improvement_bits
```

Equality retains the incumbent. There is no hidden epsilon in the decision.

Infinite reports are ordered conservatively:

```text
infinite incumbent, finite challenger -> promote challenger
finite incumbent, infinite challenger -> retain incumbent
both infinite                         -> retain incumbent
```

The output calls the measured quantity exactly what it is: empirical mean target
surprisal in bits on one declared evaluation. It is not an intelligence,
fitness, usefulness, or universal quality score.

## Verification

The gate does not trust aggregate report fields. It verifies:

- Forecast Assay report schema version 1 and exact envelopes;
- base 2 and `self_information` measure identity;
- unique observation identifiers;
- each target probability and its Metering self-information;
- per-outcome and aggregate infinity flags;
- aggregate sample count and mean;
- equal evaluation IDs; and
- equal sets of `(observation, target)` evidence, independent of array order.

A content ID for the aligned evaluation and evidence set is returned with the
decision.

Candidate fields remain opaque labels. In a Mutator composition, the external
controller must carry the exact Mutator parent and child `candidate_id` values
into the corresponding Forecast Assay requests and must ensure those genomes
were actually executed. The gate cannot infer that binding from report mathematics.
The repository [Evolution Controller](../controller/README.md) implements this
check for its fixed Candidate Runner.

## Agent-task policy

Schema version 2 implements `task-pass-count-v1`. It can reject any increase in
challenger safety failures, then requires a caller-declared positive integer
pass-count improvement. The gate recomputes target self-information and all
report aggregates before selecting. It does not infer correctness, compare
unmatched cases, or install the selected artifact.

See the [agent-artifact protocol](../../docs/agent-evolution.md).

The command remains `selection_gate.py`. Its schema-version-2 implementation is
isolated in `task_selection.py`; shared report-number checks live in
`report_validation.py`. This is source organization only, not another stage.

## Documentation

- [Architecture](docs/architecture.md)
- [Mathematical and biological foundations](docs/foundations.md)
- [Agent protocol](docs/agent-protocol.md)
