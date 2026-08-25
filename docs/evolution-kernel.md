# Minimal information-guided evolution kernel

The [system foundations](foundations.md) derive the mathematical identities,
biology analogy, integrity model, design rationale, and falsifiable hypotheses
behind this composition. This document keeps the executable responsibility and
data-flow boundary concise.

Metering remains a pure information-measurement package. Repository applications
compose explicit responsibilities around it:

```text
Observer         applies observations under a declared belief model
Mutator          generates one legal child from an explicit mutation model
Candidate Runner turns one fixed genome into pre-reveal Observer forecasts
Forecast Assay   measures revealed-target probabilistic behavior
Selection Gate   verifies two reports and chooses differential retention
Controller       executes one generation and returns the selected next parent
Evolution Driver optionally repeats completed skill generations under limits
Caller           owns configuration, adapter budgets, final tests, and deployment
```

## Two loops

The epistemic loop changes what an agent knows:

```text
environment -> observation -> belief update -> next observation
```

The evolutionary loop changes which candidate is inherited:

```text
parent
  -> Mutator
  -> child
  -> Candidate Runner forecasts for parent and child
  -> Observer reveals each shared case
  -> Forecast Assay reports
  -> Selection Gate
  -> controller returns the selected next parent
  -> caller or bounded Evolution Driver may submit another generation
```

These loops may interact, but their state transitions must remain named. An
observation result is not a mutation. A mutation is not improvement. An assay
measurement is not selection. A selection response is not inheritance until a
controller explicitly returns it as the next parent.

[`apps/controller/controller.py`](../apps/controller/controller.py) executes
that one-generation boundary through documented standard-stream protocols.
Schema version 1 remains intentionally concrete: one declared probability model
over the four Observer fixtures. Schema version 2 adds content-identified skill
artifacts and caller-selected agent and evaluator commands while preserving the
same ordering and identity boundaries. Its task gate selects on explicit pass
and safety evidence; forecast surprisal remains separately named calibration
evidence. See the [agent-skill evolution protocol](agent-evolution.md).

[`tests/test_controller.py`](../tests/test_controller.py) verifies the fixture
process, [`tests/test_agent_evolution.py`](../tests/test_agent_evolution.py)
verifies the agent-skill process,
[`tests/test_self_evolution.py`](../tests/test_self_evolution.py) verifies bounded
recurrence and resume, and
[`tests/test_evolution_kernel.py`](../tests/test_evolution_kernel.py) retains the
smaller content-ID composition check.

## Minimal generation equations

```text
c'_t ~ Q_theta_t(. | c_t)

L_E(c) = -(1/n) sum_i log2 q_c(y_i | x_i, E)

Delta_t = L_E(c_t) - L_E(c'_t)          when both losses are finite

c_(t+1) = c'_t  when Delta_t > delta
c_(t+1) = c_t   otherwise
```

Schema-version-1 Mutator receives the finite support of `Q` and an explicit
draw; it does not own random-number generation. Candidate Runner supplies the concrete
`q_c` for this fixture example. Forecast Assay reports `L_E`. Selection Gate
verifies `Delta_t` and applies `delta`. The controller performs one transition,
but any update to `theta_t` remains caller-owned.
When either report is infinite, Selection Gate applies its explicit
extended-real ordering instead of subtracting infinities.

## Candidate identity binding

Mutator returns content-derived `parent.candidate_id` and `child.candidate_id`.
Forecast Assay deliberately accepts an opaque candidate string, and Selection
Gate verifies report mathematics rather than model execution. Evolution
Controller therefore preserves this binding explicitly:

```text
incumbent_report.candidate == mutator.parent.candidate_id
challenger_report.candidate == mutator.child.candidate_id
```

Those equalities are necessary but not sufficient: the controller must also run
the corresponding genomes when constructing each report. Candidate Runner
verifies the ID-to-genome formula; neither the assay nor the gate can prove
execution from an opaque label. A mismatched label is an
invalid composition even if every individual application accepts its request.

## Trusted boundary

Version 1 treats the Mutator, fixed Candidate Runner, Observer, Forecast Assay,
Selection Gate, evaluation ordering, and the controller's candidate-ID binding
as infrastructure. Candidate genomes may evolve. Later, mutation-policy
parameters may adapt. The source code that defines mutation legality should not initially
rewrite itself because doing so would change inheritance, identity, replay, and
security assumptions at once.

## Required evaluation discipline

Selection pressure exploits any shortcut in the assay. A serious controller
should bind reports to the exact Mutator candidate IDs it executed, commit
complete normalized forecasts before target reveal, compare candidates on
identical cases and budgets, keep environment-specific results separate, and
reserve fresh final cases that are not repeatedly reused for selection.

The six applications therefore remain auditable one-generation boundaries. The
source-only Evolution Driver can repeat the unchanged schema-version-2 boundary,
but installation, deployment, final evaluation, and every policy change remain
explicit caller decisions. External adapters also own sandboxing, hidden-test
isolation, model and tool settings, and token or monetary budgets they alone can
observe.

## Composition hypothesis

The engineering hypothesis is that keeping variation, forecast expression,
target reveal, assay, retention, and one-generation orchestration as strict
separate processes makes causal ordering, identity swaps, and evidence mismatch
observable without adding an agent framework to the installed Metering package.

It is falsified by any successful generation that captures a forecast after its
target reveal, loses the Mutator parent/child content binding, compares different
evidence, trusts a forged assay aggregate, or returns an unknown next parent.
The controller integration tests exercise these conditions for version 1. They
do not prove the external empirical hypothesis that repeated selection improves
fresh-data performance; that experiment remains caller-owned.
