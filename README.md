# Metering

Metering contains two small, independent cores for auditable agent improvement:

```text
metering    measure a caller-declared finite probability model
evo         turn one candidate into one evidence-backed successor
```

Neither package runs an agent, chooses a mutation, invents an evaluator, stores a
lineage, or repeats generations.

## Install

Python 3.11 or newer is required. The runtime has no dependencies.

```bash
uv sync --extra test
```

## Information measurement

The `metering` API exposes four named functions:

```python
from metering import entropy, kl_divergence, mutual_information, self_information

assert self_information(0.125) == 3.0
assert entropy([0.5, 0.5]) == 1.0
```

Inputs must already be normalized probability models. Metering validates them
and returns a number. It does not estimate, normalize, smooth, interpret, or act.

The one-request JSON command remains available for language-independent use:

```bash
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering
```

## Evolution transition

The complete `evo` API is:

```python
from evo import Candidate, Transition, Verdict, step
```

`step` knows one relationship:

```text
parent -> propose challenger -> judge pair -> inherit selected candidate
```

```python
import asyncio

from evo import Candidate, Verdict, step


async def main():
    parent = Candidate("prompt-v1", "Answer directly.")

    async def propose(current):
        return Candidate(
            "prompt-v2",
            current.value + " Verify factual claims.",
        )

    async def judge(incumbent, challenger):
        evidence = {"parent_passed": 7, "challenger_passed": 9}
        return Verdict(challenger.id, evidence)

    transition = await step(parent, propose, judge)
    assert transition.next_parent is transition.challenger


asyncio.run(main())
```

The core enforces only universal invariants:

```text
candidate IDs are non-empty strings
parent and challenger IDs differ
selected ID is the parent or challenger ID
```

Candidate values and evidence are caller-owned. They may represent prompts,
Pi skills, source patches, policies, checkpoints, populations, test reports,
safety scans, simulator results, or human approval.

## Examples

Two materially different examples use the same `evo.step()`:

```text
examples/fixture_evolution/
    a deterministic information-guided fixture judge

examples/pi_skill_evolution/
    a Pi/Prime-compatible external skill proposer-and-judge boundary
```

Run the fixture example:

```bash
uv run python examples/fixture_evolution/main.py --active v3
```

Run the skill example with its deterministic adapter test double:

```bash
uv run python examples/pi_skill_evolution/main.py \
  --skill examples/pi_skill_evolution/SKILL.md \
  --adapter "uv run python examples/pi_skill_evolution/demo_adapter.py"
```

A real Pi or Prime Agent integration replaces only the adapter command. The Evo
core remains unchanged.

## Measurement history

`metering-history` is an explicit optional ledger for accepted Metering
request/response pairs:

```bash
history_dir="$(mktemp -d)"
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering-history record "$history_dir"
uv run metering-history verify "$history_dir"
```

It is not an evolution lineage. A caller may persist `Transition` records in any
store it chooses.

## Repository layout

```text
src/metering/                four information measures, JSON CLI, pair history
src/evo/                     one pairwise transition
examples/fixture_evolution/  one concrete information-guided judge
examples/pi_skill_evolution/ one external skill adapter example
tests/                       core and example tests
docs/                        contracts and theory
```

## Non-goals

There is no agent runtime, model SDK, workflow engine, plugin registry, database,
HTTP service, generic fitness score, deployment system, rollback service, or
autonomous loop.

## Development

```bash
uv run --extra test pytest -q
uv build
```

[`PLAN.md`](PLAN.md) is the normative contract. [`docs/README.md`](docs/README.md)
indexes the explanatory documents.
