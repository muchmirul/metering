# Metering: v0 Plan

## Status

This document defines the first implementable slice of Metering. It is intentionally smaller than the full harness-measurement vision.

The purpose of v0 is not to rank agent systems. It is to prove that a controlled interaction can produce a raw trace and that independently implemented meters can turn that trace into correct, reproducible measurements.

## The first question

v0 answers one narrow question:

> Can the instrument distinguish a careful diagnostic policy from a wasteful one using exact, replayable measurements?

If it cannot answer this correctly, adding language models, real repositories, fault injection, dashboards, or leaderboards will not help.

## Claims and non-claims

v0 may measure:

- whether a task was completed correctly;
- how many observations and actions were used;
- how much uncertainty the supplied observations removed;
- how much diagnostic information was delivered per observation.

v0 does not measure:

- whether a model understood an observation;
- private reasoning inside a model;
- universal harness quality;
- performance on real software work;
- safety under production failures;
- an overall agent score.

Every result is conditional on the declared world, policy, costs, budget, and configuration.

## Minimal experiment

The first controlled world is a hidden-fault diagnosis task.

1. The controller selects one of eight faults.
2. The harness receives the public test catalogue, but not the selected fault.
3. The harness can request diagnostic tests.
4. The harness chooses a repair.
5. The harness requests verification.
6. The harness finishes.

The eight public fault identifiers are `fault-0` through `fault-7`, with a uniform prior. Every diagnostic result is Boolean and deterministic. The catalogue contains three public bit-membership tests, which can identify any state in three balanced observations, followed by one singleton-membership test for each fault. Catalogue order is the tie-break order.

Balanced search uses the three even splits. Sequential search checks the singleton tests for `fault-0` through `fault-6` and infers `fault-7` after seven negative results rather than testing it redundantly. Its diagnostic-count vector across the ordered hidden states is therefore `[1, 2, 3, 4, 5, 6, 7, 7]`: 35 observations in total, compared with 24 for balanced search.

The complete set of eight hidden states is run during calibration, so the main reference results do not depend on sampling luck.

## Core primitives

### World

Owns the hidden state and applies actions. It exposes only observations that the harness is allowed to receive.

Required operations:

- create an instance from a versioned specification;
- return its public description;
- validate an action;
- apply a valid action;
- return an observation and raw action cost;
- expose the final reference state to the verifier, never to the harness.

### Action

A typed command produced by a harness.

v0 actions are:

- `diagnose(test_id)`
- `repair(fault_id)`
- `verify`
- `finish`

The public world description contains a fixed diagnostic-test catalogue. The harness cannot invent arbitrary tests.

A repair records the harness's current proposed fault. A later repair replaces it and makes any earlier verification stale. Verification returns only a content-free acknowledgement to the harness; whether the repair matched the hidden fault remains controller-private until the offline report is built. This prevents verification from becoming a second, unmetered diagnostic oracle.

Every returned action attempt, including an invalid one, consumes one unit of the action budget. `finish` also consumes one unit. A valid `finish` as the final budgeted action terminates normally; a non-finish action at that boundary terminates through budget exhaustion without requesting another action.

### Observation

A typed result returned after an action. Diagnostic observations contain only the result of the requested public test. Errors are protocol events, not free-form strings that meters must interpret.

### Harness

Chooses the next action from the public instance description and the observations it has received. Every canonical v0 harness must also provide a finite JSON descriptor containing its name, version, configuration, and declared seed policy; undeclared policy provenance is rejected. Reference harnesses run in process during v0.

The v0 harness is cooperative. It is not treated as hostile code, and v0 must not claim sandbox enforcement.

### Controller

Owns the run state machine. It:

- provides the public instance to the harness;
- requests one action at a time;
- validates each action;
- applies actions through the world;
- enforces the action budget;
- records canonical events;
- handles finish, invalid actions, ordinary exceptions from a returned callback, and budget exhaustion explicitly.

The controller must never silently repair malformed harness behavior.

### Trace

An append-only record of facts from a run. Interpretation does not belong in the event stream.

Canonical events use monotonic step numbers. Wall-clock timestamps may be recorded as optional metadata, but they are not part of deterministic comparisons.

Each event contains at least:

- schema version;
- run identifier;
- world and instance version;
- monotonic step number;
- event type;
- action, observation, or termination payload;
- raw resource counts relevant to that event.

Hidden reference state is stored separately from the stream available to the harness.

### Verifier

Checks exact final conditions from controller-owned state. It does not call an LLM.

The verifier reports these facts separately:

- the final selected repair matches the hidden fault;
- at least one verification occurred strictly after the final repair;
- the harness terminated by a valid `finish` action;
- the action budget was respected.

Overall task success requires all four conditions. A verification before a later repair is stale. The individual facts remain visible so a failure is not reduced to an unexplained Boolean.

### Meter

A pure offline calculation over a completed trace, the versioned world definition, and the controller-private reference record.

Changing meter code must not change the raw trace. Reports must be reproducible without rerunning the harness.

## Initial measurements

### 1. Exact correctness

Reports each verifier condition and overall task success. Correctness is never traded against low cost.

### 2. Raw resource cost

Reports separate counts for:

- diagnostic observations;
- repair actions;
- verification actions;
- total actions;
- budget exhaustion.

v0 does not combine these into invented points.

### 3. Diagnostic information exposure

Uses the known uniform prior and the materialized diagnostic outcome table to calculate:

- initial uncertainty;
- uncertainty remaining after each delivered catalogue-diagnostic result;
- realized uncertainty removed by those results;
- realized uncertainty removed per diagnostic observation.

The chosen test is treated as an intervention, not as evidence. Repair, verification, and finish events do not update the diagnostic candidate set. A repeated or non-splitting diagnostic result removes zero bits. An impossible result makes the trace invalid. A run with no diagnostic observations reports a null per-observation value rather than zero.

The natural unit is bits. This is realized posterior-entropy reduction in the declared deterministic world, not expected mutual information. The name deliberately says information was exposed or delivered. It does not claim that a future language model understood or internally used it.

Suite-level efficiency is the sum of exposed bits divided by the sum of diagnostic observations. It is not the average of the individual run ratios.

## Calibration policies

### Balanced search

Chooses diagnostic tests that divide the remaining candidates as evenly as the catalogue permits. In the eight-fault deterministic world, it should identify every fault in three diagnostic observations.

### Sequential search

Checks candidate faults in a fixed order. It is correct but usually uses more observations than balanced search.

### Seeded random search

Chooses valid diagnostic tests using a declared seed. It tests deterministic replay and provides a baseline. A single random run is not required to be worse than every careful run; comparisons use the complete declared calibration set.

The first two policies provide the main exact calibration contrast. If the information and resource meters cannot distinguish them in the expected direction, those meters are not ready.

## Run artifacts

Each run directory contains:

```text
runs/<run-id>/
    manifest.json
    events.jsonl
    reference.json
    report.json
```

- `manifest.json` records the controller-generated artifact-set identifier, an opaque salted commitment to private generated truth, implementation versions, materialized public instance, budget, policy, configuration, and seed policy.
- `events.jsonl` contains the append-only interaction and controller events.
- `reference.json` contains controller-private ground truth, the private commitment nonce, and bindings to the exact manifest and event stream. It is written only after policy execution has ended and is never provided to the harness.
- `report.json` contains verifier and meter output plus source hashes for all three raw inputs. It does not expose the private nonce.

A caller-supplied run label is not a trust boundary. Every execution receives a separate controller-generated artifact-set identifier so raw files from two executions cannot be mixed accidentally, even if their run labels are equal. Before the first policy callback, the controller commits to the complete generated-instance identity with SHA-256 and a fresh private UUID nonce. Replay checks the revealed private reference against that commitment, preventing a plausible hidden-truth substitution without making the eight-state truth guessable from the public manifest.

The SHA-256 bindings and commitment detect stale, corrupt, or accidentally mixed artifacts. They are not signatures and do not protect against a hostile party coherently rewriting an entire artifact set.

Raw schemas use exact key sets and strict JSON types. A Boolean or floating-point value is not accepted where an integer is required, and duplicate JSON object keys are invalid.

The generated instance itself is saved. A seed alone is not considered a complete reproducibility record.

## Minimal repository layout

Start with a small layout and split files only when real code requires it:

```text
metering/
    V0_PLAN.md
    pyproject.toml
    src/
        metering/
            __init__.py
            events.py
            hidden_fault.py
            runner.py
            trace.py
            policies.py
            report.py
    tests/
        test_hidden_fault.py
        test_runner.py
        test_trace_replay.py
        test_calibration.py
```

Theory should guide definitions and tests. It should not force one software module per academic field.

## Required command

From a development checkout, one command must run the complete deterministic calibration suite:

```text
uv run python -m metering calibrate
```

After the package is installed, the equivalent command is `python -m metering calibrate` or `metering calibrate`.

It runs every hidden state against the declared reference policies, writes run artifacts, rebuilds reports from saved traces, and exits unsuccessfully if calibration checks fail.

## Acceptance criteria

v0 is complete only when all of the following are true:

- The documented public callback inputs do not contain the hidden fault. This is API non-disclosure, not sandbox security.
- All eight hidden states are covered by calibration.
- Balanced search succeeds with exactly 24 diagnostic observations across the suite.
- Sequential search succeeds with the exact vector `[1, 2, 3, 4, 5, 6, 7, 7]`, or 35 observations in total.
- Suite information efficiency uses the ratio of sums.
- Seeded policies replay deterministically after controller-owned artifact identifiers are normalized.
- Invalid actions produce explicit protocol failures.
- A harness that keeps returning non-finish actions is stopped by the fixed action budget without a later callback.
- An ordinary exception raised by `next_action` produces an explicit harness-crash termination record.
- The in-process v0 does not claim to stop a callback that never returns or survive hard process exits, segmentation faults, out-of-memory termination, or interpreter failure.
- Every event has a strict schema version and a contiguous monotonic step number.
- Equal Boolean or floating-point substitutes are rejected for integer schema and count fields.
- The materialized public instance and controller-private selected state are stored separately.
- An artifact from another execution is rejected even when the caller reused the same run label.
- Reports can be deleted and regenerated from bound saved raw artifacts without invoking a policy.
- Regenerated reports match the original when the recorded implementation versions are available.
- A failed or corrupt replay does not replace an existing good report.
- Meter calculations do not affect world execution or tracing.
- The full suite runs without a model server or network access.

## Explicitly deferred

v0 does not include:

- Qwen or any other language model;
- an inference-provider abstraction;
- an external harness JSONL protocol;
- process isolation or a hostile-code sandbox;
- injected timeouts, dropped responses, duplicates, or stale state;
- browser, shell, Git, or repository tasks;
- multi-agent orchestration;
- uncertainty intervals for sampled model behavior;
- a database or dashboard;
- plugins;
- a public benchmark or leaderboard;
- an overall harness score.

These are later features, not missing v0 work.

## Development sequence after v0

### v1: external harness boundary

After at least two different in-process harnesses work, extract a small external protocol. Define its legal state transitions, request identifiers, invalid-message behavior, termination, timeout handling, and resource limits before promising compatibility.

### v2: replaceable inference engine

Add a brokered inference interface and a deterministic synthetic brain. Then add one pinned local Qwen configuration.

A model is the brain, not the harness. The harness includes context construction, prompts, memory selection, tools, retries, verification, and stopping logic.

For model-backed runs, record model and tokenizer hashes, quantization, runtime build, chat template, tool definitions, sampling settings, token limits, and complete requests and responses. A fixed seed alone does not guarantee GPU determinism.

### v3: controlled failure experiments

Add one failure mechanism at a time, beginning with ambiguous completion or lost responses. Add safe and unsafe scripted references and validate the expected behavior before testing a real model-backed harness.

### v4: additional worlds and real adapters

Add another world only when it measures something that the hidden-fault world cannot. Results remain conditional on their declared worlds and configurations.

### v5: standardized benchmark

A benchmark may be assembled only after individual measurements have stable definitions, calibration behavior, reproducible procedures, and clearly stated limitations.

## Design rules

1. Prefer one correct vertical slice over a general framework.
2. Record facts before interpreting them.
3. Keep hidden truth outside the harness boundary.
4. Keep raw resource units separate.
5. Give every measurement a precise name and a stated limitation.
6. Do not infer internal model behavior from an external trace.
7. Do not claim enforcement that the implementation does not provide.
8. Do not freeze an external protocol before multiple implementations exercise it.
9. Do not describe a world-specific result as universal harness quality.
10. Do not add a feature merely because it appears in the long-term architecture.

## Definition of the first successful brick

The first brick is successful when a reviewer can inspect a saved run, replay its report without running the policy again, and confirm that balanced diagnosis is measured as correct and less wasteful than sequential diagnosis for reasons defined by the controlled world.
