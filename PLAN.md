# Metering and Evo contract

## Purpose

This repository contains two deliberately small public packages.

`metering` measures named information-theoretic quantities from finite discrete
probability models supplied by the caller.

`evo` performs one pairwise inheritance transition:

```text
parent -> proposer -> challenger -> judge -> selected successor
```

The packages are independent. A judge may use Metering, but Evo does not require
probabilistic forecasts.

## Public Metering API

```python
from metering import (
    ProbabilityError,
    entropy,
    kl_divergence,
    mutual_information,
    self_information,
)
```

No other public Python names are supported.

For logarithm base `b > 1`:

```text
self-information:      -log_b(p)
entropy:                -sum p_i log_b(p_i)
KL divergence:           sum p_i log_b(p_i / q_i)
mutual information:      sum p(x,y) log_b(p(x,y) / (p(x)p(y)))
```

The caller supplies outcome meanings and normalized probability models.
Metering never estimates, normalizes, bins, smooths, clips, samples, or chooses a
policy.

## Public Evo API

```python
from evo import Candidate, Transition, Verdict, step
```

No other public Evo names are supported.

### Candidate

```text
Candidate(id, value)
```

`id` is a non-empty string. Identity construction and the meaning of `value`
are caller-owned.

### Verdict

```text
Verdict(selected_id, evidence)
```

`selected_id` is a non-empty string. The judge owns the evidence and selection
policy.

### Transition

```text
Transition(parent, challenger, verdict)
```

The parent and challenger IDs must differ. The verdict must select exactly one
of those IDs. `next_parent` is derived from the selected ID and is not stored as
an independent source of truth.

### Step

```text
challenger = await propose(parent)
verdict = await judge(parent, challenger)
transition = await step(parent, propose, judge)
```

The proposer and judge are asynchronous caller-supplied callables. Evo does not
retry, parallelize, persist, deploy, or repeat the transition.

## JSON command boundary

The existing `metering` command remains a strict one-request JSON adapter for the
four measurements. It is not an Evo protocol.

Bad JSON, duplicate keys, extra keys, unsupported arguments, invalid numbers,
and invalid probability models fail explicitly with exit status 2.

Evo intentionally has no installed JSON command. Transport belongs to adapters.
The Pi skill example demonstrates one external command boundary without moving
that mechanism into the core.

## Measurement history

`metering-history` stores only accepted Metering request/response pairs in one
local parent-linked ledger. It does not store candidates, verdicts, transitions,
deployments, or rollback state.

Evolution persistence remains caller-owned:

```python
transition = await step(parent, propose, judge)
store.append(transition)
```

## Examples

Examples are source-only and excluded from the wheel.

`examples/fixture_evolution` is one deterministic proposer and one judge. Its
judge folds candidate expression, active observation, log-loss measurement, and
strict pairwise selection into one example-local function.

`examples/pi_skill_evolution` evolves text skills through an external adapter.
The adapter may be backed by Pi, Prime Agent, another agent, deterministic tests,
or human review. The checked-in adapter is only a reproducible test double.

Example-specific fields and equations are not public core abstractions.

## Permanent non-goals

Neither core contains:

```text
an LLM or provider SDK
an agent loop
prompt or skill semantics
a mutation language
an evaluator framework
a workflow graph
subprocess orchestration
persistence or a database
lineage or rollback policy
deployment
budgets or stopping rules
a generic fitness score
a multi-generation loop
```

## Repository layout

```text
src/metering/
    __init__.py
    information.py
    __main__.py
    history.py
src/evo/
    __init__.py
    core.py
examples/
    fixture_evolution/
    pi_skill_evolution/
tests/
docs/
```

## Acceptance criteria

The repository is conformant when:

- all four Metering functions match their documented finite-discrete formulas;
- invalid or ambiguous probability models are rejected rather than repaired;
- Metering direct and JSON calls agree;
- measurement history records only accepted pairs and detects corruption;
- Evo exports exactly `Candidate`, `Transition`, `Verdict`, and `step`;
- Evo has no runtime dependency on Metering or any example;
- Evo rejects empty IDs, no-op candidate identity, and unknown selections;
- `next_parent` is derived from the verdict;
- both examples use the same `evo.step()` without candidate-type branches in
  the core;
- the fixture example promotes its better `v3` challenger and rejects the same
  change when it regresses on `v4`;
- the Pi skill example can replace its adapter command without changing Evo;
- the wheel contains only `metering`, `evo`, and packaging metadata;
- the full test suite and package build pass.
