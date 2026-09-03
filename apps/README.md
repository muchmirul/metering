# Source applications

`apps/` contains repository-local control-plane applications. They are included
in the source archive but excluded from the installed `metering` wheel.

The installed package remains limited to four information measures, strict JSON,
and opt-in measurement history. Applications own evolution, evidence,
sandboxing, and recurrence.

## One-generation boundaries

| Application | Owns |
|---|---|
| [Mutator](mutator/README.md) | one legal child proposal |
| [Candidate Runner](candidate_runner/README.md) | candidate execution and forecast capture |
| [Observer](observer/README.md) | post-submission reveal or trusted evaluation |
| [Forecast Assay](forecast_assay/README.md) | named forecast, task, and safety evidence |
| [Selection Gate](selection_gate/README.md) | one verified parent/child retention decision |
| [Controller](controller/README.md) | ordering and authentication of one generation |

These remain separate authority boundaries. Controller does not allocate future
parents, and no stage creates a generic fitness score.

## Recurrence and concrete agents

| Application | Owns |
|---|---|
| [Evolution Driver](evolution_driver/README.md) | bounded single-lineage recurrence |
| [Population](population/README.md) | archive membership, Pareto retention, and exact allocation |
| [Population Driver](population_driver/README.md) | bounded multi-candidate recurrence |
| [Evolutionary Harness](harness/README.md) | typed Level-2 harness execution and sealing |
| [Coding Agent](coding_agent/README.md) | Level-1 immutable solution evolution and final patch |

Population's SQLite database is only a rebuildable query projection. Git,
canonical JSONL, exact draws, and immutable receipts remain authoritative.

## Shared source mechanics

- `agent_protocol.py` validates shared agent-artifact envelopes.
- `_support/wire.py` owns strict and canonical JSON mechanics.
- `_support/process.py` owns bounded subprocess execution and cleanup.
- `_support/stdio.py` owns one-shot and JSONL command boundaries.
- `_support/journal.py` owns hash-linked journal mechanics.
- `_support/durable.py` owns atomic writes and directory durability.

Applications import these focused owners directly. Provider-specific Pi and
Prime Agent translation lives only under
[`connectors/fixed/`](../connectors/fixed/README.md). Generic Git candidate
mechanics live under [`artifacts/git/`](../artifacts/git/README.md).

## Coding-agent documentation

Start with the dedicated [coding-agent guide](../docs/coding-agent/README.md),
then read its [simple architecture](../docs/coding-agent/how-it-works.md),
[workflow](../docs/coding-agent/workflow.md),
[operations](../docs/coding-agent/operations.md),
[task profile](../docs/coding-agent/task-profile.md), and
[security architecture](../docs/coding-agent/architecture.md).

For the wider dependency and authority rules, see the
[source architecture](../docs/source-architecture.md) and
[evolution kernel](../docs/evolution-kernel.md).
