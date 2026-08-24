# Minimal information-guided evolution kernel

Metering remains a pure information-measurement package. Repository applications
compose explicit responsibilities around it:

```text
Observer       chooses or applies observations under a declared belief model
Mutator        generates one legal child from an explicit mutation model
Forecast Assay measures pre-reveal probabilistic behavior
Selection Gate verifies two reports and chooses differential retention
Controller     owns inheritance, repetition, budgets, and stopping
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
  -> run parent and child on identical declared cases
  -> Forecast Assay reports
  -> Selection Gate
  -> controller retains parent or promotes child
  -> next generation
```

These loops may interact, but their state transitions must remain named. An
observation result is not a mutation. A mutation is not improvement. An assay
measurement is not selection. A selection response is not inheritance until a
controller advances the parent.

## Minimal generation equations

```text
c'_t ~ Q_theta_t(. | c_t)

L_E(c) = -(1/n) sum_i log2 q_c(y_i | x_i, E)

Delta_t = L_E(c_t) - L_E(c'_t)

c_(t+1) = c'_t  when Delta_t > delta
c_(t+1) = c_t   otherwise
```

The current Mutator receives the finite support of `Q` and an explicit draw; it
does not own random-number generation. Forecast Assay reports `L_E`. Selection
Gate verifies `Delta_t` and applies `delta`. A future controller may update
`theta_t`, but that policy update should remain outside all three applications.

## Candidate identity binding

Mutator returns content-derived `parent.candidate_id` and `child.candidate_id`.
Forecast Assay deliberately accepts an opaque candidate string, and Selection
Gate verifies report mathematics rather than model execution. The external
controller must therefore preserve this binding explicitly:

```text
incumbent_report.candidate == mutator.parent.candidate_id
challenger_report.candidate == mutator.child.candidate_id
```

Those equalities are necessary but not sufficient: the controller must also run
the corresponding genomes when constructing each report. Neither the assay nor
the gate can prove execution from an opaque label. A mismatched label is an
invalid composition even if every individual application accepts its request.

## Trusted boundary

Version 1 treats the Mutator implementation, Forecast Assay, Selection Gate,
evaluation ordering, and the controller's candidate-ID binding as
infrastructure. Candidate genomes may evolve. Later, mutation-policy parameters
may adapt. The source code that defines mutation legality should not initially
rewrite itself because doing so would change inheritance, identity, replay, and
security assumptions at once.

## Required evaluation discipline

Selection pressure exploits any shortcut in the assay. A serious controller
should bind reports to the exact Mutator candidate IDs it executed, commit
complete normalized forecasts before target reveal, compare candidates on
identical cases and budgets, keep environment-specific results separate, and
reserve fresh final cases that are not repeatedly reused for selection.

The four applications are therefore components of an auditable evolutionary
kernel, not a claim that the repository already contains an autonomous
self-evolving agent.
