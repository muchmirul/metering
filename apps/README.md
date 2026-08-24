# Example applications

Applications under this directory are concrete repository-local demonstrations.
They are not the reusable evolution core and are not installed as application
commands.

The minimal generalized boundary is the one-file [`evo`](../docs/evo.md)
package:

```text
parent + proposer + judge -> transition -> next_parent
```

The current applications map onto that boundary as follows:

| Application | Concrete role | Foundation |
|---|---|---|
| [Mutator](mutator/README.md) | One fixture proposer | [Mutation kernel, biology boundary, and hypotheses](mutator/docs/foundations.md) |
| [Candidate Runner](candidate_runner/README.md) | Fixture candidate expression inside the judge | [Pushforward forecasts, entropy, and hypotheses](candidate_runner/docs/foundations.md) |
| [Observer](observer/README.md) | Optional active evidence acquisition inside the judge | [Bayesian identification, entropy, identity, and hypotheses](observer/docs/theory-and-hypothesis.md) |
| [Forecast Assay](forecast_assay/README.md) | One log-loss evaluator inside the judge | [Proper scoring, assay analogy, and hypotheses](forecast_assay/docs/foundations.md) |
| [Selection Gate](selection_gate/README.md) | One strict log-loss judge policy | [Pairwise selection, log-loss ratio, and hypotheses](selection_gate/docs/foundations.md) |
| [Evolution Controller](controller/README.md) | Fixture-specific composition adapter | [One-generation equations, biology boundary, and hypotheses](controller/docs/foundations.md) |

The complete fixture composition is documented in
[`docs/evolution-kernel.md`](../docs/evolution-kernel.md). It preserves Mutator
content IDs, captures both forecasts before reveal, submits aligned reports, and
applies Selection Gate.

The fixture Controller still runs only one generation. Repetition,
mutation-policy adaptation, persistence, budgets, and stopping remain
caller-owned. A different system may replace all six applications with two
plain callables passed to `evo.step()`.

The repository-wide [system foundations](../docs/foundations.md) separate
mathematical identities, tested implementation hypotheses, and unproven
empirical adaptation hypotheses.
