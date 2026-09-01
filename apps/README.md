# Example applications

Applications under this directory are repository-local demonstrations. They are
not installed as part of the `metering` package.

| Application | Implemented boundary | Foundation |
|---|---|---|
| [Observer](observer/README.md) | Finite sandbox observation or trusted post-run task evaluation | [Bayesian identification, entropy, identity, and hypotheses](observer/docs/theory-and-hypothesis.md) |
| [Mutator](mutator/README.md) | One explicit locus variation, staged skill binding, or strict proposer invocation | [Mutation kernel, biology boundary, and hypotheses](mutator/docs/foundations.md) |
| [Candidate Runner](candidate_runner/README.md) | Fixed fixture forecast or external-agent adapter invocation | [Pushforward forecasts, entropy, and hypotheses](candidate_runner/docs/foundations.md) |
| [Forecast Assay](forecast_assay/README.md) | Forecast calibration plus separately named task and safety evidence | [Proper scoring, assay analogy, and hypotheses](forecast_assay/docs/foundations.md) |
| [Selection Gate](selection_gate/README.md) | Verified forecast or task/safety pairwise retention | [Pairwise selection, log-loss ratio, and hypotheses](selection_gate/docs/foundations.md) |
| [Evolution Controller](controller/README.md) | One complete fixture or agent-artifact generation | [One-generation equations, biology boundary, and hypotheses](controller/docs/foundations.md) |

Three source-only outer controls compose those stages without becoming
additional semantic stages:

- [Evolution Driver](evolution_driver/README.md) repeats one selected head under
  explicit limits.
- [Population Archive](population/README.md) records multiple candidate/run
  identities, rebuilds a derived SQLite index, retains a development-only Pareto
  archive, allocates a parent from an exact draw, and performs typed skill-file
  recombination. It does not run an agent or replace Controller.
- [Population Driver](population_driver/README.md) performs bounded Git-code
  recurrence across Population allocation and one-generation Controller calls.
  It uses immutable receipts and an interruption-safe round intent, and never
  reads SQLite or final evidence into search.

The intended composition is documented in
[`docs/evolution-kernel.md`](../docs/evolution-kernel.md). Evolution Controller
owns candidate execution, candidate-ID binding, and one explicit retention
transition. An external caller, the optional single-head Evolution Driver, or
the bounded Population Driver owns repetition and stopping; adapters own physical resource
budgets. The controller carries
Mutator content IDs into
Forecast Assay reports for the exact candidates Candidate Runner executed; an
opaque report label alone remains insufficient proof.

Schema version 1 executes one generation with the fixed Candidate Runner model.
It preserves Mutator content IDs, captures both forecasts before each Observer
reveal, submits aligned Forecast Assay reports, and applies Selection Gate.

Schema version 2 reuses all six process boundaries for one agent-artifact
generation. Mutator binds normalized artifacts supplied directly or invokes one
strict proposer for a complete replacement `SKILL.md`; Candidate Runner invokes
a fixed Pi, Prime Agent, or other reviewed connector; Observer
invokes a separate trusted evaluator after both submissions exist; Forecast
Assay reports task, safety, and Metering forecast evidence; Selection Gate
applies an explicit pass-count and safety policy; and Controller returns one
selected artifact. See the [agent-artifact protocol](../docs/agent-evolution.md)
and [`tests/test_agent_evolution.py`](../tests/test_agent_evolution.py).

Shared source support is deliberately narrow. `agent_protocol.py` owns schema
version 2 artifact and wire validation; `stdio_connector.py` owns the common
canonical JSON, one-shot/JSONL, and subprocess mechanics used by the composable
stdin applications. Concrete Pi and Prime Agent CLI translations live under
[`connectors/fixed/`](../connectors/fixed/README.md), outside every application
owner. Application modules still own schemas, mathematics, ordering, and error
policy. Population Archive reuses only normalized artifact and canonical-JSON
helpers; its ledger, evidence, archive, allocation, and index schemas remain
local. Observer's independently copyable fixture protocol remains self-contained
where sharing would create the wrong dependency. Observer's task evaluator and
Controller's schema-v2 orchestration are separate internal modules behind the
unchanged commands. This keeps unrelated workflows readable without turning the
six boundaries into one framework.

[`evolution_driver/evolver.py`](evolution_driver/README.md) is an outer wrapper,
not a seventh semantic stage. It repeats only completed schema-v2 generations,
keeps a hash-linked local ledger, and stops at explicit limits. Proposal is still
Mutator-owned, retention is still Selection-Gate-owned, and installation remains
caller-owned. Fixture behavior is exercised by
[`tests/test_controller.py`](../tests/test_controller.py); bounded recurrence is
exercised by [`tests/test_self_evolution.py`](../tests/test_self_evolution.py).
The driver's constructed Signal Relay command adds a real-Pi acceptance path
with final cases kept outside retention; its complete fake-Pi regression is
[`tests/test_signal_relay_acceptance.py`](../tests/test_signal_relay_acceptance.py).

[`population_driver/population_driver.py`](population_driver/README.md) is the
multi-candidate outer wrapper. It starts with the seed and then uses each exact
Population allocation as Controller's next Git parent, records matched
incumbent/challenger reports as Population replicates, and refreshes the Pareto
archive. Its global round, proposal-call, timeout-reservation, and resource
bounds include explicit retry approval; its canonical receipts and ledgers are
covered by [`tests/test_population_driver.py`](../tests/test_population_driver.py).

The external [Git artifact bridge](../artifacts/git/README.md) demonstrates that
the same boundaries can retain immutable adapter-source commits and external
model-output receipts. It is candidate plumbing, not another semantic stage or
an installed Metering feature. Population Archive may index those descriptors,
but resolution, execution, and external-output verification remain in the Git
bridge and caller sandbox.

The repository-wide [system foundations](../docs/foundations.md) separate
mathematical identities, tested implementation hypotheses, and unproven
empirical adaptation hypotheses. App-local foundation pages derive the exact
equations and explain why each boundary stays narrow.
