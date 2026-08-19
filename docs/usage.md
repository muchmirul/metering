# Metering usage guide

This guide shows how to set up Metering, check the instrument, run one experiment, understand its output, write a policy, and rebuild a report offline. Each section builds on the one before it, so reading straight through gives you a working setup and an accurate picture of what the numbers mean.

## What Metering does

Metering runs a policy against a deterministic hidden-fault task. The controller privately holds one of eight faults, `fault-0` through `fault-7`, and the policy receives only the public fault catalogue and its own observation history. From there the policy may diagnose, repair, verify, and finish, and Metering records every action in an append-only trace. After execution ends, offline replay checks that trace and produces three readings, covering correctness, resource cost, and diagnostic information.

The point of this arrangement is that the correct answer is known in advance. Because the world is deterministic and its rules are published, anyone reading a saved run can recompute exactly what the policy could have known at every step, which makes a result checkable rather than merely reported. Metering measures one controlled task under declared conditions, so its output describes that task rather than agent quality in general, and it does not attempt to isolate hostile code.

## The system, from high level to low level

Metering is assembled from focused modules. Each layer depends only on the layers below it, so you can read the stack top down and know where any behavior comes from. The commands in this guide enter at the top, and the readings you get back are produced near the bottom.

```text
HIGH LEVEL
  __main__.py       entry points        metering calibrate, metering report, run_hidden_fault
  calibration.py    the self check      eight states x three policies, every report rebuilt
  runner.py         controller loop     ask, charge the budget, apply, record, decide to stop
  policies.py       harness boundary    next_action(public instance, observations so far)
  hidden_fault.py   world               owns the selected fault, validates, applies, returns cost
  events / trace    protocol and bytes  four actions, four observations, append-only JSONL
  binding.py        commitment          salted hash of the private truth
  on disk           run artifacts       manifest.json, events.jsonl, reference.json
  replay.py         strict replay       rebuild state, check identity, transitions, costs, hashes
  report.py         verifier and meters correctness, raw counts, information in bits
  schema.py         strict decoding     exact keys, exact types, finite numbers, no duplicates
LOW LEVEL
```

Sections 3 and 8 of this guide work at the harness boundary in the middle of that stack, which is the only layer you normally write code against. Sections 9 and 11 work at the replay and report layers near the bottom, which read files that are already written and can therefore never change the run they describe. For the mathematical reasoning behind these layers, read the [theory and scope guide](theory.html), which places every explanation beside the code that implements it.

## Requirements

Metering needs Python 3.11 or newer, [`uv`](https://docs.astral.sh/uv/), and Git when you clone the repository. The runtime package itself has no third-party dependencies, so the checkout below is everything you need, and the test suite runs without a network connection or a model server.

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

The version comes from the current Git tag, so a checkout without tags reports a development value rather than a release number.

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

Those two totals are the point of the exercise. Balanced search uses three diagnostic observations for each of the eight faults, or 24 in total, while sequential search uses `[1, 2, 3, 4, 5, 6, 7, 7]`, or 35 in total. With the default seed, the seeded-random reference uses 28. All three policies solve all eight states correctly.

A binary decision tree with eight leaves has a minimum total leaf depth of 24. The calibration summary therefore reports suite-level `excess_observations` of 0 for balanced search, 4 for seeded random search, and 11 for sequential search. This field does not appear in individual run reports, because a valid short path can be shallower than the worst-case depth.

### Read the suite-level result

`calibration.json` is the simplest place to read the new value:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

summary = json.loads(Path("runs/calibration/calibration.json").read_text())
for policy in ("balanced", "seeded_random", "sequential"):
    result = summary["aggregates"][policy]
    print(policy, result["diagnostic_observations_total"], result["excess_observations"])
PY
```

The default calibration prints:

```text
balanced 24 0
seeded_random 28 4
sequential 35 11
```

To aggregate your own results, pass one report for every hidden state:

```python
from metering import aggregate_reports

suite = aggregate_reports(all_eight_reports)
print(suite["diagnostic_information"]["excess_observations"])
```

`aggregate_reports()` continues to aggregate resources and information for collections of any size. The excess value is `None` unless the collection contains exactly eight successful reports. To interpret a non-null value, those reports must cover one run per hidden state under the same policy, world, and configuration. The function can check count and success, but it cannot infer private state coverage or common policy provenance from report files; the caller must establish those facts, as calibration does.

### Calibration options

Write to another directory:

```bash
uv run python -m metering calibrate --output /tmp/metering-check
```

Choose the random-baseline seed and the action budget:

```bash
uv run python -m metering calibrate \
  --output /tmp/metering-check \
  --seed 20260722 \
  --budget 16
```

The budget must be at least 10, because a reference policy may need seven diagnostics plus a repair, a verification, and a finish. The default output directory is `runs/calibration` when `--output` is omitted.

Metering refuses to overwrite a non-empty directory. Passing `--force` replaces an existing directory only when it carries Metering's calibration ownership marker, so a mistyped path cannot turn calibration into a recursive delete:

```bash
uv run python -m metering calibrate --force
```

Every check is written to `calibration.json` in the output directory, including the ones that failed. A failing suite still writes that file before it exits, so the reason stays available after the terminal has scrolled away.

## 3. Run one hidden-fault experiment

A single run is one call. Create `example.py` in the repository root:

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

The run directory must be new or empty, because a run owns the files it writes and will not merge itself into another run's results. To run the example again, either name a different directory or remove the old one deliberately.

The `hidden_fault_id` argument sets controller-private truth. The controller passes neither that value nor the world object to the policy callback, so choosing the fault here tells the policy nothing and the run stays a fair measurement.

The committed driver [`examples/run_suite.py`](../examples/run_suite.py) extends this single run into the complete eight-state suite and prints the aggregate readings, so measuring a policy across every hidden state does not require writing the loop yourself.

## 4. Choose a built-in policy

Metering includes three reference policies, and all three are deterministic:

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
| `SeededRandomSearchPolicy` | Deterministic SHA-256-ranked test choice | Depends on the declared seed, and is 28 at the default seed |

The seeded policy ranks tests by hashing rather than by calling `random.Random`, which keeps its choices stable across Python releases. Because of this, rerunning it with the same seed produces the same interaction sequence, which is what makes it useful as a determinism check.

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

`result.report` and `report.json` contain three readings that stay separate. They answer different questions, and combining them would let a cheap failure look better than an expensive success.

### Correctness

```python
correctness = result.report["correctness"]
print(correctness["overall_task_success"])
```

Overall success requires all four of these conditions:

- the final repair matches the hidden fault;
- verification occurred after the final repair;
- the policy terminated normally with `Finish()`;
- the action budget was respected.

The four stay visible individually so that a failure says which part went wrong. For example, a run that repaired correctly but never verified afterwards fails the second condition, and so does a run that verified and then repaired again, because a later repair makes the earlier verification stale. Reporting only a single Boolean would hide the difference between those two mistakes.

### Raw resources

```python
resources = result.report["resources"]
print(resources["diagnostic_observations"])
print(resources["repair_actions"])
print(resources["verification_actions"])
print(resources["total_actions"])
```

These counts stay in separate columns at every layer, and Metering never adds them together into an overall score. A diagnostic observation and a repair are different kinds of expense, so only the reader knows how to trade one against the other.

### Diagnostic information

```python
information = result.report["diagnostic_information"]
print(information["total_uncertainty_removed_bits"])
print(information["uncertainty_removed_per_diagnostic_observation_bits"])
print(information["progression"])
```

The initial uniform choice among eight faults contains three bits of uncertainty, and the meter reports how much of that the delivered results actually removed. Only delivered diagnostic outcomes reduce the uncertainty, because choosing a test is an intervention rather than evidence, and repair, verification, and finish carry no diagnostic content. As a result, a repeated diagnostic still costs an observation and removes exactly zero additional bits, since the candidate set has already been filtered by that test's outcome. That zero is the waste the meter exists to make visible.

## 6. Understand the four run artifacts

A completed run contains four files, and the order in which they are written is part of what they prove:

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
| `reference.json` | After execution | Hidden fault, commitment nonce, private final state, and hashes binding the manifest and event files |
| `report.json` | Last | Correctness, resources, diagnostic information, scope, and hashes of all three raw inputs |

```text
  before the run        during the run        after the policy ends    last
  ------------------    ------------------    ---------------------    -----------
  manifest.json    ->   events.jsonl     ->   reference.json      ->   report.json
  public instance,      append-only           hidden fault,            correctness,
  budget, policy,       canonical facts,      nonce, byte              resources,
  salted commitment     one line per step     bindings                 information

  the policy acts only in this window:  [ during the run ]
  the hidden fault is disclosed only here:                [ after the policy ends ]
```

The manifest commits to the hidden fault before the policy receives its first callback, and the reference reveals that fault only once the policy can no longer act on it. Replay recomputes the commitment from the revealed values, so a plausible hidden fault cannot be substituted afterwards. The nonce is what makes this work, because a bare hash of one of eight faults could be reversed by hashing all eight and comparing.

Treat `reference.json` as private while a policy is running, since it contains the hidden answer, and note that `manifest.json` exposes only the salted commitment to it. The hashes detect corruption, staleness, and accidentally mixed artifacts, which means they are an integrity check against accident rather than a signature or an authentication scheme.

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

Step 5 is worth reading closely, because verification produces only `VerificationObservation()` and that value carries no result. Whether the repair matched stays private until offline reporting, so a policy learns that verification happened and nothing more. If the outcome came back instead, a policy could call verification repeatedly to identify the fault, and the resource meter would count cheap verifications rather than the diagnostics that were really being performed.

## 8. Write a custom policy

A policy is any object with two methods. `descriptor()` returns exact finite JSON describing its configuration, and `next_action(instance, observations)` returns one typed action. The descriptor must contain exactly `name`, `version`, `configuration`, and `seed_policy`, and Metering validates it before the run starts, because a result nobody can reproduce is worse than no result.

The two methods see this much and no more:

```text
  your policy receives                        the controller keeps private
  ----------------------------------------    ----------------------------------
  PublicInstance                              the selected hidden fault
    fault_ids: fault-0 ... fault-7            whether each verification passed
    diagnostic_tests                          the commitment nonce
      test_id, description,                   the final private world state
      positive_fault_ids

  observations delivered so far
    DiagnosticObservation(test_id, positive)
    RepairObservation(fault_id)
    VerificationObservation()   <- no result
    FinishObservation()
```

Here is a complete working policy that picks the first catalogue test able to separate the remaining candidates:

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

The helper `remaining_candidates` does the reasoning a policy is entitled to do, filtering the fault list by delivered diagnostic outcomes and the published observation model while ignoring repair and verification results. Writing that logic yourself is fine, and using the helper keeps a policy honest about what it was allowed to know.

For a reproducibly randomized policy, declare a fixed integer seed in the descriptor instead of `{"kind": "none"}`:

```python
"seed_policy": {"kind": "fixed", "seed": 123}
```

Return `Diagnose`, `Repair`, `Verify`, or `Finish` objects, because a plain dictionary is not converted into an action. Unknown tests, unknown faults, verification before a repair, and malformed output all become explicit protocol failures that consume one action and end the run, since a defect in the thing being measured should surface rather than be quietly corrected.

## Which harnesses can be measured today?

The directly supported harness is a cooperative Python object implementing the policy contract shown above. It runs inside Metering, receives only the public hidden-fault instance and its delivered observations through the documented callback, returns one typed action at a time, and declares its configuration through `descriptor()`. A custom diagnostic decision rule or planner that fits this shape can be measured now.

A Python policy may call a model or remote service internally, but Metering provides no ready-made adapter. The user must translate the public instance and observation history into that system's request, turn its response into a typed Metering action, and record enough configuration to make the policy declaration honest. The execution boundary remains cooperative and in process even when the policy delegates work elsewhere.

| Harness | Current support |
|---|---|
| Built-in reference policy | Direct |
| Custom Python hidden-fault policy | Direct |
| Python wrapper around a model or service | Manual adapter written by the user |
| Agent CLI, HTTP harness, or separate process | No direct protocol or process controller |
| Coding, browser, shell, or repository agent | Not supported by the current world |
| Hostile or potentially nonreturning callback | Not supported |

For a step-by-step path aimed at an external agent testing its own harness, read [`HARNESS.md`](../HARNESS.md) in the repository root.

## 9. Rebuild a report offline

Recreate `report.json` from the three bound raw artifacts:

```bash
uv run python -m metering report runs/example
```

Typical output:

```text
regenerated runs/example/report.json for run example
```

You may delete the derived report first, which is a good way to confirm that the rebuild really does reproduce it:

```bash
rm runs/example/report.json
uv run python -m metering report runs/example
```

Offline regeneration executes neither the policy nor the world. It validates:

- strict schemas and exact JSON types;
- contiguous event steps and stable identities;
- legal transitions and recorded action costs;
- diagnostic outcomes against the hidden fault;
- final private controller state;
- implementation provenance;
- the manifest's declared execution boundary and reproducibility limits, so a manifest cannot claim a guarantee Metering does not provide;
- the salted private-truth commitment;
- canonical bytes and artifact hashes.

If any of that fails, the command exits with status 1 and leaves an existing valid report exactly as it was. A corrupt run therefore keeps whatever report it already had, which is what makes a rebuilt report worth the same as the original.

## 10. Common failures

### The run directory is not empty

Use a new directory for each run, since Metering does not merge or silently overwrite run artifacts:

```python
run_dir="runs/example-2"
```

### Calibration output already exists

Choose a new output directory, and reserve `--force` for a directory that a previous Metering calibration created and marked:

```bash
uv run python -m metering calibrate --output /tmp/metering-check-2
```

### `invalid_action`

The policy returned a malformed action, named an unknown catalogue entry, or verified before selecting a repair. The rejected attempt is recorded as a `protocol_error` event, costs one action, and terminates the run. Charging the attempt is deliberate, because it stops a policy from probing the validator for free.

### `budget_exhausted`

The policy used the full budget without returning `Finish()`, so either the budget is too low for the strategy or the stopping logic needs fixing. A valid `Finish()` spent as the final budgeted action still counts as normal completion, because the policy did finish and the budget did hold.

### `harness_crash`

`next_action()` raised an ordinary Python exception. Metering records the termination, and the exception text is deliberately neither stored in the artifacts nor interpreted, since a meter that read error strings would be measuring prose.

### Report regeneration fails

One or more raw artifacts are malformed, inconsistent, non-canonical, mixed from different runs, corrupt, or incompatible with the installed replay implementation. Keep the raw files for investigation, because Metering will not silently repair them and the originals are the only evidence of what happened.

## 11. Run project validation

Run the complete test suite:

```bash
uv run --extra test pytest -q
```

Run a fresh calibration into a directory nothing else is using:

```bash
uv run python -m metering calibrate --output /tmp/metering-validation
```

Rebuild one of the reports it generated:

```bash
uv run python -m metering report \
  /tmp/metering-validation/reference/balanced/00
```

These three commands cover the instrument end to end, and none of them needs a model server or network access. The developer guide lists the further checks that a change to the package itself should pass, including `uv lock --check`, `compileall`, and `ruff`.

## 12. Important limits

An instrument is useful only when its limits are as clear as its results. These boundaries define what the current measurements mean, and they are recorded inside every report.

- The current experiment covers one deterministic eight-state world. It does not measure performance on real software work or harness quality in general.
- There is no external harness protocol, model adapter, subprocess controller, enforced timeout, tool runner, or repository task.
- Policies execute cooperatively inside the Metering process. This provides API non-disclosure, not isolation from hostile code.
- Metering cannot stop a callback that never returns or recover from a hard process exit, segmentation fault, out-of-memory kill, or interpreter failure.
- Diagnostic information is realized uncertainty reduction from delivered catalogue results. It says nothing about whether a model understood, remembered, trusted, or used that evidence.
- The entropy calculation assumes the declared uniform prior and deterministic observation table. A different world needs its own prior, observation semantics, calibration cases, and validated meter.
- Correctness, raw resources, and information remain separate. Metering has no overall score, ranking, or leaderboard.
- Suite-level excess observations apply only to a successful, complete eight-state suite. General aggregation still works for one run or an arbitrary collection, but its excess value is null.
- Meter version 2 adds the suite-level interpretation. Strict replay of meter-v1 artifacts still requires a v1-compatible checkout; controller, verifier, and artifact schema versions remain at 1.
- Hashes and commitments detect corruption and accidental artifact mixing. They provide neither authentication nor protection from coherent malicious rewriting.

## Further reading

- [Project overview](../README.md)
- [Normative scope and semantics](../PLAN.md)
- [Theory, implementation, and scope](theory.html)
- [HTML quickstart](quickstart.html)
- [Python API reference](api.html)
- [Developer guide](developer.html)
- [Release process](../RELEASING.md)
