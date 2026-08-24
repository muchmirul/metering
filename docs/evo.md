# Evo: the minimal transition kernel

`evo` is the reusable self-evolution brick in this repository.

It knows only one relationship:

```text
parent -> propose challenger -> judge pair -> inherit selected candidate
```

The complete public API is:

```python
from evo import Candidate, Transition, Verdict, step
```

## Example

```python
from evo import Candidate, Verdict, step

parent = Candidate("prompt-v1", "Answer directly.")


def propose(current):
    return Candidate("prompt-v2", current.value + " Verify factual claims.")


def judge(incumbent, challenger):
    evidence = {
        "incumbent_passed": 7,
        "challenger_passed": 9,
    }
    selected = challenger.id if evidence["challenger_passed"] > 7 else incumbent.id
    return Verdict(selected, evidence)


transition = step(parent, propose, judge)
print(transition.next_parent)
```

## Invariants

The core enforces only universal pairwise-transition invariants:

```text
candidate IDs are non-empty strings
parent ID != challenger ID
selected ID is either parent ID or challenger ID
```

`next_parent` is derived from the verdict. The transition does not duplicate the
same fact as `accepted`, `winner`, `promoted`, and `next_parent` fields.

## Caller-owned semantics

The core does not know what a candidate value means. It may be:

```text
a prompt
a Pi skill
a source patch
a planner policy
a model checkpoint
a population
a mutation policy
```

The core does not know what evidence means. It may contain:

```text
unit-test output
hidden benchmark results
safety checks
logarithmic loss
latency and cost
human approval
simulator results
```

The proposer owns variation. The judge owns evaluation and selection policy.
The caller owns identity construction, persistence, repetition, budgets,
rollback, deployment, and stopping.

## Relationship to Metering

`evo` does not depend on `metering`. A judge may use Metering's named measures,
but self-evolution is not restricted to probabilistic forecasts.

Examples:

```text
active experiment judge -> entropy or mutual information
forecast judge          -> self-information
policy-change monitor   -> KL divergence
coding-agent judge      -> tests and safety gates, with no information measure
```

This keeps both cores small:

```text
metering = optional instrumentation
evo      = one inheritance transition
```

## Deliberately absent

`evo` has no JSON protocol, filesystem access, subprocess management, network
access, model adapter, mutation language, evaluator, database, event bus,
plugin registry, lineage store, or autonomous loop.

The repository applications remain concrete reference implementations. They are
not required by `evo.step()`.
