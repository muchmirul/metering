# Minimal evolution kernel

The reusable self-evolution brick is one transition:

```text
parent -> propose challenger -> judge pair -> inherit selected candidate
```

```python
transition = await step(parent, propose, judge)
next_parent = transition.next_parent
```

## Objects

```text
Candidate(id, value)
Verdict(selected_id, evidence)
Transition(parent, challenger, verdict)
```

Only one selection invariant is universal:

```text
selected_id in {parent.id, challenger.id}
```

`accepted`, `promoted`, `winner`, and stored `next_parent` fields would duplicate
that fact, so the core does not contain them.

## Generality

The core does not inspect candidate values or evidence. A candidate can be a
prompt, skill directory, source patch, policy, checkpoint, population, or
mutation strategy. Evidence can contain tests, safety gates, log loss, formal
verification, simulator results, cost, or human approval.

A population does not require population machinery in the core. The population
can be the candidate value. A mutation policy can also be a candidate value,
which allows a caller to compose meta-evolution from the same transition.

## Relationship to Metering

Metering is optional instrumentation:

```text
active experiment judge -> entropy or mutual information
forecast judge          -> self-information
policy-change monitor   -> KL divergence
coding-agent judge      -> tests and safety gates, no Metering required
```

Information measurement does not imply selection. Selection does not imply
inheritance until a transition identifies the successor.

## Examples

The fixture example implements:

```text
proposer = one explicit confidence mutation
judge    = forecasts + active observations + log loss + threshold
```

The Pi skill example implements:

```text
proposer = external adapter proposes modified skill text
judge    = external adapter returns evidence and selected identity
```

Both call the same `evo.step()` with no domain branch in Evo.

## Caller-owned work

The caller owns:

```text
candidate identity construction
mutation generation
evaluation validity
hidden data and leakage prevention
persistence
repetition
budgets
rollback
deployment
stopping
```

The kernel cannot prove that a judge is unbiased or that a selected candidate
generalizes. It only makes one inheritance transition explicit and valid.
