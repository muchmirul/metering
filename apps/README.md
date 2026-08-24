# Example applications

Applications under this directory are repository-local demonstrations. They are
not installed as part of the `metering` package.

| Application | Implemented boundary | Foundation |
|---|---|---|
| [Observer](observer/README.md) | Active observation over a finite versioned sandbox | [Bayesian identification, entropy, identity, and hypotheses](observer/docs/theory-and-hypothesis.md) |
| [Mutator](mutator/README.md) | One explicit one-locus candidate variation | [Mutation kernel, biology boundary, and hypotheses](mutator/docs/foundations.md) |
| [Candidate Runner](candidate_runner/README.md) | One fixed genome-to-Observer-forecast model | [Pushforward forecasts, entropy, and hypotheses](candidate_runner/docs/foundations.md) |
| [Forecast Assay](forecast_assay/README.md) | Target surprisal and empirical mean logarithmic loss | [Proper scoring, assay analogy, and hypotheses](forecast_assay/docs/foundations.md) |
| [Selection Gate](selection_gate/README.md) | Verified pairwise differential retention | [Pairwise selection, log-loss ratio, and hypotheses](selection_gate/docs/foundations.md) |
| [Evolution Controller](controller/README.md) | One complete, subprocess-composed generation | [One-generation equations, biology boundary, and hypotheses](controller/docs/foundations.md) |

The intended composition is documented in
[`docs/evolution-kernel.md`](../docs/evolution-kernel.md). Evolution Controller
owns candidate execution, candidate-ID binding, and one explicit retention
transition. The external caller owns repetition, budgets, mutation-policy
adaptation, and stopping. The controller carries Mutator content IDs into
Forecast Assay reports for the exact candidates Candidate Runner executed; an
opaque report label alone remains insufficient proof.

The narrow Evolution Controller now executes one generation with the fixed
Candidate Runner model. It preserves Mutator content IDs, captures both
forecasts before each Observer reveal, submits aligned Forecast Assay reports,
and applies Selection Gate. Multi-generation policy, mutation adaptation,
persistence, budgets, and stopping remain caller-owned. The complete behavior
is exercised by [`tests/test_controller.py`](../tests/test_controller.py).

The repository-wide [system foundations](../docs/foundations.md) separate
mathematical identities, tested implementation hypotheses, and unproven
empirical adaptation hypotheses. App-local foundation pages derive the exact
equations and explain why each boundary stays narrow.
