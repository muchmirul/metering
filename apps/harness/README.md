# Evolutionary harness application

`apps/harness/` is a source-only, mutation-only agent-harness implementation.
It makes the previously generic Git executor boundary concrete without changing
the installed `metering` package. A fresh checkout can run the deterministic
reference experiment with no model or container:

```bash
rm -rf /tmp/metering-harness-reference
uv run python apps/harness/experiment.py \
  fixture /tmp/metering-harness-reference
uv run python apps/harness/experiment.py \
  verify /tmp/metering-harness-reference
```

The first command creates an immutable Git seed, runs kernel conformance, evolves
and evaluates two descendants through Controller and Population Driver, performs
one protected final assay, seals Population, and verifies the resulting ledgers.
The deterministic fixture changes subtraction to addition and then multiplication:
addition is retained, multiplication is rejected, and the retained addition
harness passes the three protected final cases. This proves the checked-in
mechanism, not broad model improvement.

## Candidate contract

Every candidate is a complete `evolutionary-harness-v1` tree. `harness.json`
binds exactly nine sorted, SHA-256-addressed loci:

| Locus | Meaning |
|---|---|
| `system_prompt` | Candidate problem-solving instructions |
| `context_policy` | Task/event inclusion and transcript bounds |
| `compaction_policy` | Deterministic hash-linked event dropping |
| `tool_policy` | IPython code, output, execution, interrupt, and call bounds |
| `subagent_policy` | Recursive depth, calls, task size, and turn bounds |
| `ipython_bootstrap` | Python executed only inside the kernel sandbox |
| `snapshot_policy` | JSON-safe names, size, cadence, and restart restoration |
| `dependency_lock` | Sorted exact package pins supported by the immutable image |
| `entrypoint` | Recursive action protocol and finite turn/error limits |

No undeclared file, symlink, duplicate locus, noncanonical policy, unpinned
dependency, or digest mismatch is accepted. Candidate Python is syntax-checked
but never imported or executed by host validation. The fixed runner interprets
declarative policy; candidate-owned extensions or transport code never run with
host credentials. `reference/` is the complete seed genome.

The fixed outer mutator, model transport, kernel supervisor, sandbox flags,
resource observer, evaluator, development/final task ownership, Metering core,
Controller, Population verifier, and final seal are not candidate loci.

## Runtime and kernel contract

A canonical `evolutionary-harness-runtime-v1` profile binds:

- model connector, implementation version, provider, model, and reasoning;
- an immutable dependency-lock allowlist;
- kernel command and OCI image digest;
- CPU, memory, process, storage, tmpfs, and wall limits;
- required external observations;
- model-call timeout, call-count, and cumulative action-output limits; and
- observed-live or deterministic-fixture cost semantics.

Its canonical digest is the Population `runtime_id`. Live profiles accept only
the reviewed `docker-v1` engine and an image reference containing
`@sha256:<digest>`. The runner verifies Pi/Prime Agent `--version` and the pinned
provider/model/reasoning values before inference.

`kernel_server.py` implements the fixed JSON-lines ABI. `KernelSession` covers:

```text
boot -> execute -> interrupt/timeout -> snapshot -> restore
     -> cleanup -> restart recovery -> shutdown
```

The OCI process has no network, host mount, credential, writable root, or IPC
sharing. Docker enforces a read-only filesystem, dropped capabilities,
`no-new-privileges`, a non-root UID, file-descriptor/core limits,
pids/memory/CPU limits, and bounded writable tmpfs storage. The host supervisor
samples cgroup-v2 CPU, memory peak, process peak, storage writes, and wall time.
Model connector subprocesses are separately observed through procfs. Receipts
also bind model calls/tokens, candidate, task, manifest, runtime, recursive
transcript root, returned forecast/submission, and separately named Population
cost coordinates. Energy and GPU time are
explicitly marked unavailable rather than inferred.

`process-fixture-v1` runs the same wire contract in a host process for CI. It is
not isolation and is rejected unless
`METERING_HARNESS_ALLOW_UNSAFE_FIXTURE=1` is explicit.

Run conformance alone with:

```bash
uv run python apps/harness/conformance.py \
  --allow-unsafe-fixture \
  apps/harness/profiles/runtime-fixture.json \
  apps/harness/reference
```

See [`isolation/README.md`](isolation/README.md) for the live OCI prerequisite.

## Recursive harness loop

The application owns a provider-neutral bounded loop. A tool-free model transport
returns exactly one action per call:

```json
{"action":"execute","code":"Python code"}
{"action":"delegate","task":"bounded subproblem"}
{"action":"finish","forecast":{"outcomes":[]},"submission":{}}
```

A delegate receives an independent context and kernel session and must return a
bounded string result. The fixed loop enforces candidate depth/call/turn limits,
executes cells only through the kernel ABI, snapshots declared JSON state,
compacts transcript events with a retained SHA-256 commitment, and validates the
final forecast/submission contract. Pi and Prime Agent are one-shot model
transports; neither owns recurrence, tools, snapshots, or retention.

## Evolution and final evidence

The one-command composition uses existing owners:

```text
tool-free fixed mutator -> immutable Git child
  -> fixed harness runner -> isolated IPython phenotype
  -> independent evaluator -> Forecast Assay / Selection Gate
  -> Population evidence receipt -> Pareto archive / exact draw
  -> bounded recurrence -> protected final assay -> permanent seal
```

Development and final tasks are different identified sets. Final tasks are
loaded only after development stops and the final candidate allocation is
recorded. Declaring the one-use final experiment stops Population Driver before
case execution; if that assay fails, the experiment cannot be reused for search
or silently retried. Final outcomes never enter mutation, archive construction,
or another allocation. The first final-role run activates Population's existing
permanent search seal. Offline verification replays both ledgers, the exact development
and final task-set identities, conformance, every authenticated run/result receipt,
and receipt-set closure; checks every Git candidate and typed manifest; verifies
dependency compatibility; and requires exactly one final run.

Authority remains separate: Controller authenticates one pairwise generation;
Population owns archive membership and exact allocation. There is no generic
fitness or intelligence score. Task, safety, reliability, novelty, forecast,
information, and resource coordinates stay separately named.

## Coding workspace and Level 2

The kernel ABI also supports a bounded archive-in/archive-out coding workspace.
A task may add `workspace.files` and a fixed policy to the ordinary prompt and
outcomes. The host validates at most 2,000 sorted regular files/8 MiB, excludes
`.git`, rejects symlinks and traversal, and transfers the archive over stdin—no
host mount. Fixed kernel helpers expose list/read/write/delete/search and
shell-free argv execution. The Docker boundary and resource limits are the same
as for generated IPython cells; persisted writes are restricted to declared
paths. Finish returns a complete content-addressed snapshot, and a fresh
container—not the mutation container—runs each trusted assay.

`coding-fixture` and `coding-pi` use these workspaces to evolve the complete
nine-locus Pi harness on fixed development coding cases, then run a separate
protected final suite and write `selected-harness.json`:

```bash
uv run python apps/harness/experiment.py \
  coding-fixture /tmp/metering-coding-harness
uv run python apps/harness/experiment.py \
  verify /tmp/metering-coding-harness

uv run python apps/harness/experiment.py \
  coding-pi /tmp/metering-coding-harness-live \
  /absolute/path/runtime.pi.json

# Inspect [2/6] harness evolution or [3/6] harness sealing.
uv run python apps/harness/experiment.py status /tmp/metering-coding-harness-live

# Resume only replayable effects, or explicitly spend one reserved retry.
uv run python apps/harness/experiment.py resume /tmp/metering-coding-harness-live
uv run python apps/harness/experiment.py retry \
  /tmp/metering-coding-harness-live 'operator-reviewed reason'
```

New coding-harness roots write projection-only `process-status.json`: stage
`[2/6] Evolving harness` advances monotonically to `[3/6] Harness sealed`.
The tracker improves operator visibility but has no selection or replay authority;
see the [six-stage Agentvolve process](../../docs/coding-agent/workflow.md).

A retry first seals the existing content-addressed run receipts under
`state/retry-effects/` and includes its digest in the next hash-derived attempt
identity. Offline replay treats otherwise-unbound entries as non-selecting
residue and preserves exact receipt-set closure.

That selected descriptor is the frozen policy input to the separate
[Agentvolve Level-1 application](../coding_agent/README.md), which evolves
solution commits. Harness and solution genomes never mutate in the same
experiment. A Level-2 descendant selected from a saturated suite is evidence of
mechanism and retained compatibility, not necessarily higher coding capability.

## Live Pi or Prime Agent

After preparing an immutable OCI runtime profile, run:

```bash
uv run python apps/harness/experiment.py \
  pi /tmp/metering-harness-pi /absolute/path/runtime.pi.json

uv run python apps/harness/experiment.py \
  prime-agent /tmp/metering-harness-prime /absolute/path/runtime.prime.json
```

A trusted source checkout also exposes the same Pi composition through the
project-local **Agentvolve** extension. Run `pi` from the repository root, approve the
project once, and use `/evolve`, `/evolve-status`, or `/evolve-verify`. For coding, use
`/evolve-harness`, `/evolve-harness-status`, then
`/evolve-code /absolute/task.json`, `/evolve-code-status`, or
`/evolve-code-verify`. This is a
thin fixed-connector UI: opening Pi does not start a run, nested model calls do
not inherit the interactive session or extension, and selected candidates are
not automatically installed. See the [Pi connector](../../connectors/fixed/pi/README.md#interactive-population-evolution-mode).

The runtime profile, not ambient settings, pins provider, model, reasoning, and
agent version. `METERING_PI_COMMAND` or `METERING_PRIME_AGENT_COMMAND` may name
a reviewed JSON command prefix. The connectors use isolated configuration roots and empty temporary model
working directories, and disable sessions, discovered resources, context files,
and tools. The mutator receives bounded candidate file text and returns whole-file edits without
tools; it cannot browse the repository or protected cases. The runner's model
transport is also tool-free; only the fixed host loop can invoke the isolated
IPython action.

Docker/cgroup-v2 support, a built immutable runtime image, model credentials, and
a reachable provider are platform prerequisites. A live result applies only to
the exact profile, model, tasks, evaluator, and receipts.

## Modules

| Module | Owner |
|---|---|
| `protocol.py` | typed candidate genome and refresh validation |
| `runtime_manifest.py` | canonical runtime identity and compatibility |
| `workspace.py` | canonical archive/path/policy validation and host materialization |
| `kernel_server.py` | sandbox-side IPython/fixture wire server and coding helpers |
| `kernel_contract.py` | host supervisor, restarts, OCI flags |
| `resources.py` | external procfs/cgroup-v2 observations |
| `model_contract.py` | provider-neutral one-shot model protocol |
| `runtime.py` | context, compaction, tools, recursion, completion |
| `receipts.py` | immutable content-addressed run evidence |
| `conformance.py` | lifecycle assay |
| `harness_runner.py` | concrete `git-candidate-v1` executor |
| `evidence_adapter.py` | receipt-to-Population translation |
| `final_assay.py` | protected single-candidate evaluation and seal |
| `experiment.py` | reference composition and offline verification |

Provider CLI translation stays under `connectors/fixed/`; generic Git clone,
commit, content identity, and publication stay under `artifacts/git/`.
