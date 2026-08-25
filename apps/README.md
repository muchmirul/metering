# Example applications

Applications under this directory are repository-local demonstrations. They are
not installed as part of the `metering` package.

| Application | Implemented boundary | Foundation |
|---|---|---|
| [Observer](observer/README.md) | Finite sandbox observation or trusted post-run task evaluation | [Bayesian identification, entropy, identity, and hypotheses](observer/docs/theory-and-hypothesis.md) |
| [Mutator](mutator/README.md) | One explicit locus variation or one staged skill-artifact binding | [Mutation kernel, biology boundary, and hypotheses](mutator/docs/foundations.md) |
| [Candidate Runner](candidate_runner/README.md) | Fixed fixture forecast or external-agent adapter invocation | [Pushforward forecasts, entropy, and hypotheses](candidate_runner/docs/foundations.md) |
| [Forecast Assay](forecast_assay/README.md) | Forecast calibration plus separately named task and safety evidence | [Proper scoring, assay analogy, and hypotheses](forecast_assay/docs/foundations.md) |
| [Selection Gate](selection_gate/README.md) | Verified forecast or task/safety pairwise retention | [Pairwise selection, log-loss ratio, and hypotheses](selection_gate/docs/foundations.md) |
| [Evolution Controller](controller/README.md) | One complete fixture or agent-skill generation | [One-generation equations, biology boundary, and hypotheses](controller/docs/foundations.md) |

The intended composition is documented in
[`docs/evolution-kernel.md`](../docs/evolution-kernel.md). Evolution Controller
owns candidate execution, candidate-ID binding, and one explicit retention
transition. The external caller owns repetition, budgets, mutation-policy
adaptation, and stopping. The controller carries Mutator content IDs into
Forecast Assay reports for the exact candidates Candidate Runner executed; an
opaque report label alone remains insufficient proof.

Schema version 1 executes one generation with the fixed Candidate Runner model.
It preserves Mutator content IDs, captures both forecasts before each Observer
reveal, submits aligned Forecast Assay reports, and applies Selection Gate.

Schema version 2 reuses all six process boundaries for one agent-skill
generation. Mutator binds normalized default-agent or skill-directory artifacts;
Candidate Runner invokes an external Pi, Prime Agent, or other adapter; Observer
invokes a separate trusted evaluator after both submissions exist; Forecast
Assay reports task, safety, and Metering forecast evidence; Selection Gate
applies an explicit pass-count and safety policy; and Controller returns one
selected artifact. See the [agent-skill protocol](../docs/agent-evolution.md)
and [`tests/test_agent_evolution.py`](../tests/test_agent_evolution.py).

Shared source support is deliberately narrow. `agent_protocol.py` owns schema
version 2 artifact and wire validation; `stdio_connector.py` owns the common
canonical JSON, one-shot/JSONL, and subprocess mechanics used by the composable
stdin applications. Application modules still own schemas, mathematics,
ordering, and error policy. Observer's independently copyable fixture protocol
and external adapter examples remain self-contained where sharing would create
the wrong dependency. This removes copied mechanics without turning the six
boundaries into one framework.

Multi-generation policy, proposal generation, adapter isolation, persistence,
installation, budgets beyond the declared timeout, and stopping remain
caller-owned. The fixture behavior is exercised by
[`tests/test_controller.py`](../tests/test_controller.py).

The repository-wide [system foundations](../docs/foundations.md) separate
mathematical identities, tested implementation hypotheses, and unproven
empirical adaptation hypotheses. App-local foundation pages derive the exact
equations and explain why each boundary stays narrow.
