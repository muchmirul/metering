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

The [Evolutionary Harness](harness/README.md) is a concrete typed
`git-candidate-v1` phenotype and reference composition, not another semantic
stage. It supplies a provider-neutral recursive action loop, isolated IPython
kernel ABI, OCI/resource profile, immutable receipts, protected final assay, and
Pi/Prime Agent translations while reusing the owners above.

The [Darwinian Coding Agent](coding_agent/README.md) composes that typed harness
with an archive-in/archive-out solution workspace. It evolves immutable solution
commits under caller-owned development and protected-final argv checks, runs
each check in a fresh OCI kernel, applies a deterministic capability-first final
allocation, emits a selected patch, and verifies the entire sealed run offline.
Its separate Level-2 mode evolves the nine harness loci on fixed coding assays
before the selected harness is supplied to Level 1. It neither modifies the
source repository nor installs the result.

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
version 2 artifact validation. `apps/_support/` owns only byte-identical wire,
process, stdio, journal, lock/checkpoint, and fsync mechanics;
`stdio_connector.py` preserves its historical application-facing API over those
small operations. Concrete Pi and Prime Agent CLI translations live under
[`connectors/fixed/`](../connectors/fixed/README.md), outside every application
owner. Application modules still own schemas, mathematics, ordering, and error
policy. Population and Controller expose explicit public owner contracts rather
than requiring outer controls to import private policy or state helpers.
Observer's independently copyable fixture protocol remains self-contained where
sharing would create the wrong dependency. Schema-v1 fixture and schema-v2 agent
implementations live in separate modules behind unchanged thin dispatchers. This
keeps unrelated workflows readable without turning the six boundaries into one
framework. See the [source-only architecture](../docs/source-architecture.md).

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
The executable-Git Darwinian recurrence—subtraction seed, retained addition
mutation, rejected multiplication regression—is covered by
[`tests/test_darwinian_code_evolution.py`](../tests/test_darwinian_code_evolution.py).
The repository-complete typed-harness recurrence, including kernel lifecycle,
recursive subagents, resource receipts, protected final sealing, and offline
verification, is covered by
[`tests/test_harness_evolution.py`](../tests/test_harness_evolution.py).
The two-level coding composition, immutable solution branches, independent
fresh-container checks, capability-first final selection, selected patch, and
SQLite-free replay are covered by
[`tests/test_coding_agent.py`](../tests/test_coding_agent.py).

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
