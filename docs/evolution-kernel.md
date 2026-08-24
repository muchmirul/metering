# Minimal information-guided evolution kernel

Metering remains a pure information-measurement package. Repository applications
compose explicit responsibilities around it:

```text
Observer         applies observations under a declared belief model
Mutator          generates one legal child from an explicit mutation model
Candidate Runner turns one fixed genome into pre-reveal Observer forecasts
Forecast Assay   measures revealed-target probabilistic behavior
Selection Gate   verifies two reports and chooses differential retention
Controller       executes one generation and returns the selected next parent
Caller           owns repetition, budgets, policy adaptation, and stopping
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
  -> caller may submit another generation
```

These loops may interact, but their state transitions must remain named. An
observation result is not a mutation. A mutation is not improvement. An assay
measurement is not selection. A selection response is not inheritance until a
controller explicitly returns it as the next parent.

[`apps/controller/controller.py`](../apps/controller/controller.py) now executes
that one-generation boundary through the applications' documented
standard-stream protocols. Its Candidate Runner is intentionally concrete: one
declared probability model over the four Observer fixtures, not an arbitrary
model adapter. [`tests/test_controller.py`](../tests/test_controller.py) verifies the
complete process. The older
[`tests/test_evolution_kernel.py`](../tests/test_evolution_kernel.py) retains the
smaller content-ID composition check.

## Minimal generation equations

```text
c'_t ~ Q_theta_t(. | c_t)

L_E(c) = -(1/n) sum_i log2 q_c(y_i | x_i, E)

Delta_t = L_E(c_t) - L_E(c'_t)

c_(t+1) = c'_t  when Delta_t > delta
c_(t+1) = c_t   otherwise
```

The current Mutator receives the finite support of `Q` and an explicit draw; it
does not own random-number generation. Candidate Runner supplies the concrete
`q_c` for this fixture example. Forecast Assay reports `L_E`. Selection Gate
verifies `Delta_t` and applies `delta`. The controller performs one transition,
but any update to `theta_t` remains caller-owned.

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

The six applications therefore form one auditable generation example, not an
autonomous self-evolving agent. Repetition and every policy update remain an
explicit caller decision.
