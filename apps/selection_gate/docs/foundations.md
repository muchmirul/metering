# Selection gate foundations

## Biological role

Mutation creates variation. Selection changes which variants contribute to the
next generation. A score without differential retention is observation, not
selection.

In this software architecture:

```text
Mutator          -> variation
Forecast Assay   -> measured phenotype evidence
Selection Gate   -> differential retention decision
Controller       -> inheritance into the next generation
```

The gate therefore implements one necessary condition of a directed-evolution-
inspired loop, but not the complete loop.

## Mathematical rule

For candidate `c`, fixed evaluation `E`, observations `x_i`, targets `y_i`, and
pre-reveal probabilities `q_c(y_i | x_i, E)`, Forecast Assay reports:

```text
L_E(c) = -(1/n) sum_i log2 q_c(y_i | x_i, E)
```

For incumbent `c_t`, challenger `c'_t`, and required improvement `delta >= 0`:

```text
Delta_t = L_E(c_t) - L_E(c'_t)
```

The gate returns:

```text
promote challenger  when Delta_t > delta
retain incumbent    otherwise
```

The inherited candidate may then be defined by an external controller as:

```text
c_(t+1) = c'_t  if promoted
c_(t+1) = c_t   otherwise
```

This is structurally a pairwise elitist `(1+1)` evolutionary strategy: one
parent, one child, and one retained candidate.

## What the rule guarantees

For finite reports on the same development evaluation, if the controller obeys
the gate, the retained candidate's verified development loss does not increase.
A promoted child exceeds the declared improvement threshold.

The guarantee is narrow. It does not imply lower future loss, cross-environment
improvement, safety, lower cost, better reasoning, or a global optimum. A strict
pairwise hill climber can also reject an intermediate regression that would be
needed to reach a better distant candidate.

## Proper scoring and leakage

Logarithmic loss is strictly proper in expectation when the candidate supplies a
complete coherent probability distribution before the target is revealed. The
Forecast Assay receives only the realized target coordinate and therefore cannot
prove normalization or precommitment. The Selection Gate cannot repair that
missing causal guarantee.

An external evaluation controller should eventually enforce:

```text
candidate commits full forecast
environment reveals target afterward
assay extracts the committed target coordinate
selection compares identical cases
```

Otherwise selection can favor leakage or forged after-the-fact probability one
rather than better prediction.

## Adaptive evaluation risk

Repeatedly selecting against the same finite evaluation makes that evaluation
part of development. Monotonic development loss can coexist with worse fresh
performance. Claims of adaptation require untouched final cases, repeated runs,
and predeclared environment analysis.

## Falsifiable implementation claim

For every accepted request, the gate:

1. recomputes both reports from their target probabilities;
2. compares exactly the same evaluation and `(observation, target)` set;
3. ignores report array order;
4. promotes finite reports only under strict `Delta > delta`;
5. applies the documented conservative infinity ordering; and
6. returns the same canonical decision for the same semantic request.

A counterexample falsifies the implementation claim.

## Research lineage

- Claude Shannon, 1948, supplies self-information.
- Gneiting and Raftery, 2007, formalize proper scoring rules including the
  logarithmic score.
- R. C. Lewontin, 1970, identifies variation, differential retention, and
  heritability as minimal selection conditions.
- G. R. Price, 1970, expresses selection through covariance and separates it
  from transmission effects.
- Hansen and Ostermeier, 2001, describe adaptation of mutation distributions in
  evolution strategies; such adaptation belongs to the external controller,
  not this gate.
- Cawley and Talbot, 2010, and reusable-holdout research motivate fresh final
  evaluation under adaptive model selection.
