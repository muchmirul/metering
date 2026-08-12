# Metering

Metering is a small, deterministic instrument for measuring externally visible harness behavior in a controlled hidden-fault world.

It is not a leaderboard and does not assign an overall agent score. Metering validates the measurement path before introducing a language model:

```text
controlled world -> harness actions -> raw trace -> offline verifier and meters
```

See [`PLAN.md`](https://github.com/muchmirul/metering/blob/main/PLAN.md) for the normative scope, definitions, limitations, and acceptance criteria. The static guide lives in [documentation site](https://muchmirul.github.io/metering/) and is published through GitHub Pages.

Release versions come from Git tags and [GitHub Releases](https://github.com/muchmirul/metering/releases), not from phase names embedded in the product. Source archives and packages derive their version from the release tag; see [`RELEASING.md`](https://github.com/muchmirul/metering/blob/main/RELEASING.md). Release versions are recorded as provenance. Replay requires compatible controller, verifier, and meter component versions plus accepted schemas; world, instance, and policy declarations are recorded and checked for internal consistency.

## What Metering contains

- Eight equally likely hidden faults
- A fixed public catalogue of balanced and singleton diagnostic tests
- Balanced, sequential, and seeded deterministic reference policies
- Exact final-state verification without an LLM judge
- Separate raw action counts
- Realized diagnostic information exposure in bits
- Append-only canonical JSONL events
- Offline report regeneration with artifact-set hashes and a salted private-truth commitment
- A complete calibration command

Verification feedback is content-free during a run. Whether a repair matched the hidden fault remains private until the offline report is produced, so verification cannot be used as an unmetered diagnostic oracle.

## Requirements

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/) for the development commands below

The runtime package has no third-party dependencies.

Show the version derived from the current Git tag:

```bash
uv run python -m metering --version
```

## Run the calibration

From this checkout:

```bash
uv run python -m metering calibrate
```

The default output is `runs/calibration`. Refusing to overwrite a non-empty directory is intentional. `--force` replaces only a directory carrying Metering's own calibration marker; it will not recursively delete an arbitrary directory.

To choose another location:

```bash
uv run python -m metering calibrate --output /tmp/metering
```

A successful run prints the calibrated aggregate costs:

```text
balanced diagnostics: 24; sequential diagnostics: 35
```

## Run the tests

```bash
uv run --extra test pytest -q
```

The suite runs without network access or a model server.

## Regenerate a report

Each run contains:

```text
manifest.json
events.jsonl
reference.json
report.json
```

Regenerate `report.json` solely from its three bound raw inputs:

```bash
uv run python -m metering report PATH_TO_RUN_DIRECTORY
```

Replay does not invoke the policy or world. It rejects inconsistent schemas, identities, transitions, costs, observations, provenance, private-truth commitments, or artifact bindings before atomically replacing a report. The public manifest contains only an opaque salted commitment; its nonce remains in the private reference artifact.

## Minimal Python API

```python
from metering import BalancedSearchPolicy, run_hidden_fault

result = run_hidden_fault(
    BalancedSearchPolicy(),
    hidden_fault_id="fault-3",
    run_dir="runs/example",
    run_id="example",
    action_budget=16,
)

print(result.report["correctness"])
print(result.report["resources"])
print(result.report["diagnostic_information"])
```

Run directories must be new or empty.

## Migration from development-phase names

- Construct the canonical world with `HiddenFaultSpec.default()`.
- New calibrations use `runs/calibration` and the `.metering-calibration` ownership marker.
- A directory created by an older development build is not automatically replaced by `--force`; archive or remove it explicitly.
- Existing individual run directories can still be passed to `metering report` when their recorded controller, verifier, meter, and schemas are compatible. Regenerating a full calibration produces new run labels and therefore new bound hashes.

## Measurement boundary

The harness interface is cooperative and in-process. The controller passes an immutable public instance and observation history to `next_action`; it does not pass controller-private ground truth.

This is API non-disclosure, not a security sandbox. Metering cannot stop a callback that never returns, and it cannot recover from a hard process exit, segmentation fault, out-of-memory termination, or interpreter failure. Process isolation is deliberately deferred.

The information meter measures realized uncertainty removed by delivered catalogue-diagnostic results. It does not measure whether a model understood or internally used information, and results are not universal properties of a harness.
