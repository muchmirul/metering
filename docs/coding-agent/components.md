# Agentvolve component map

**Agentvolve** is the user-facing name for Metering's source-only two-level
coding evolution workflow. It evolves a coding harness, freezes that harness,
then evolves immutable solution commits under independent evaluation.

The existing implementation path `apps/coding_agent/`, documentation path
`docs/coding-agent/`, `/evolve-*` commands, `darwinian_coding` tool name, and
`darwinian-coding-*` JSON identifiers remain unchanged compatibility contracts.
They identify existing code and run artifacts; they are not alternative product
names.

## End-to-end stack

```text
Operator
  task profile, writable paths, budgets, development checks, final-profile hash
       |
       v
Pi project extension and fixed connectors
  Agentvolve commands, isolated model transport, no selection authority
       |
       +---------------------------+
       |                           |
       v                           v
Level 2: harness evolution     Level 1: solution evolution
  nine typed policy loci         approved repository files
       |                           |
       +------------+--------------+
                    v
             fixed local model
       Qwen weights served by llama.cpp
       through Pi's provider interface
                    |
                    v
       Docker-isolated persistent IPython kernel
       bounded execute/delegate/finish and workspace helpers
                    |
                    v
  Controller -> independent evaluator -> Population archive/allocation
                    |
                    v
       protected final assay -> selected commit and patch
```

Only validated Git artifacts are inherited. Model weights, Pi sessions,
transcripts, IPython namespaces, temporary files, evaluator state, and SQLite
rows are not heredity.

## Model and agent layer

| Component | Agentvolve role | What it does not own |
|---|---|---|
| **Qwen or another fixed model** | Produces one mutation proposal or one bounded harness action from the supplied prompt and context. The same fixed weights can be used for harness mutation and coding actions in separate stateless calls. | Candidate retention, evaluator results, protected-final access, Git identity, or deployment. |
| **llama.cpp** | Serves the local model behind an OpenAI-compatible provider endpoint. It performs tokenization, sampling, prompt evaluation, and generation. | Evolution, task scoring, parent selection, or inherited memory. |
| **Pi** | Provides the operator UI and translates fixed requests to model calls. Top-level Pi exposes `/evolve-harness` and `/evolve-code`; nested calls use isolated configuration and disable sessions, skills, extensions, prompt templates, context files, and provider tools. | Sandbox enforcement, evaluator authority, Population authority, or automatic installation. |
| **Fixed Pi connector** | Pins the selected provider/model/reasoning names, verifies the Pi version, translates strict JSON model actions, and rejects malformed output. | General provider discovery or silent fallback to another model. |

The repository is provider-neutral at the application boundary. Pi and Qwen are
one concrete stack, not requirements of the Controller or Population schemas.
Prime Agent is another implemented connector.

### Current local configuration

The default local manifest at
`~/.config/metering/harness/runtime.pi.local.json` currently identifies:

```text
Pi implementation: 0.84.4
provider:          llamacpp
model alias:       local
reasoning:         medium
kernel:            digest-pinned OCI image
```

The local Pi model catalog labels that alias as a Qwen3.8-27B Q4_K_M model with
a Q4_0 MTP draft model. The Agentvolve manifest currently binds the alias, not
the GGUF hashes, llama.cpp build, server flags, chat template, or full sampler
configuration. A controlled empirical claim must additionally pin those values
outside the candidate and record them with the run.

## Execution layer

| Component | Agentvolve role | Lifetime and boundary |
|---|---|---|
| **Evolutionary Harness** (`apps/harness/`) | A typed nine-locus policy controlling system prompt, context, compaction, tools, subagents, IPython bootstrap, snapshots, dependency lock, and entry point. | Level 2 may mutate one complete locus per child. The selected descriptor is frozen before Level 1. |
| **IPython kernel** | Executes bounded Python cells, calculations, and fixed coding-workspace helper calls. It supports supervised snapshots and restart recovery. | Persistent only within one candidate run. Its namespace is discarded and never inherited. |
| **Docker and cgroup v2** | Isolate candidate Python and collect CPU, memory, process, storage, and wall observations. Live containers have no network, host mount, host `.git`, credentials, Docker socket, capabilities, or writable root. | They do not isolate ordinary top-level Pi; that remains a host process. |
| **Workspace archive** | Moves sorted bounded regular files into and out of the kernel over the wire. Fixed helpers provide list, read, write, delete, search, and argv-only command execution. | No symlinks, devices, traversal, `.git`, arbitrary mounts, or out-of-policy persisted writes. |

The model process and the candidate kernel are separate effects. The model asks
for a strict action; fixed host code decides whether that action is legal and,
for execution, sends only the bounded operation to the kernel.

## Evolution and selection layer

| Component | Responsibility |
|---|---|
| **Mutator** | Accept one parent and produce one different normalized child through the fixed proposer. |
| **Candidate Runner** | Execute one immutable candidate/task pair and capture its forecast and submission. |
| **Observer/evaluator** | Interpret independently produced execution evidence after submission. |
| **Forecast Assay** | Recompute target surprisal and report task and safety evidence. |
| **Selection Gate** | Make the authenticated parent/child pass-count and safety decision for one Controller round. |
| **Controller** | Order one matched generation and bind all component results. It does not choose the next Population parent. |
| **Population Archive** | Record candidates and replicates, enforce feasibility, compute named Pareto coordinates and behavior novelty, and retain a bounded development archive. |
| **Population Driver** | Use the preceding exact allocation as the next parent, invoke bounded Controller rounds, persist receipts, handle explicit retries, and stop at an evaluator-verified development goal or declared limit. |
| **Agentvolve final selector** | Choose from the development archive by task rate, then reliability, then the exact tie draw before protected content is opened. |

Agentvolve is a bounded steady-state search: each round allocates one parent and
creates one challenger. It does not train Qwen, construct a Bayesian posterior,
adapt mutation policy, or automatically deploy the winner.

## Git and evidence layer

| Component | Responsibility |
|---|---|
| **Git** | Immutable candidate bytes, first-parent ancestry, tree identity, and the final patch. Host code—not candidate code—creates solution commits. A Git hash proves content identity, not correctness or authorship. |
| **Canonical Driver JSONL** | Bounded recurrence, attempts, retry reservations, selected parents, and cross-ledger references. |
| **Canonical Population JSONL** | Candidate, experiment, run, archive, allocation, and final-seal authority. |
| **Content-addressed receipts** | Mutation transcripts and usage, candidate execution, evaluator outcomes, resources, final cases, and conformance evidence. |
| **SQLite** | Disposable query index rebuilt from the Population ledger. It never controls recurrence or selection. |
| **Status and report files** | Human-readable projections such as `[4/6] Evolving solution`; they carry no authority. |

## What evolves and what stays fixed

| Run level | Evolves | Must stay fixed |
|---|---|---|
| **Level 2** | One of the nine harness loci per child. | Model weights/runtime, Pi connector, coding workspaces, evaluator, Docker profile, Population policy, and protected suite. |
| **Level 1** | Repository files under the task profile's allowed paths. | Selected harness, model/runtime, repository base, task profile, evaluators, Population policy, and protected suite. |

This separation is what makes a result attributable. Changing Qwen weights,
llama.cpp settings, the harness, solution source, and evaluator in one run would
make the selected cause unknowable.

## Protected final boundary

The task profile exposes only an absolute final-profile path and SHA-256 to
trusted host code. Mutation requests contain development material, not final
checks. Development stops and an exact final candidate allocation is committed
before the final profile is opened. The first final run seals Population against
later mutation, archive, or allocation transitions.

A verified result therefore means that the recorded candidate passed or failed
the named checks under the recorded stack. It does not mean universal coding
improvement, model training, safe deployment, or an official external benchmark
score.
