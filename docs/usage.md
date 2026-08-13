# Metering usage guide

This guide shows how to set up Metering, check the instrument, run one experiment, understand its output, write a policy, and rebuild a report offline.

## What Metering does

Metering runs a policy against a deterministic hidden-fault task:

1. The controller privately selects one of eight faults: `fault-0` through `fault-7`.
2. The policy receives only the public fault catalogue and its observation history.
3. The policy may diagnose, repair, verify, and finish.
4. Metering records every action in an append-only trace.
5. After execution, offline replay checks the trace and produces correctness, resource, and diagnostic-information readings.

Metering is a controlled measurement instrument, not a general agent benchmark or a hostile-code sandbox.

## Requirements

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Git, when cloning the repository

The runtime package has no third-party dependencies.

## 1. Set up the project

```bash
git clone https://github.com/muchmirul/metering.git
cd metering
uv sync --extra test
```

Confirm that the checkout works:

```bash
uv run --extra test pytest -q
```

Show the installed version:

```bash
uv run python -m metering --version
```

## 2. Run the calibration

Calibration checks Metering against policies whose expected behavior is known in advance:

```bash
uv run python -m metering calibrate
```

Expected final output:

```text
calibration passed: runs/calibration
balanced diagnostics: 24; sequential diagnostics: 35
```

Balanced search uses three diagnostic observations for each of the eight faults, or 24 total. Sequential search uses `[1, 2, 3, 4, 5, 6, 7, 7]`, or 35 total. Both policies solve all eight states correctly; the different costs prove that the meter can distinguish careful and wasteful diagnosis.

### Calibration options

Write to another directory:

```bash
uv run python -m metering calibrate --output /tmp/metering-check
```

Choose the random-baseline seed and action budget:

```bash
uv run python -m metering calibrate \
  --output /tmp/metering-check \
  --seed 20260722 \
  --budget 16
```

The calibration budget must be at least 10. The default output directory is `runs/calibration`.

Metering refuses to overwrite a non-empty directory. `--force` replaces an existing directory only when it contains Metering's calibration ownership marker:

```bash
uv run python -m metering calibrate --force
```

The full result, including failed checks, is saved as `calibration.json` in the output directory.

## 3. Run one hidden-fault experiment

Create `example.py` in the repository root:

```python
from metering import BalancedSearchPolicy, run_hidden_fault

result = run_hidden_fault(
    BalancedSearchPolicy(),
    hidden_fault_id="fault-3",
    run_dir="runs/example",
    run_id="example",
    action_budget=16,
)

print("Succeeded:", result.succeeded)
print("Correctness:", result.report["correctness"])
print("Resources:", result.report["resources"])
print("Information:", result.report["diagnostic_information"])
```

Run it:

```bash
uv run python example.py
```

The resource output for balanced search includes:

```text
{
  'diagnostic_observations': 3,
  'repair_actions': 1,
  'verification_actions': 1,
  'total_actions': 6,
  'action_budget': 16,
  'budget_exhaustion': False
}
```

The run directory must be new or empty. To run the example again, use a different directory or remove the old example directory intentionally.

`hidden_fault_id` sets controller-private truth. The controller does not pass that value or the world object to the policy callback.

## 4. Choose a built-in policy

Metering includes three reference policies:

```python
from metering import (
    BalancedSearchPolicy,
    SeededRandomSearchPolicy,
    SequentialSearchPolicy,
)

balanced = BalancedSearchPolicy()
sequential = SequentialSearchPolicy()
seeded = SeededRandomSearchPolicy(seed=20260722)
```

| Policy | Behavior | Diagnostic cost across all eight faults |
|---|---|---:|
| `BalancedSearchPolicy` | Chooses the most even remaining split | 24 |
| `SequentialSearchPolicy` | Checks candidates one at a time | 35 |
| `SeededRandomSearchPolicy` | Deterministic SHA-256-ranked test choice | Depends on the declared seed |

Use a separate run directory for every execution:

```python
from metering import SequentialSearchPolicy, run_hidden_fault

result = run_hidden_fault(
    SequentialSearchPolicy(),
    hidden_fault_id="fault-5",
    run_dir="runs/sequential-fault-5",
)
```

## 5. Understand the report

`result.report` and `report.json` contain three readings that remain separate.

### Correctness

```python
correctness = result.report["correctness"]
print(correctness["overall_task_success"])
```

Overall success requires all four conditions:

- the final repair matches the hidden fault;
- verification occurred after the final repair;
- the policy terminated normally with `Finish()`;
- the action budget was respected.

A correct repair without a later verification is not successful. A repair made after verification makes the earlier verification stale.

### Raw resources

```python
resources = result.report["resources"]
print(resources["diagnostic_observations"])
print(resources["repair_actions"])
print(resources["verification_actions"])
print(resources["total_actions"])
```

Metering does not combine these values into an overall score.

### Diagnostic information

```python
information = result.report["diagnostic_information"]
print(information["total_uncertainty_removed_bits"])
print(information["uncertainty_removed_per_diagnostic_observation_bits"])
print(information["progression"])
```

The initial uniform choice among eight faults contains three bits of uncertainty. Only delivered diagnostic outcomes reduce that uncertainty. Test selection, repair, verification, and finish do not count as diagnostic evidence.

A repeated diagnostic still costs an observation, but it normally removes zero additional bits.

## 6. Understand the four run artifacts

A completed run contains:

```text
runs/example/
├── manifest.json
├── events.jsonl
├── reference.json
└── report.json
```

| File | Written | Purpose |
|---|---|---|
| `manifest.json` | Before policy execution | Public instance, budget, policy descriptor, provenance, artifact identity, and an opaque commitment to private truth |
| `events.jsonl` | During execution | Append-only canonical events, observations, and raw costs |
| `reference.json` | After execution | Hidden fault, commitment nonce, private final state, and hashes binding the raw files |
| `report.json` | Last | Correctness, resources, diagnostic information, scope, and input hashes |

Treat `reference.json` as private while a policy is running because it contains the hidden answer. `manifest.json` exposes only a salted commitment to that answer.

The hashes detect corruption and accidental artifact mixing. They are integrity checks, not digital signatures or authentication.

## 7. Read the event trace

Load the canonical JSONL trace as typed events:

```python
from metering import read_events

for event in read_events("runs/example/events.jsonl"):
    print(event.step, event.event_type, event.payload, event.resources)
```

A successful balanced run normally has this shape:

```text
0  run_started
1  interaction: diagnose
2  interaction: diagnose
3  interaction: diagnose
4  interaction: repair
5  interaction: verify
6  interaction: finish
7  termination: normal_finish
```

Verification produces only `VerificationObservation()`. It does not reveal pass or fail to the policy; that result remains private until offline reporting.

## 8. Write a custom policy

A policy needs:

- `descriptor()`, returning exact finite JSON configuration;
- `next_action(instance, observations)`, returning one typed action.

The descriptor must contain exactly `name`, `version`, `configuration`, and `seed_policy`.

```python
from metering import (
    Diagnose,
    DiagnosticObservation,
    Finish,
    Repair,
    RepairObservation,
    VerificationObservation,
    Verify,
    run_hidden_fault,
)
from metering.policies import remaining_candidates


class FirstInformativePolicy:
    name = "first-informative"
    version = "1"

    def descriptor(self):
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {"order": "public_catalogue_order"},
            "seed_policy": {"kind": "none"},
        }

    def next_action(self, instance, observations):
        last_repair = max(
            (index for index, item in enumerate(observations)
             if isinstance(item, RepairObservation)),
            default=-1,
        )
        if last_repair >= 0:
            verified_after = any(
                index > last_repair and isinstance(item, VerificationObservation)
                for index, item in enumerate(observations)
            )
            return Finish() if verified_after else Verify()

        candidates = remaining_candidates(instance, observations)
        if len(candidates) == 1:
            return Repair(candidates[0])

        used = {
            item.test_id
            for item in observations
            if isinstance(item, DiagnosticObservation)
        }
        candidate_set = set(candidates)
        for test in instance.diagnostic_tests:
            positive = candidate_set.intersection(test.positive_fault_ids)
            if test.test_id not in used and 0 < len(positive) < len(candidate_set):
                return Diagnose(test.test_id)

        return Repair(candidates[0])


result = run_hidden_fault(
    FirstInformativePolicy(),
    hidden_fault_id="fault-6",
    run_dir="runs/custom-fault-6",
)
print(result.report["correctness"])
```

For a reproducibly randomized policy, declare a fixed integer seed:

```python
"seed_policy": {"kind": "fixed", "seed": 123}
```

A plain dictionary is not an action. Return `Diagnose`, `Repair`, `Verify`, or `Finish` objects. Unknown tests, unknown faults, verification before repair, and malformed output become explicit protocol failures and consume one action.

## 9. Rebuild a report offline

Recreate `report.json` from the three bound raw artifacts:

```bash
uv run python -m metering report runs/example
```

Typical output:

```text
regenerated runs/example/report.json for run example
```

You may delete the derived report first:

```bash
rm runs/example/report.json
uv run python -m metering report runs/example
```

Offline regeneration does not execute the policy or world. It validates:

- strict schemas and exact JSON types;
- contiguous event steps and stable identities;
- legal transitions and recorded action costs;
- diagnostic outcomes against the hidden fault;
- final private controller state;
- implementation provenance;
- the salted private-truth commitment;
- canonical bytes and artifact hashes.

If validation fails, the command exits with status 1 and does not replace an existing valid report.

## 10. Common failures

### The run directory is not empty

Use a new directory for each run:

```python
run_dir="runs/example-2"
```

Metering does not merge or silently overwrite run artifacts.

### Calibration output already exists

Choose a new output directory:

```bash
uv run python -m metering calibrate --output /tmp/metering-check-2
```

Use `--force` only for a directory previously created and marked by Metering calibration.

### `invalid_action`

The policy returned a malformed action, named an unknown catalogue entry, or verified before selecting a repair. The rejected attempt is recorded as `protocol_error`, costs one action, and terminates the run.

### `budget_exhausted`

The policy used the full budget without returning `Finish()`. Increase the budget or fix the stopping logic. A valid `Finish()` used as the final budgeted action still counts as normal completion.

### `harness_crash`

`next_action()` raised an ordinary Python exception. Metering records the termination but deliberately does not interpret the exception text.

### Report regeneration fails

One or more raw artifacts are malformed, inconsistent, non-canonical, mixed from different runs, corrupt, or incompatible with the installed replay implementation. Keep the raw files for investigation; Metering will not silently repair them.

## 11. Run project validation

Run the complete test suite:

```bash
uv run --extra test pytest -q
```

Run a fresh calibration outside the repository:

```bash
uv run python -m metering calibrate --output /tmp/metering-check
```

Rebuild one generated report:

```bash
uv run python -m metering report \
  /tmp/metering-check/reference/balanced/00
```

The tests and calibration run without a model server or network access.

## 12. Important limits

- Policies execute cooperatively in the Metering process; this is not hostile-code isolation.
- Metering cannot stop a callback that never returns.
- It cannot recover from a hard process exit, segmentation fault, out-of-memory kill, or interpreter failure.
- Diagnostic information measures delivered evidence, not whether a model understood or used it internally.
- Results are conditional on this declared eight-state world, catalogue, policy, configuration, and budget. They are not universal agent-quality measurements.
- Metering deliberately reports no combined leaderboard score.

## Further reading

- [Project overview](../README.md)
- [Normative scope and semantics](../PLAN.md)
- [HTML quickstart](quickstart.html)
- [Python API reference](api.html)
- [Developer guide](developer.html)
- [Release process](../RELEASING.md)
