# Information-guided evolution example

The reusable kernel is the one-file [`evo`](evo.md) package:

```text
Candidate + proposer + judge -> Transition -> next_parent
```

The repository applications are one concrete implementation of those caller
roles. They demonstrate a deterministic fixture-backed generation; they do not
define the general evolution API.

## Concrete mapping

```text
proposer
    Mutator

judge
    Candidate Runner
    + Observer
    + Forecast Assay
    + Selection Gate

composition adapter
    Evolution Controller

optional measurement
    Metering
```

The Controller currently obtains canonical parent and challenger identities from
Mutator, captures both candidates' forecasts before each Observer reveal,
constructs aligned Forecast Assay reports, asks Selection Gate for a verdict,
and returns the selected value as `next_parent`.

A smaller or different system can replace all six applications with two plain
callables:

```python
transition = step(parent, propose, judge)
```

## Two independent loops

The epistemic loop changes what an evaluator knows:

```text
environment -> observation -> belief update -> next observation
```

The evolutionary loop changes what is inherited:

```text
parent -> challenger -> evidence -> verdict -> next parent
```

Observer is useful when a judge needs active information acquisition. It is not
a required component of self-evolution.

## Fixture equations

The checked-in example uses a caller-declared mutation event

```text
c'_t ~ Q_theta_t(. | c_t)
```

and empirical mean target surprisal

```text
L_E(c) = -(1/n) sum_i log2 q_c(y_i | x_i, E)
```

Selection Gate computes, for finite reports,

```text
Delta_t = L_E(c_t) - L_E(c'_t)
```

and selects the challenger only when

```text
Delta_t > delta
```

Those equations belong to this log-loss judge. Another judge may use tests,
formal verification, safety gates, human review, or simulator outcomes without
changing `evo`.

## Identity boundary

`evo` accepts candidate IDs; it does not invent their hashing scheme. The fixture
example uses Mutator content IDs and Candidate Runner independently verifies the
ID-to-genome binding. A Pi adapter may instead hash a canonical skill directory,
prompt bundle, or agent configuration.

## Trust boundary

The core guarantees only that a transition has two distinct candidate IDs and
selects one of them. It does not prove that:

```text
the proposer produced a useful mutation
the judge used hidden or unbiased evidence
the candidate was executed faithfully
the selected candidate generalizes
the transition was persisted or deployed
```

Those claims belong to adapters and experiments.
