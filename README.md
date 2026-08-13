# Metering

Metering is a deterministic instrument for measuring the externally visible behavior of an agent harness. A harness is everything around a language model that decides what to do next, including the prompts, the tools, the retries, and the stopping rule. Measuring one honestly is hard, because most of what happens is invisible from the outside and easy to describe in flattering language. Metering starts from the opposite end by building one task whose correct answer is known in advance, then checking that the measurements come out right before any language model is involved.

The task is the hidden-fault world. The controller selects one of eight faults and keeps it private. A policy receives the fault identifiers and a catalogue of diagnostic tests, spends actions to narrow the possibilities, proposes a repair, asks for verification, and finishes. Because the world is deterministic and its rules are published, anyone reading a saved run can recompute exactly what the policy could have known at every step. This is what makes a result checkable rather than merely reported.

Metering does not rank agents and does not produce an overall score. It answers one narrow question, which is whether the instrument can tell a careful diagnostic policy apart from a wasteful one using exact and replayable numbers.

Full documentation is published at the [documentation site](https://muchmirul.github.io/metering/). For a copyable walkthrough in the repository, read the [Markdown usage guide](docs/usage.md). [`PLAN.md`](https://github.com/muchmirul/metering/blob/main/PLAN.md) is the normative source for scope, definitions, limitations, and acceptance criteria.

## Quick start

Metering needs Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/). The runtime package has no third-party dependencies.

```bash
git clone https://github.com/muchmirul/metering.git
cd metering
uv run python -m metering calibrate
```

That command runs the full calibration suite and finishes with the headline contrast between the two search strategies:

```text
calibration passed: runs/calibration
balanced diagnostics: 24; sequential diagnostics: 35
```

## The calibrated contrast

The three reference policies all solve the task correctly, so correctness alone cannot separate them. What separates them is what they spent. Balanced search asks questions that halve the candidate set, so every observation is worth a full bit. Sequential search checks one candidate at a time, so an early negative result removes very little.

| Policy | Correct | Diagnostics per state | Total | Bits removed | Bits per observation |
|---|---|---|---|---|---|
| Balanced search | 8 / 8 | `[3, 3, 3, 3, 3, 3, 3, 3]` | 24 | 24.0 | 1.0000 |
| Sequential search | 8 / 8 | `[1, 2, 3, 4, 5, 6, 7, 7]` | 35 | 24.0 | 0.6857 |
| Seeded random search | 8 / 8 | `[4, 4, 4, 1, 4, 4, 4, 3]` | 28 | 24.0 | 0.8571 |

Each policy removes the same 24 bits in total, because each one ends up knowing the answer in all eight states. The efficiency column is total bits divided by total observations, which is the ratio of the sums rather than the average of the per-run ratios. Averaging the ratios would give a lucky one-observation run the same weight as a seven-observation run and would overstate how efficient the suite really was.

## What a run reports

Every report carries three readings that stay in separate columns, because they answer different questions and combining them would let a cheap failure look better than an expensive success.

- **Exact correctness.** Four conditions are reported one by one. The final repair must match the hidden fault, a verification must come after that repair, the policy must finish normally, and the budget must hold. Overall success needs all four, and keeping them visible turns a failure into a diagnosis instead of an unexplained false.
- **Raw resource cost.** Diagnostic observations, repairs, verifications, and total actions are counted separately, together with whether the run ran out of budget. Metering never adds them into invented points.
- **Diagnostic information.** Eight equally likely faults carry three bits of uncertainty. The meter reports how many of those bits the delivered test results actually removed, and how many bits each observation was worth.

Verification feedback is content-free while a run is in progress. Whether a repair matched the hidden fault stays private until the offline report is built, so a policy cannot use verification as a second diagnostic oracle that no meter counts.

## The system, from high level to low level

Metering is assembled from focused modules rather than one framework with plug-in points. Each layer depends only on the layers below it, so the code reads top down and a change in how a run is measured cannot reach back and change how the run was executed.

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

The boundary in the middle is the design rule everything else follows. The controller hands the policy an immutable public instance and the observations delivered so far, and it never hands over the world object or the selected fault. Because of this, a policy cannot read the answer even by accident, and the only way it can learn anything is through actions that the trace records and the meters count.

The separation at the bottom matters just as much. Replay and the meters read files that are already written and hashed, so changing how a measurement is calculated cannot change a raw trace recorded earlier. This is what lets an old run be re-measured by newer code and still describe the same execution.

## Two paths through one run

During execution the controller and the world exchange typed values while the trace collects facts without judging them:

```text
HiddenFaultSpec.default() -> HiddenFaultWorld holding one private fault
                                      ^
                   validate and apply  |  observation and raw cost
                                      v
Controller -- public instance + history --> policy.next_action(...)
Controller <------------ one typed action -- policy.next_action(...)
    |
    +--> Event --> events.jsonl
```

Interpretation happens only after execution has ended and the files are closed:

```text
manifest.json + events.jsonl + private reference.json
                         |
                         v
               strict offline replay
                         |
                         v
       exact verifier + resource meter + information meter
                         |
                         v
                    report.json
```

Because the second path never calls the policy or the world, a report can be rebuilt on a different machine, months later, from nothing but the saved files.

## Run one hidden fault

```python
from metering import BalancedSearchPolicy, run_hidden_fault

result = run_hidden_fault(
    BalancedSearchPolicy(),
    hidden_fault_id="fault-3",
    run_dir="runs/example",
    run_id="example",
    action_budget=16,
)

print(result.succeeded)
print(result.report["resources"])
```

```text
True
{'diagnostic_observations': 3, 'repair_actions': 1, 'verification_actions': 1,
 'total_actions': 6, 'action_budget': 16, 'budget_exhaustion': False}
```

The run directory must be new or empty, because a run owns the files it writes. The `hidden_fault_id` argument sets controller-private truth and is never passed to the policy callback.

## The four artifacts

```text
runs/example/
    manifest.json     written before the run: public instance, budget, policy, commitment
    events.jsonl      written during the run: append-only canonical facts
    reference.json    written after the policy ends: hidden fault, nonce, byte bindings
    report.json       written last: correctness, resources, information, input hashes
```

The order is deliberate. The manifest commits to the hidden fault before the policy gets its first callback, and the reference reveals that fault only after the policy can no longer act on it. Replay recomputes the commitment from the revealed values, so a plausible hidden fault cannot be substituted after the fact. The nonce is what makes this work, because a bare hash of one of eight faults could be reversed by hashing all eight.

## Rebuild a report offline

```bash
uv run python -m metering report runs/example
```

Replay does not call the policy or the world. It reads the three raw files, rebuilds the controller state that must have produced them, and checks the schemas, the artifact identity, the private commitment, every transition, every recorded cost, and the exact bytes of each input. Only when all of that passes does the new report atomically replace the old one. A corrupt run therefore keeps whatever report it already had:

```text
report regeneration failed: diagnostic outcome contradicts the generated instance
```

## Run the tests

```bash
uv run --extra test pytest -q
```

The suite runs without a network connection or a model server.

## Calibration options

The default output directory is `runs/calibration`, and a non-empty directory is never overwritten. Passing `--force` replaces a directory only when it carries Metering's own marker file, so a mistyped path cannot turn calibration into a recursive delete.

```bash
uv run python -m metering calibrate --output /tmp/metering
```

Every check, whether it passed or failed, is written to `calibration.json` in that directory. A failing suite still writes the file before it exits, so the reason stays available after the terminal has scrolled away.

Show the version derived from the current Git tag:

```bash
uv run python -m metering --version
```

## Versions and compatibility

Release versions come from Git tags and [GitHub Releases](https://github.com/muchmirul/metering/releases) rather than from names embedded in the product, and [`RELEASING.md`](https://github.com/muchmirul/metering/blob/main/RELEASING.md) describes the process. The release version is recorded as provenance only. Replay compatibility is decided by the recorded controller, verifier, and meter versions plus the accepted strict schemas, because those are the parts whose behavior a replay actually depends on. World, instance, and policy declarations are recorded and checked for consistency inside each artifact set.

## What Metering deliberately leaves out

An instrument is only useful if its limits are stated as plainly as its results. These boundaries are chosen rather than pending, and they are recorded inside every artifact so a number cannot be quoted later without them.

- The harness boundary is cooperative and in process. Metering cannot stop a callback that never returns, and it cannot survive a hard process exit, a segmentation fault, or an out-of-memory kill. It provides API non-disclosure and claims nothing about hostile code.
- The information meter measures uncertainty removed by delivered results. It says nothing about whether a model understood or internally used what it was told.
- Every reading is conditional on the declared world, policy, budget, and configuration, so a result here does not describe harness quality in general.
- Hashes and commitments detect corruption and accidentally mixed artifacts. They are not signatures, and they do not defend against someone who rewrites an entire artifact set coherently.
