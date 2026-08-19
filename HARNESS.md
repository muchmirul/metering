# Measuring your harness with Metering

This is the shortest correct path for an external agent that wants to test its
own harness against Metering's hidden-fault world. It routes to the rest of
the documentation rather than replacing it:

- [`README.md`](README.md) explains the concepts and the calibrated contrast.
- [`PLAN.md`](PLAN.md) is normative for scope and semantics; on any conflict, it wins.
- [`docs/usage.md`](docs/usage.md) is the full walkthrough of every command and reading.
- [`tests/`](tests/) are the executable acceptance criteria.
- [`examples/run_suite.py`](examples/run_suite.py) is the committed suite driver this guide uses.

## 1. Install and verify the instrument

Metering needs Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/), and
the runtime package has no third-party dependencies:

```bash
git clone https://github.com/muchmirul/metering.git
cd metering
uv sync --extra test
uv run --extra test pytest -q
uv run python -m metering calibrate
```

Calibration must end with exactly this contrast before you measure anything of
your own:

```text
calibration passed: runs/calibration
balanced diagnostics: 24; sequential diagnostics: 35
```

## 2. The contract your harness implements

A harness is one Python object with two string attributes and two methods.
Nothing else is inspected.

```python
class MyPolicy:
    name = "my-policy"
    version = "1"

    def descriptor(self):
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {},
            "seed_policy": {"kind": "none"},
        }

    def next_action(self, instance, observations):
        ...
```

The rules, all enforced before or during the run:

- `descriptor()` must return finite JSON with **exactly** the four keys
  `name`, `version`, `configuration`, and `seed_policy`. `seed_policy` is
  either `{"kind": "none"}` or `{"kind": "fixed", "seed": <int>}`. Anything
  else is rejected before the run starts and before any artifact is written.
- `next_action(instance, observations)` must return one **typed** action:
  `Diagnose(test_id)`, `Repair(fault_id)`, `Verify()`, or `Finish()`. A plain
  dict is not converted; it terminates the run as a protocol error.
- `instance` is a `PublicInstance`: `fault_ids` (`fault-0` … `fault-7`) and
  `diagnostic_tests`, each test carrying `test_id`, `description`, and
  `positive_fault_ids`. The hidden fault is never passed to your code.
- `observations` is everything delivered so far: `DiagnosticObservation(test_id,
  positive)`, `RepairObservation(fault_id)`, `VerificationObservation()`, and
  `FinishObservation()`. Note that `VerificationObservation()` carries **no
  result** — whether the repair matched stays private until offline reporting.

The successful shape of a run is `diagnose* → repair → verify → finish`. The
helper `metering.remaining_candidates(instance, observations)` filters the
fault list by delivered diagnostic outcomes, which is exactly the reasoning a
policy is entitled to do. Section 8 of [`docs/usage.md`](docs/usage.md) walks
through a complete working policy line by line.

## 3. Run the suite

Put your policy in a file, for example `my_policy.py`, and run the committed
driver from the repository root:

```bash
uv run python examples/run_suite.py my_policy:MyPolicy --json
```

The `module:Class` argument is imported with your current working directory on
the import path, and the class must be constructible with no arguments. The
driver runs one fresh directory per hidden fault, prints every per-run reading
and the suite aggregate, and exits 0 only when all eight runs succeed, so it
can gate a continuous-integration check directly. Without `--json` it prints
human-readable tables; sanity-check the plumbing first with a reference
policy:

```bash
uv run python examples/run_suite.py balanced
```

The equivalent loop, if you are embedding Metering rather than shelling out:

```python
from pathlib import Path

from metering import HiddenFaultSpec, aggregate_reports, run_hidden_fault
from my_policy import MyPolicy

parent = Path("runs/my-suite")
results = [
    run_hidden_fault(MyPolicy(), hidden_fault_id=fault_id, run_dir=parent / fault_id)
    for fault_id in HiddenFaultSpec.default().fault_ids
]
suite = aggregate_reports([result.report for result in results])
print(suite["diagnostic_information"]["excess_observations"])
```

Every run directory must be new or empty; Metering never merges or overwrites
run artifacts.

## 4. Read the numbers

Each run's `report.json` (and `result.report`) keeps three readings in
separate columns, and Metering never combines them into an overall score:

- `correctness` — four booleans plus their conjunction
  `overall_task_success`: the final repair matched the hidden fault,
  verification happened after that repair, the run finished normally, and the
  budget held.
- `resources` — raw counts: `diagnostic_observations`, `repair_actions`,
  `verification_actions`, `total_actions`, plus the budget and whether it was
  exhausted.
- `diagnostic_information` — realized uncertainty reduction in bits out of the
  initial three, with a per-observation progression.

The suite aggregate from `aggregate_reports` adds:

- `resources` totals across the runs;
- `diagnostic_information.total_uncertainty_removed_bits` and
  `bits_per_diagnostic_observation` — the ratio of the sums, not the mean of
  per-run ratios. Note the naming difference: the per-run field is
  `uncertainty_removed_per_diagnostic_observation_bits`.
- `excess_observations` — total diagnostic observations minus 24, the minimum
  total external path length of a binary decision tree over eight leaves. It
  is `null` unless the collection holds exactly eight successful reports, and
  interpreting a non-null value requires one run per hidden state under the
  same policy and configuration, which only you as the caller can guarantee.

## 5. Expected reference values

Run each reference policy through the driver before trusting your own
measurement. At the default seed these values are exact:

| Policy | Total diagnostics | Bits per observation | Excess observations |
|---|---:|---:|---:|
| `balanced` | 24 | 1.0000 | 0 |
| `seeded-random` (default seed 20260722) | 28 | 0.8571 | 4 |
| `sequential` | 35 | 0.6857 | 11 |

All three solve all eight states correctly, which is the point: correctness
alone cannot separate a careful policy from a wasteful one, and the resource
and information columns can.

## 6. Verify a run offline

Each run directory holds four files written in a fixed order —
`manifest.json` (before the run, committing to the hidden fault),
`events.jsonl` (append-only during the run), `reference.json` (revealing the
fault only after your code can no longer act), and `report.json` (derived
last). Any report can be deleted and rebuilt from the raw bytes without
executing your policy or the world:

```bash
rm runs/my-suite/fault-3/report.json
uv run python -m metering report runs/my-suite/fault-3
```

Strict replay validates schemas, transitions, costs, hashes, and the salted
commitment to the hidden fault; if anything fails, the command exits 1 and an
existing valid report is left untouched.

## 7. Failure modes you will actually hit

- **Descriptor rejected** — the driver prints `suite rejected: …` and exits 1
  before any artifact is written. Fix `descriptor()` to the exact four keys.
- **Run directory not empty** — the driver exits 2 without running; the Python
  API raises `RunnerError`. Use a fresh directory per run.
- **`invalid_action`** — an unknown test or fault id, a `Verify()` before any
  repair, or a non-typed return value. The attempt is charged one action and
  the run terminates; this shows up in the report, not as an exception.
- **`budget_exhausted`** — the policy never returned `Finish()` within the
  budget (default 16 actions; `--budget` raises it per run).
- **`harness_crash`** — `next_action()` raised. The exception text is
  deliberately not recorded in the artifacts, so debug by calling your
  `next_action()` directly outside the runner.
- **Report regeneration fails** — a raw artifact is malformed or inconsistent.
  Keep the raw files; they are the only evidence of what happened.

## 8. Scope you can rely on

The measured boundary is a cooperative, in-process Python object. There is no
external process, HTTP, or JSONL protocol, no enforced timeout, and no
sandbox, and none is promised; `PLAN.md` defers these explicitly. Your policy
may call a model or remote service internally, but you write that adapter,
you keep `next_action()` returning normally, and you declare enough
configuration in `descriptor()` to make the measurement honest. Metering
reports correctness, resource, and information readings for one declared
eight-state world — it does not rank agents and has no overall score.
