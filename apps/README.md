# Example applications

Applications under this directory are repository-local demonstrations. They are
not installed as part of the `metering` package.

```text
observer/         active observation over a finite versioned sandbox
forecast_assay/   target surprisal and empirical mean logarithmic loss
mutator/          one explicit one-locus candidate variation
selection_gate/   verified pairwise differential retention
```

The intended composition is documented in
[`docs/evolution-kernel.md`](../docs/evolution-kernel.md). An external controller
owns execution, inheritance, repetition, budgets, mutation-policy adaptation,
and stopping.
