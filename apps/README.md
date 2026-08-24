# Example applications

Applications under this directory are repository-local demonstrations. They are
not installed as part of the `metering` package.

| Application | Implemented boundary |
|---|---|
| [Observer](observer/README.md) | Active observation over a finite versioned sandbox |
| [Mutator](mutator/README.md) | One explicit one-locus candidate variation |
| [Candidate Runner](candidate_runner/README.md) | One fixed genome-to-Observer-forecast model |
| [Forecast Assay](forecast_assay/README.md) | Target surprisal and empirical mean logarithmic loss |
| [Selection Gate](selection_gate/README.md) | Verified pairwise differential retention |
| [Evolution Controller](controller/README.md) | One complete, subprocess-composed generation |

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
