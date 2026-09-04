# Metering Plan

## Status

This document defines Metering's complete accepted scope. It replaces the
earlier hidden-fault harness design with a deliberately breaking reset.

The installed Metering package has one measurement purpose:

> Measure named information-theoretic quantities from probability
> distributions supplied by the caller.

It is a tool, not an agent. The package contains no policy, planner, optimizer,
model, world, controller, belief updater, or recommendation logic. A separate,
explicit history command may retain accepted measurement requests and responses;
it does not change or interpret them.

Repository-local evolution applications and connectors are source-only tools
around external agents. They now include one concrete, mutation-only typed
recursive harness under `apps/harness/` and one profile-bound two-level coding
composition under `apps/coding_agent/`; neither is installed Metering
and does not move provider translation, evaluation, selection, or deployment
authority into the package. External agents propose harness, adapter, and
model-output candidates. External trainers produce weights. Metering validates
declared probability models and computes named quantities; source-only owners
bind candidate/evidence identity, apply explicit retention, and record lineage.
The installed package never generates a refined harness or trains model weights.

## Foundation

The fundamental quantity is the logarithmic measure introduced by Claude
Shannon in *A Mathematical Theory of Communication*:

```text
self-information:  I(x) = -log_b p(x)
entropy:            H(P) = -sum_x p(x) log_b p(x)
```

The choice of base fixes the unit. Base 2 is the default and produces bits.
Base `e` produces nats. Metering accepts a real base whose conversion to a
finite Python float remains greater than 1.

Metering supports finite discrete probability models only.
That boundary is intentional. Continuous entropy, sample-based estimation, and
channel optimization require additional assumptions that this package must not
silently invent.

## Public measures

### Self-information

```text
self_information(p, base=2) = -log_b(p)
```

`p` is one probability in `[0, 1]`. A probability of zero returns positive
infinity. A probability of one returns zero.

### Shannon entropy

```text
entropy(P, base=2) = -sum_i p_i log_b(p_i)
```

`P` is a finite discrete probability mass function. Terms with `p_i = 0`
contribute zero.

### Kullback-Leibler divergence

```text
kl_divergence(P, Q, base=2) = sum_i p_i log_b(p_i / q_i)
```

`P` and `Q` are aligned finite distributions of equal length. An index with
`p_i > 0` and `q_i = 0` returns positive infinity. An index with `p_i = 0`
contributes zero. The order matters: `D_KL(P || Q)` is not generally equal to
`D_KL(Q || P)`.

### Mutual information

```text
mutual_information(P_XY, base=2)
    = sum_x sum_y p(x,y) log_b(p(x,y) / (p(x) p(y)))
```

The input is a non-empty rectangular matrix containing a finite joint
distribution. Rows represent outcomes of one variable and columns represent
outcomes of the other. Metering derives only the two marginals required by the
formula; it does not interpret the variables.

## Mathematical naming boundary

Metering does not expose a generic `information_gain` function.

In a uniform deterministic partition, these three values happen to be equal:

```text
H(prior) - H(posterior)
-log_b P(observation)
D_KL(posterior || prior)
```

They differ for general non-uniform or noisy models. Callers must use the name
that matches what they mean:

- entropy before minus entropy after is an entropy change;
- self-information is the surprisal of one declared outcome;
- `D_KL(posterior || prior)` measures a particular distribution update;
- mutual information measures expected dependence between two declared
  variables.

The package must not collapse these into one flattering number.

## Input contract

All validation is strict and visible:

- A probability is a real, non-Boolean number in `[0, 1]` whose conversion to
  a finite Python float does not collapse a nonzero value to zero or a value
  distinct from one to one.
- A distribution is a non-empty ordered iterable of probabilities.
- A distribution's sum must be within an absolute tolerance of `1e-12` from
  one. Relative tolerance is zero.
- A joint distribution is non-empty, rectangular, and normalized as one
  distribution across all cells.
- KL inputs must have equal lengths and use the same positional ordering.
- The logarithm base is a real, non-Boolean number whose conversion to a
  finite Python float remains greater than one.
- Invalid inputs raise `ProbabilityError`.

Metering never normalizes, smooths, clips, bins, samples, or estimates on the
caller's behalf. Acceptance within the fixed sum tolerance accommodates normal
floating-point roundoff. Entropy and self-information use the converted values
as supplied. KL and mutual information use the explicitly declared
non-negative relative-entropy extension below. Nothing is rescaled.

Calculations use Python's double-precision floating-point arithmetic and
`math.fsum` where sums are involved. Results should be compared with a suitable
numerical tolerance rather than by serialized decimal spelling. Metering does
not promise byte-identical last-place decimals across different Python/libm
platforms.

KL is evaluated with the non-negative form
`sum_i (p_i ln(p_i/q_i) - p_i + q_i) / ln(base)`. For normalized distributions,
the added terms sum to zero, so this is algebraically the declared KL formula.
For inputs accepted only because their sums are within tolerance, this formula
is the defined extension and remains non-negative. Close coordinates use the
convergent series for `(1+d) ln(1+d) - d` to avoid cancellation. Mutual
information uses the same form and separates the two marginal logarithms when
their product would underflow. If an accepted joint has total mass `S` that
differs from one only within tolerance, its derived comparison mass is
`row_x * column_y / S`, not the mass-`S^2` raw marginal product. This preserves
zero dependence for factorized tables without rescaling the supplied cells.
These evaluation rules do not normalize or modify either input.

## Python boundary

The complete supported public API is:

```python
from metering import (
    ProbabilityError,
    self_information,
    entropy,
    kl_divergence,
    mutual_information,
)
```

For fixed numeric inputs, the functions are deterministic. They do not read or
write files, access the network, or modify caller-owned containers. A one-shot
iterator is necessarily consumed once when its values are materialized.

## Agent and shell boundary

Other agents use the same measures through one Unix-style command. The command
reads exactly one JSON object from standard input and writes exactly one JSON
object to standard output.

Valid request shapes are:

```jsonl
{"measure":"self_information","probability":0.125}
{"measure":"entropy","probabilities":[0.5,0.5]}
{"measure":"kl_divergence","p":[0.5,0.5],"q":[0.75,0.25]}
{"measure":"mutual_information","joint":[[0.5,0.0],[0.0,0.5]]}
```

Each request may add an optional numeric `base` key. No other keys are
accepted. Duplicate keys and non-finite numbers are rejected. A numeric token
is also rejected if double-precision conversion would produce infinity or
would change whether its value is zero or one.

A finite result has this exact shape:

```json
{"base":2.0,"infinite":false,"measure":"entropy","value":1.0}
```

Positive infinity is represented without emitting invalid JSON:

```json
{"base":2.0,"infinite":true,"measure":"self_information","value":null}
```

The command emits exactly `error.code` and `error.message` as one JSON object
on standard error:

```json
{"error":{"code":"invalid_probability","message":"..."}}
```

The only error codes are `invalid_request` for JSON, command-line, or request
envelope failures, and `invalid_probability` for a rejected probability model
or logarithm base. Exit status is zero for a successful measurement and two
for either error. `-h`/`--help` and `--version` are the only command-line
options; long options are not abbreviated. The command does not read or write
application files and does not make network requests.

This JSON boundary is intentionally not agent-specific. Any agent, shell,
programming language, or process runner that can exchange JSON over standard
streams can use it. An MCP server, plugin system, HTTP service, or model adapter
would add machinery without improving the measurement and does not belong here.

## Measurement history boundary

`metering-history` is an explicit Git-backed filesystem wrapper around the
public `metering` command. The ordinary Python functions and `metering` command
never enable it implicitly. Recording one request is deliberate:

```bash
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | metering-history record PATH
```

The wrapper first asks `metering` to validate and measure the request. A rejected
request leaves `PATH` absent. The first accepted request initializes a dedicated
Git repository on branch `metering-history`; every accepted request then commits
exactly these canonical files:

```text
measurement/pair/configuration.json   normalized Metering request
measurement/pair/result.json          exact named Metering response
measurement/provenance.json           package, Python, source, and implementation identity
```

Git owns storage and lineage identity:

```text
pair_id          = Git tree ID of measurement/pair
record_id        = Git commit ID
parent_record_id = first parent commit ID or null
tree_id          = complete commit tree ID
```

Repeating the same configuration and result preserves `pair_id`. Every append
creates a distinct commit even when its tree is unchanged. The result schema is
version 2 and also exposes the implementation SHA-256, Metering version, Python
version, optional source commit, and whether that source checkout was dirty.
No Metering source code is copied into the history.

The complete command surface remains:

```text
metering-history record PATH   validate, measure, and commit one pair
metering-history log PATH      emit current-branch commits newest first
metering-history verify PATH   verify Git, schemas, cleanliness, and replay
```

`verify` runs `git fsck`, rejects a dirty worktree, validates the exact tracked
files and canonical schemas in every current-branch commit, requires a linear
first-parent history, and reruns every stored configuration through the current
Metering executable. A committed result that differs from replay is invalid.
Git proves committed byte identity and parentage; replay supplies semantic
measurement validation. Neither authenticates the author or prevents an actor
with write authority from consistently replacing history. Remotes, protected
branches, and signatures remain caller choices.

The history wrapper requires a `git` executable but adds no Python dependency.
Storage or integrity failures emit `invalid_history`; command-envelope failures
emit `invalid_request`; both exit with status two. Measurement request failures
preserve Metering's error and do not create storage. A stale
`.git/metering-history.lock` after interruption must be inspected before removal.
Legacy schema-version-1 `objects/` histories are intentionally not modified or
automatically migrated; inspect them with the historical implementation.

## Application boundary

Small, non-packaged applications may live under `apps/` to demonstrate how a
caller constructs a probability model and invokes Metering through its public
boundary. Application code may observe a world, update caller-owned state, and
use a measurement when choosing an action. Those responsibilities remain in
the application and are not re-exported from `metering`.

Every application must state:

- what the outcomes in each supplied distribution mean;
- how the probabilities were constructed;
- which named Metering result is being reported; and
- what the result does not establish;
- the foundational equations and assumptions that justify its mechanism;
- why its software boundary is no broader than necessary; and
- which claims are mathematical identities, tested implementation hypotheses,
  or external empirical hypotheses, including concrete falsifiers and primary
  sources where applicable.

The `apps/forecast_assay` example is a stateless screening adapter. Each
request and successful report carries application schema version 1. A request
identifies one candidate, one fixed evaluation, and unique observed cases. The
caller supplies the probability that a normalized candidate forecast assigned
to each named target before that target was revealed. The adapter reports the
target self-information and an explicitly application-owned, equally weighted
arithmetic mean. Default transport handles one request and exits; `--jsonl`
processes independent requests one per line without retaining candidate state.
It does not generate mutations, compare or retain candidates, implement an
environment, or run an evolution loop.

The `apps/observer` example owns a finite versioned sandbox, a uniform candidate
belief, and an immutable probe catalogue. Its default deterministic demo chooses
the maximum-result-entropy probe. Its `--jsonl` transport instead accepts
external-agent `state`, `observe`, and `finish` actions sequentially, returning
one flushed response per input line while keeping the active sandbox private.
The application constructs and conditions the probability model; Metering only
measures its declared distributions. The protocol does not add agent policy,
nonuniform priors, persistence, or application behavior to the installed
package.

The `apps/mutator` example applies exactly one legal one-locus change. The
caller supplies the immutable parent, finite legal catalogue, complete positive
mutation distribution, and explicit draw. The app canonicalizes unordered
support, asks Metering for distribution entropy and selected-outcome
self-information, and returns content-derived catalogue, parent, child, and
transition identifiers. It contains no hidden randomness, assay, selection,
lineage, repetition, or mutation-policy update.

The `apps/candidate_runner` example gives one concrete executable meaning to a
Mutator genome. The genome declares one Observer fixture hypothesis and its
integer probability in basis points; remaining probability is divided equally
among the other fixtures. For one unrevealed public probe, the runner constructs
the complete result distribution, validates and measures its entropy through
Metering, and returns canonical target strings. It independently verifies that
the Mutator candidate ID matches the genome. It does not receive the active
fixture, inspect Observer state, execute arbitrary code, learn, mutate, observe,
or select.

The `apps/selection_gate` example verifies two complete Forecast Assay reports
on the same identified evidence, recomputes their target self-information and
means, and applies one caller-supplied strict improvement threshold. The
retention decision belongs to that application, not to Metering. Candidate
labels remain opaque assay identifiers: an external controller must bind them
to the exact incumbent and challenger content identities that it executed.
The gate does not prove model execution, forecast precommitment, inheritance,
or future improvement.

The `apps/controller` schema version 1 example executes exactly one fixture
generation. It sends one explicit request to Mutator, obtains both Candidate
Runner forecasts before each Observer reveal, carries exact content IDs into
Forecast Assay, submits aligned reports to Selection Gate, and returns the
selected candidate as `next_parent`.

Application schema version 2 adds one bounded agent-artifact generation without
changing Metering's installed interfaces. Mutator either binds one
caller-supplied challenger or invokes one strict proposer command with only the
current parent and caller-approved context, then binds the returned complete
`SKILL.md` or immutable Git descriptor. Candidate Runner invokes a
caller-selected adapter for both
candidates on identical finite task documents and validates a complete
pre-evaluation outcome forecast. Observer invokes a separate trusted evaluator
adapter only after both submissions exist. Forecast Assay reports named task
pass, safety, and forecast-surprisal evidence. Selection Gate applies an
explicit safety-regression and minimum-pass-improvement policy; it does not use
lower surprisal as a substitute for task capability. Controller preserves
candidate IDs and returns one selected artifact.

Version 2 adapters are ordinary caller-selected subprocesses. The controller
enforces command argument separation, equal task documents, ordering, candidate
binding, finite timeouts, and report alignment. Protocol strings must encode as
UTF-8, and adapter decimal tokens are rejected when double-precision conversion
would produce infinity or change whether the value is zero or one. Adapter
implementations own
agent invocation, hidden verifiers, workspace isolation, model and tool
settings, token or monetary budgets, and the meanings of `passed` and
`safety_passed`. The checked-in demo adapters are deterministic protocol test
doubles. Concrete fixed Pi and Prime Agent runners and proposers live under
`connectors/fixed/`; their tool-free skill paths disable discovered resources
and inject only the verified candidate `SKILL.md`. Neither connector is a coding
sandbox or empirical evidence of improvement. Another agent is supported only
after its concrete connector passes the same protocol and evidence tests.

Both controller versions invoke every component through documented JSON
standard streams. Neither owns a persistent lineage, automatic policy update,
repetition, installation, deployment, rollback, or stopping rule. A caller, the
explicit single-head Evolution Driver, or the bounded Population Driver must
submit another request to advance another generation. Installation of
`next_parent` always remains a separate caller-approved operation.

The `apps/evolution_driver` wrapper owns only bounded recurrence between
completed schema-version-2 generations. It keeps one append-only, hash-linked,
canonical JSONL ledger, verifies the full chain before resuming, supplies the
last selected artifact as the next parent, exposes only a fixed aggregate of the
previous selection as proposer feedback, and does not start another generation
after the first configured generation, consecutive-rejection, or per-invocation
wall-clock limit. A failed or
interrupted Controller call never appends a generation record. Selected skills
remain run-local; the driver does not install, deploy, or claim general
improvement.

The `apps/population` outer control plane is a separate source-only schema
version 1 application. It records normalized agent candidates, identified
development/final experiments, unique replicate runs, immutable external
evidence receipts, named evidence, archive events, and exact parent allocations
in one canonical hash-linked JSONL ledger.
It derives task rate, target self-information, optional finite-model mutual
information, hard protected/safety/resource admission, replicate reliability,
and directed behavior novelty through public Metering functions and explicit
application policy. It never reads final-role evidence into an archive. The
first final run seals that ledger against every later candidate, experiment,
development-run, archive, allocation, or recombination transition while still
allowing additional runs of already declared final experiments.

Population Archive retains a bounded development-only Pareto set over separately
named task, reliability, novelty, forecast-loss, optional information, and
resource coordinates. It uses no weighted generic score. Its one parent policy
orders immutable candidate IDs, gives each retained member exact probability
`1/n`, and applies a caller-supplied rational draw with integer arithmetic. An
empty, superseded, or evidence-stale archive cannot allocate a parent. Typed
recombination is limited to complete `agent-skill-v1` file loci, requires a
differing contribution from both identified parents, and is reconstructed on
ledger replay. It does not merge Git candidates, invoke Controller, execute an
allocated parent, adapt policy, install, or deploy.

`population.sqlite` is a caller-local disposable index over the canonical
ledger. Rebuild creates every row from replayed records; verification compares
every indexed row with an independent in-memory rebuild. Archive and allocation
decisions never read SQLite. The application uses Python's standard-library
SQLite support, is excluded from the wheel, and adds no package dependency. Its
source command surface is exactly `init`, `candidate`, `experiment`, `run`,
`archive`, `allocate`, `recombine`, `rebuild`, `verify`, `verify-index`, and
`query`, each followed by one caller-selected state directory. Request commands
read one strict JSON object; success writes one canonical JSON object, and a
request or population-state failure exits with status two and emits
`invalid_request` or `population_error` respectively.

The `apps/population_driver` outer orchestrator activates bounded automatic
population execution as a separate source-only schema version 1 application.
It accepts exactly one normalized Git seed, fixed proposal/runner/evaluator and
trusted evidence-adapter commands, one derived development experiment, exactly
`max_rounds - 1` rational allocation draws, finite global round, proposal-call,
candidate-resource, and timeout-reservation limits, and an optional versioned
`all-development-cases-pass-v1` stopping policy. The seed is
the first Controller parent. Every later parent must be the exact candidate in
the preceding Population allocation record. Controller still owns one matched
parent/child generation; Population still owns named run evidence, Pareto
retention, and exact allocation.

Before a Controller attempt, Population Driver atomically records a canonical
round intent. A valid Controller result is written as an immutable receipt
before evidence adaptation or Population ingestion. A pending attempt without a
valid Controller receipt cannot be repeated by ordinary resume; one matching
`retry` request, explicit reason, remaining proposal call, and remaining timeout
reservation are required. Once the Controller receipt exists, evidence
adaptation and prefix-checked Population records resume without another model
call. Completed rounds form a separate canonical hash-linked driver ledger and
cross-reference exact Population candidate, run, archive, and allocation
records. Driver and Population ledgers, immutable receipts, and a pending intent
are authority; Population Driver never reads SQLite.

This first driver schema is mutation-only and Git-code-only. A fixed external
model such as Qwen may mutate ordinary code through Pi while model weights remain
unchanged. The trusted evidence adapter may add only behavior distribution,
protected admission, resource observations, and seed metadata; task, safety,
forecast, candidate, evaluator, and selection facts replay from Controller.
Controller's pairwise `next_parent` is recorded but Population allocation chooses
the next population parent. A natural-language objective guides proposals but
never certifies completion. When configured, the pure stopping predicate accepts
only a feasible member of the latest independently computed archive whose
accumulated public cases all pass for the required replicate count; it reports
`development_goal_reached` and suppresses a next-parent allocation. The finite
`max_rounds` bound remains mandatory and is the fallback. The driver creates
only development experiments, checks the Population final seal before another
round, and never exposes final evidence to proposal, archive, or allocation. By
itself it does not adapt mutation, recombine Git code, train weights, co-evolve
evaluators, provide a
generic sandbox, install, or deploy.

`apps/harness` supplies the accepted concrete executor for one typed Git
candidate form. `evolutionary-harness-v1` binds exactly nine prompt, context,
compaction, tool, subagent, IPython-bootstrap, snapshot, dependency-lock, and
entrypoint loci. Host validation never imports or executes candidate Python. A
fixed provider-neutral loop accepts only bounded `execute`, `delegate`, and
`finish` actions. Each delegate receives an independent context and kernel;
finite depth, calls, turns, code, output, snapshots, model calls, and runtime
limits are mandatory. Pi and Prime Agent translations disable tools, sessions,
discovered resources, and context; a tool-free fixed mutator can replace only
declared complete locus files and never receives protected final tasks.

The corresponding `evolutionary-harness-runtime-v1` identity binds the agent
version, provider, model, reasoning, immutable OCI image, kernel command,
dependency allowlist, kernel and model-call/output/timeout limits, required
observations, and cost mode. Live candidate bootstrap and cells execute only in the reviewed Docker profile:
no network or host mount, read-only root, non-root UID, all capabilities dropped,
`no-new-privileges`, bounded tmpfs/CPU/memory/pids, fixed command, and external
cgroup-v2 CPU/memory/process/storage/wall observations. Model connector
subprocesses are observed through procfs. A process fixture uses the same ABI for
deterministic CI but is explicitly unsafe and cannot silently replace live
isolation.

Content-addressed receipts bind candidate, task, manifest, runtime, transcript,
model calls/tokens, kernel/model observations, and separately named Population
costs. The reference sequencer runs kernel conformance, two bounded development
mutations through Population Driver, one exact final allocation, declaration of
a one-use final experiment that immediately stops Driver recurrence, a distinct
protected final suite, the first final-role run, and offline Git/manifest/
dependency/receipt/ledger verification. Final evidence never enters mutation,
archive, or another allocation; Population's existing first-final-run seal is
authority. Energy and GPU observations remain explicitly unavailable rather than
estimated. This implementation does not train weights, adapt mutation,
recombine Git candidates, co-evolve an evaluator, install, or deploy.

**Agentvolve** is the user-facing name for the accepted two-level coding
workflow. `apps/coding_agent` remains the compatibility-stable narrow coding
executor path over that same typed harness and Docker profile. Existing
`darwinian-coding-*` schema identifiers, the `darwinian_coding` tool name, and
`/evolve-*` commands remain unchanged so recorded runs and task profiles replay.
Agentvolve does not activate arbitrary legacy Git execution.
Its canonical `darwinian-coding-task-v1` profile binds one absolute
operator-approved repository, exact base commit and entrypoint, sorted allowed
write paths, non-empty development checks as argv arrays, a normalized absolute
path plus SHA-256 for a separately permissioned protected-final profile,
per-check timeouts, exact recurrence and final tie draws, a bounded worded goal,
finite round/proposal/wall limits, and an optional evaluator-backed goal-or-limit
stopping policy. Profiles without the additive policy retain numeric limit-only
behavior. Fixed code opens the protected profile only
after development stops. A model cannot directly authorize or alter either
profile. The interactive launcher may generate a task-description draft from
user messages on the active Pi branch, but it excludes assistant messages and
requires explicit operator review before fixed code registers the profile. That
registration binds a clean repository HEAD and may only replay the reviewed
public checks as its disclosed protected-final policy; it does not invent hidden
coverage. `/goal` plus `/limit` may mechanically derive a fresh profile only from
an already reviewed discovered task profile, preserving its paths, checks,
protected-final binding, and stopping policy while updating the exact goal,
clean HEAD, round limit, and draws. The task identity is the SHA-256 of its
normalized canonical form.

Coding mutation is archive-in/archive-out. Fixed host code resolves the exact
base/parent commit, serializes only sorted regular files, excludes `.git`, and
rejects symlinks, devices, path traversal, duplicate paths, more than 2,000
files, or more than 8 MiB. The archive enters the reviewed OCI kernel through
stdin, never a host mount. Fixed Docker-side helpers expose bounded
list/read/write/delete/search and shell-free argv execution; persisted writes
must match caller-approved path prefixes. The candidate has no network, host
Git checkout, `.git`, Docker socket, credentials, evaluator assets, host tools,
or writable root. Fixed host code validates the complete exported snapshot and
changed paths, then creates the immutable first-parent child commit itself.
There is no live-to-host fallback. The unsafe process fixture remains CI-only.

Development and final checks execute from fresh candidate archives in new OCI
kernel sessions rather than the mutation session. Their commands are the
profile's reviewed argv arrays, never model-generated shell strings. Execution
receipts bind candidate/content, task, runtime, command, return code, timeout,
output digests, workspace digest, isolation, cgroup observations, and separately
named Population resources. Candidate-written tests have no authority unless an
operator profile invokes them. The selected source repository is never modified.

Level 1 evolves solution commits under one frozen selected harness, model/runtime,
task profile, evaluator, and Population policy. Level 2 separately evolves the
nine typed harness loci on fixed coding workspaces through the same Controller,
Population recurrence, fresh independent evaluator, protected final suite, and
seal; it emits a canonical `selected-evolutionary-harness-v2` descriptor whose
provenance binds the assay, development experiment, final allocation, final
receipt/run/counts, and sealed Population head. Before use, Level 1 verifies the
complete source Level-2 run, preserves the candidate's original artifact
identity while localizing Git objects, and records a replayed provenance
receipt. A Level-2 descriptor is an explicit immutable input to a later Level-1 run.
Solution and harness genomes never mutate in the same experiment. A Pi session,
transcript, IPython namespace, and unexported temporary state are phenotype, not
heredity; only a validated Git child is inherited.

The operator-facing Agentvolve workflow uses one six-stage vocabulary: `[1/6] Task
and runtime configured`, `[2/6] Evolving harness`, `[3/6] Harness sealed`,
`[4/6] Evolving solution`, `[5/6] Protected final assay`, and `[6/6] Result
ready for review`. New run roots expose a canonical, monotonic
`process-status.json`, and Pi polls that file for status/widget updates. This
file is explicitly a disposable projection: it cannot authorize calls,
allocation, final access, selection, or replay, all of which remain controlled
by the existing hash-linked ledgers and receipts.

Population still owns development archive membership and reproductive parent
allocation. For user-facing code selection, the coding final assay uses one
explicit lexicographic policy rather than uniform selection across resource
tradeoffs: maximize development task rate, then maximize replicate reliability,
then consume the profile's exact rational draw among canonical candidate-ID
ties. Fixed code derives and records the exact Population allocation draw that
selects that candidate. Both draws and the policy identifier replay offline; no
weighted fitness/intelligence score is introduced.

Protected final checks are not included in mutation prompts, Controller
development requests, archives, or ancestry views. They are loaded only after
development stops and the final allocation is committed. Declaring the one-use
final experiment stops Driver recurrence; its first run permanently seals
Population. Final failure cannot trigger another mutation or replacement assay
inside that run. Output is an immutable selected commit/descriptor, a
replay-derived patch, and evidence. Applying, merging, installing, or deploying
it is always a separate caller action.

The reviewed Pi extension registers `/agentvolve` as the primary interactive
launcher, `/goal` and `/limit` as session-persisted workflow configuration, and
retains `/evolve-harness`, `/evolve-harness-status`,
`/evolve-harness-resume`, `/evolve-harness-retry`, `/evolve-code`,
`/evolve-code-resume`, `/evolve-code-retry`, `/evolve-code-status`, and
`/evolve-code-verify` as compatibility commands. A caller may explicitly list
the reviewed absolute extension path in Pi's global settings to make the command
available from every working directory. `/agentvolve` first offers local and
routed outer-session model modes, then opens one bounded workflow UI rather than
exposing Level-1 and Level-2 choices. The UI always renders all six explicit
`[n/6]` stages and offers one start/status/history/resume/retry/verify control
surface. Every Agentvolve-activated Pi session polls the same reviewed run
directory, stops its monitor on deactivation or session shutdown, and can browse
up to the latest 50 runs through
`/agentvolve-history`; monitoring is read-only and does not authorize effects.
Start discovers bounded `*.task.json` profiles from the absolute
`METERING_EVOLUTION_TASKS_DIR` (defaulting to the checkout sibling
`metering-live-tasks`), gives current-folder profiles priority, and keeps manual
absolute-path entry as a compatibility option. With both `/goal` and `/limit`
configured, `/agentvolve` selects the sole applicable reviewed profile, derives
its canonical run profile, activates local mode, and begins without another path
prompt; ambiguity still requires a choice. The configured three-command path is
also available in Pi RPC mode for headless operator automation, while incomplete
RPC configuration cannot open an interactive menu. Start validates one task
profile, reuses an already sealed compatible harness or creates one when none
exists, and then continues through solution evolution and the protected final
assay. An isolated run registry may reference an original sealed descriptor via
`METERING_EVOLUTION_HARNESS_DESCRIPTOR`; copying or rewriting its
repository-bound provenance is forbidden. It refuses to hide or bypass an
unfinished run. Local mode
starts the configured user llama.cpp service when needed, waits for the declared
Qwen alias, and selects the canonical runtime's provider/model/reasoning level.
Routed mode retains or restores the Pi model that preceded Agentvolve and does
not start llama.cpp merely to open the UI. An evolution action in either mode
still uses, and if necessary activates, the provider pinned by the canonical
runtime manifest. Loading the extension alone performs none of those effects.
Mode selection and service activation are UI transport conveniences, not
evaluation evidence or changes to nested runtime identity. A routed UI model
cannot silently become the experiment model; that requires a separately
reviewed runtime manifest and constitutes a different experiment. Resume cannot
repeat an indeterminate model call; retry requires an operator reason and a
predeclared call/time
reservation. The model-facing
`darwinian_coding` tool accepts only a
fixed action enum and uses the operator-configured absolute profile; it accepts
no task, command, evaluator, candidate, or output path. Pi is mutation transport
and UI, never evaluator, selector, ledger authority, or sandbox boundary.

Offline verification replays Driver and Population without SQLite, validates
profile/runtime/harness bindings and kernel conformance, re-clones every exact
harness and solution candidate, checks first-parent ancestry and allowed paths,
closes mutation/evaluation/final receipt sets, requires recorded evaluator
interpreter aliases to resolve to the exact current interpreter and evaluator
script, recomputes capability-first final allocation, requires complete
development and exactly one final run, confirms
the permanent seal, and regenerates the selected Git patch byte-for-byte.

Agentvolve workflow changes require an opt-in live acceptance run that loads the
project Pi extension and runs at least three operator-approved tasks through the
pinned local llama.cpp runtime, requiring every protected case and offline replay
to pass. This expensive check is separate from deterministic CI and fails unless
its explicit runtime, sealed harness, and task-profile inputs are present.

Agentvolve does not guarantee universal or monotonic improvement.
A live result applies only to its exact model, runtime, task profile, checks, and
receipts. A saturated Level-2 suite can prove compatible retained harness
evolution without proving increased capability. Broader improvement evidence
requires matched one-shot, continual, and Darwinian treatments under equal
model, tools, evaluator, task set, tokens/calls/wall budget, and protected cases.

### Parked population extensions

**Status: automatic population execution is implemented; all items below remain
parked.** They are not accepted runtime behavior, schema promises, or authority
granted to the installed package or current applications:

1. **Adaptive mutation policy.** A future application may update one declared
   mutation policy only after mutation features, finite belief/update semantics,
   evidence alignment, policy identity, rollback, and falsifiers are concrete.
   It must not infer causality from mutual information or introduce a generic
   fitness, intelligence, or quality score.
2. **Adversarial task generation or evaluator co-evolution.** This requires a
   separately fixed and protected meta-evaluator, immutable evaluator lineage,
   non-stationary experiment identities, fresh final evidence, and a rule that
   no candidate or evolving evaluator can approve itself. The current trusted
   evaluator remains frozen within every accepted experiment.
3. **Additional sandbox and transport profiles.** The typed harness and bounded
   coding workspace share one reviewed Docker/cgroup-v2 profile. Git execution
   outside the accepted archive-in/archive-out coding profile, Podman,
   Kubernetes, bubblewrap, remote kernels, and VM transports remain caller
   infrastructure until each has a versioned fail-closed profile, explicit
   receipts, and adversarial conformance tests. Python path checks, command
   separation, process-group cleanup, and timeouts alone are not a sandbox.
4. **Installation, deployment, and rollback integration.** These remain
   caller-approved external operations. Any future source-only adapter must keep
   credentials outside candidate access, bind the exact selected artifact and
   environment, require a separate approval action, emit immutable receipts,
   and demonstrate an explicit rollback path. Selection alone must never trigger
   installation or deployment.

Activating any parked item requires an explicit `PLAN.md` status change, the
narrowest new versioned schema, focused security and replay tests, full-suite and
package-boundary validation, compatibility documentation, and evidence that the
installed four-measure API and dependency surface remain unchanged. Do not add
placeholder modules, plugin interfaces, or database fields for parked work.

Application JSONL transports use standard input and output only. Recoverable
line errors produce an aligned JSON response and leave later requests usable.
They do not change Metering's installed one-request JSON command.

Applications must not add a generic score or describe a measured quantity as
meaning, usefulness, correctness, understanding, or universal harness quality.
They use the same public Python or JSON interface as any external caller. A
demonstration must not rely on private package modules.

## Permanent package non-goals

The installed Metering package does not contain:

- agents, models, prompts, memories, tools that choose other tools, or model
  adapters;
- policies, planners, search strategies, optimizers, rankings, or scores;
- worlds, tasks, repairs, verification, correctness, budgets, or resource
  accounting;
- posterior construction, Bayesian inference, probability estimation, sample
  binning, smoothing, or normalization;
- generic traces, experiment runners, manifests, commitments, replay engines,
  databases, dashboards, or artifact stores beyond the fixed measurement-pair
  ledger;
- continuous or differential entropy, entropy-rate estimators, channel
  capacity optimization, or learned estimators;
- claims about meaning, relevance, understanding, reasoning, knowledge, or
  intelligence.

Repository-local applications are examples, not additional Metering features.
They are excluded from the public API and wheel package.

## Repository layout

```text
src/metering/
    __init__.py       exact public Python surface
    information.py    validation and four pure measures
    __main__.py       strict JSON standard-stream adapter
    history.py        explicit Git-backed measurement history
tests/
    test_information.py
    test_cli.py
    test_history.py
    test_public_api.py
    test_observer.py
    test_forecast_assay.py
    test_mutator.py
    test_selection_gate.py
    test_candidate_runner.py
    test_controller.py
    test_evolution_kernel.py
    test_agent_evolution.py
    test_self_evolution.py
    test_population.py
    test_population_driver.py
    test_darwinian_code_evolution.py
    test_harness_evolution.py
    test_coding_agent.py
    test_architecture.py
    test_signal_relay_acceptance.py
    test_git_artifact_evolution.py
    test_connectors.py
docs/
    README.md
    foundations.md
    theory.md
    history.md
    evolution-kernel.md
    agent-evolution.md
    deterministic-search-evolution.md
    source-architecture.md
    coding-agent/       Agentvolve components, workflow, operations, task profile, architecture, and threat model
artifacts/
    git/              agent-neutral Git source/model-output candidate bridge
connectors/
    README.md         connector ownership and live conformance boundary
    tools/metering/   shared Agent Skills-compatible internal Metering tool
    fixed/
        pi/           concrete Pi proposer and runner translations
        prime_agent/  concrete Prime Agent proposer and runner translations
    full_context/     parked manifest-based repository-adoption profile
apps/
    README.md         application index and composition boundary
    _support/         narrow wire, process, stdio, journal, and durable mechanics
    agent_protocol.py shared source-only agent artifact and adapter validation
    observer/         fixture observer and trusted task-evaluator boundary
    forecast_assay/   forecast and task-evidence assay
    mutator/          schema-v1 genome mutation plus schema-v2 artifact mutation
    candidate_runner/ fixture model and external-agent adapter boundary
    selection_gate/   schema-specific forecast/task retention implementations
    controller/       fixture and agent-skill one-generation orchestrator
    evolution_driver/ bounded run-local recurrence over selected SKILL.md artifacts
    population/       public contract, canonical ledger, Pareto archive, allocation, and derived index
    population_driver/ replay, planner, effects, store, and bounded Git recurrence runtime
    harness/            typed recursive phenotype, coding workspace, OCI kernel, receipts, final assay, and reference composition
    coding_agent/       Agentvolve Level-1 solution evolution, independent checks, selected patch, and offline replay
```

Agent-specific CLI translation and its canonical commands have one implementation
owner under `connectors/fixed/`; generic Git identity and build mechanics remain
under `artifacts/git/`. Applications do not retain provider-specific aliases.

Add a package module only when a concrete responsibility no longer fits one of
these four. Do not introduce a generic abstraction in anticipation of future
work.

## Compatibility

Candidate Runner and Evolution Controller are repository-local source examples.
Application schema version 2 is additive: every schema version 1 request and
response remains supported, and existing default/skill direct-challenger and
proposal behavior is unchanged. `git-candidate-v1` and its adapter protocol
version 2 are additional artifact/execution forms; default and skill adapters
remain on protocol version 1. The Evolution Driver has a separate source-only
schema version 1 and no earlier state format to migrate. Population Archive also
has a separate source-only schema version 1 and no earlier ledger or SQLite
format to migrate; its generated index is disposable rather than a compatibility
authority. Population Driver has its own additive source-only schema version 1,
canonical driver ledger, pending-intent format, and immutable receipt format; it
reads the unchanged Population schema and never treats its SQLite index as
state authority. The source-only namespace and instruction refactor is internal:
public Controller/Population contracts, shared journal/transport mechanics, and
Population Driver replay/planner/effect/store modules preserve active owner
commands, canonical bytes, identities, ledgers, receipts, and process boundaries;
no state migration is introduced. Pi translations have canonical paths under
`connectors/fixed/pi`; obsolete provider aliases under applications and artifacts
are not retained. Prime Agent is an additive concrete connector over those
existing contracts. These application and connector changes do not change the
installed Python API, Metering JSON protocol, or numerical definitions.
Measurement-history schema version 2 is a
separate intentional storage break: Git commits replace schema-version-1
`objects/` storage, which requires the historical implementation for inspection.

This scope reset intentionally removes the previous hidden-fault world,
actions, policies, controller, calibration, reports, general trace/replay
system, artifact schemas, and their CLI commands. Existing run artifacts remain
usable only with a checkout of the historical implementation that created them.

There is no compatibility shim. Keeping one would retain the unrelated product
inside the new one and violate the one-purpose boundary.

## Agent-neutral metered evolution tools

Population Driver itself has no model runtime. It invokes caller-selected strict
commands and uses the existing Metering applications as measurement, evidence,
retention, and lineage tools. The concrete source-only Evolutionary Harness now
implements one provider-neutral bounded recursive runtime behind that command
boundary. Fixed connectors translate one model action for Pi and Prime Agent
without making either a package dependency.

The irreducible transition is one metered recurrence:

```text
challenger[n] = external_agent(parent[n], allowed_feedback[n])
generation[n] = controller(parent[n], challenger[n], evaluation[n])
parent[n + 1] = generation[n].next_parent
```

Controller continues to own ordering and validation within one generation; the
driver owns only recurrence between completed generations. The external harness
owns candidate search and the external trainer owns any weight update. The
implementation:

- evolves exactly one normalized artifact and one challenger per generation;
  checked-in connector paths support a complete non-executable `SKILL.md` or an
  immutable Git source/output descriptor;
- invokes a caller-pinned external agent through strict JSON with the current
  parent and caller-approved context, not protected evaluator cases or outcomes;
- advances the current parent only to the exact `next_parent` returned through
  Selection Gate;
- records a canonical hash-linked run header and completed Controller
  request/result pairs in a caller-selected local JSONL file;
- fails visibly on malformed, non-canonical, conflicting, or interrupted state;
- enforces generation and consecutive-rejection limits, checks the
  per-invocation wall-clock limit before each generation, and derives a bounded
  Controller timeout from proposer, runner, and evaluator timeouts, while token
  and monetary limits remain connector responsibilities;
- keeps selected artifacts run-local and performs no installation, deployment,
  training, or automatic rollback; and
- requires an untouched final evaluation for any broader improvement claim.

`connectors/fixed/pi/` and `connectors/fixed/prime_agent/` implement the same
skill-proposer, text-runner, Git-workspace, tool-free typed-harness mutator, and
one-action harness-model roles. Deterministic tests use fake model commands to
verify the strict translations and complete harness runtime contract.
`connectors/live_agent_acceptance.py` separately launches the real Pi
and Prime Agent CLIs and requires each model to invoke Metering as an internal
harness tool. That live check proves tool adoption for one request; it is not a
full candidate-improvement claim.

The existing Signal Relay acceptance remains a deliberately narrow real-Pi
proposal, development retention decision, and separate two-case final
comparison. Its final cases are loaded only after retention and never become
proposer feedback. Passing proves that exact constructed run and configuration,
not broad agent improvement; its deterministic fake-Pi regression remains the
CI-safe mechanism proof.

An external agent may propose or execute a candidate, but it never judges its
own retention. Task and safety evidence control selection. Forecast entropy and
target surprisal remain separately named calibration signals that may expose
uncertainty or blind spots; they are not a capability score and cannot move the
parent by themselves.

The single-head Evolution Driver itself has no recursive agent tree, candidate
population, learned mutation policy, database, event bus, plugin framework,
automatic global skill installation, training loop, or production deployment.
The separate Population Driver now composes Population allocation with bounded
Controller calls for Git candidates while preserving all six semantic owners.
It adds no learned policy, generic score, generic executor sandbox, installation,
training, or deployment; the typed Evolutionary Harness supplies its own narrow
OCI execution profile behind Candidate Runner. Schema-version-1 fixture behavior and schema-version-2 direct
challenger requests remain compatible. Candidate Runner, Mutator, Forecast
Assay, Selection Gate, Controller, and Observer split fixture-v1 and agent-v2
workflow code behind unchanged thin dispatchers. Population Driver separately
loads and verifies, plans one action, executes one effect, and stores through
explicit owner APIs. These are readability and dependency-direction changes,
not new semantic stages.

A CI-safe executable-Git recurrence test now creates a subtraction seed,
retains an addition descendant, allocates it as the next parent, rejects a
multiplication descendant, and verifies the resulting fresh archive and replay.
It establishes that exact deterministic mechanism for one trusted fixture only;
it does not establish live-model or general task-solving improvement.

## Coding-agent connector status and roadmap

**Status:** the least-privilege fixed profile is implemented for Pi and Prime
Agent, including the typed-harness proposer/model/runner translations. The
manifest-based full-context profile remains parked. The earlier live conformance
path proves that both installed harnesses can invoke Metering as an internal tool
for one request. Deterministic tests now additionally prove strict model-event
translation and the complete typed recursive runtime through a fake model; they
do not prove identical live end-to-end candidate improvement across providers.
Live OCI acceptance remains configuration-specific.

The goal is to let a concrete coding agent adopt this repository as an explicit
tool, create or execute one candidate through a narrow role boundary, and invoke
the frozen applications through documented public commands. “Adopt” does not
mean that the agent may rewrite the control plane, inspect protected assessment
material, judge itself, install a winner, train inside Metering, or rely on
ambient global memory.

This remains source-only. It adds no agent SDK, model provider, session runtime,
or connector API to the installed `metering` package.

### Connector cleanup and ownership

Every checked-in executable that translates between a coding-agent CLI and the
candidate protocols now has one implementation owner under:

```text
connectors/
    README.md
    tools/
        metering/
    fixed/
        README.md
        pi/
        prime_agent/
    full_context/
        README.md
```

The provider directories are concrete reviewed integrations, not dynamic
plugins. Do not add a registry, provider framework, import-time discovery, or a
common “agent” class. A connector remains an ordinary strict JSON subprocess
command. Shared `fixed/` modules own only identical request validation, prompts,
and process-response mechanics; provider files own explicit CLI construction.

Pi proposer/runner translations live at their canonical provider paths. Generic
Git clone, validation, build, identity, commit, and publication mechanics remain
under `artifacts/git/`; application schemas remain under `apps/`; mutation,
evaluation, measurement, selection, and recurrence did not move.

Source applications import canonical wire, standard-stream, subprocess, and
journal operations directly from the orthogonal modules under `apps/_support/`.
There is no aggregate transport facade or application-local provider launcher.

### Profile 1: fixed connector

`fixed-connector-v1` is the implemented least-privilege profile. Pi and Prime
Agent each expose a skill proposer, text-only candidate runner, Git-workspace
proposer, typed-harness whole-file mutator, one-action model transport, and
harness runner over the existing artifact boundary. A connector receives only
the data required for one declared role and returns one strict protocol response. It has:

- no implicit repository scan, discovered skills, context files, prior session,
  provider memory, or mutable global state;
- one runtime-pinned agent version, provider, model, reasoning, tool policy,
  command, timeout, image, and budget for typed harness runs;
- an explicit candidate and public task/context payload;
- canonical JSON input and strict, no-coercion output validation; and
- no evaluator secrets, selection authority, installation, or deployment
  capability.

Use this profile for reproducible comparisons and narrow production runners.
Typed harness runs additionally require the reviewed no-network OCI kernel and
external observations; historical workspace roles do not gain that isolation
implicitly. Provider-specific code may translate the fixed request into another
coding agent's public CLI boundary only after focused conformance tests; it must
not change Metering's candidate, evidence, or retention semantics. SDK embedding
is not part of the implemented profile.

### Profile 2: full-context connector

**Status: parked.** `full-context-connector-v1` is the proposed transparent
repository-adoption profile. It
receives a content-identified `agent-context-v1` manifest plus read-only access
to the referenced repository snapshot. The manifest exposes all *authorized*
information needed to understand and operate the metered-evolution tools,
not all information available to the trusted host.

At minimum the normalized manifest must identify:

- repository origin, immutable commit/tree/content digest, root, path inventory,
  and the read-only documentation/source/test entry points the agent may inspect;
- frozen control-plane version and the exact protocol/schema versions and public
  command arrays available as tools;
- current selected parent artifact, candidate axis, generation number, ledger
  chain head, approved aggregate feedback, and generation/rejection/wall-clock
  limits;
- caller-approved task and proposal context, evaluation-suite identity, outcome
  vocabulary, and the fact that protected cases or evidence are withheld;
- provider, model, reasoning, tool, sandbox, runtime, token, monetary, and
  compute configuration identities where the host can observe them;
- read-only, writable, temporary, and forbidden filesystem locations plus
  network and credential policy;
- allowed candidate paths and artifact/output receipt contracts;
- trusted commands the agent may invoke and the exact request/response documents
  expected by each; and
- explicit omitted or redacted categories so absence cannot be mistaken for an
  empty value.

The complete source need not be embedded in one huge prompt or JSON document.
The manifest should bind a read-only checkout and a finite path/digest index so a
coding agent can load files progressively with its normal tools. Required fields
must never be inferred from an installed agent's ambient configuration.

The context ID is the SHA-256 of canonical normalized manifest content. Every
agent action and connector response binds that context ID, selected-parent ID,
and ledger head. Resume rejects stale, conflicting, or tampered context rather
than silently combining it with a newer run. The candidate sees only a safe
state projection; the trusted ledger, hidden evaluator code, credentials,
one-use final suites, protected submissions, and disallowed per-case evidence
remain outside the manifest.

The full-context connector may help a coding agent read the repository, prepare
one candidate, and call the fixed control-plane tools. It does not become a
seventh semantic stage or an autonomous selector. Proposal still belongs to
Mutator, execution to Candidate Runner, evaluation to Observer, measurement to
Forecast Assay, retention to Selection Gate, one-generation ordering to
Controller, and recurrence to Evolution Driver.

### Provider conformance and evidence

The provider-neutral claim requires behavior, not a directory name. The fixed
profile currently has this implementation evidence:

1. deterministic fake-command tests send the same strict skill-proposer and
   text-runner requests through Pi and Prime Agent translations;
2. both Git-workspace translations run through the complete six-stage loop,
   promotion, hash-linked ledger, and resume path without network or paid-model
   access;
3. tests execute the canonical provider connector paths directly; and
4. an explicit live test launches real Pi and Prime Agent binaries, requires a
   native harness tool call, and verifies the exact Metering response.

Before claiming broad provider neutrality or implementing the full-context
profile, still require:

1. strict full-context fixtures for duplicate keys, extra keys, malformed
   output, timeout, stale state, context digest, and secret exclusion;
2. the same public context manifest and complete candidate/evidence path through
   Pi and at least one independently implemented non-Pi harness;
3. matched parent/challenger model, tool, budget, and runtime settings with a
   separate trusted evaluator;
4. one live promotion, one retention, interruption-safe resume, and rejection
   of attempts to alter the frozen control plane or read a forbidden path;
5. byte-identical pinned legacy outputs or an explicitly versioned additive
   migration; and
6. an unchanged wheel public API, dependency count, and package contents.

Any live result proves only that connector, agent version, model, tasks,
evaluator, and budget. It does not establish that every coding agent is
supported or that autonomous self-modification is safe. Production
full-context connectors still require a reviewed container or VM boundary and a
separate explicit operation to install or deploy a selected artifact.

## Git source and external-output boundary

**Status: implemented and tested.** The source-only `git-candidate-v1` bridge
binds immutable Git source and externally stored output receipts without adding
an installed package dependency or claiming candidate improvement.

The implemented evidence transition remains:

```text
propose one content-identified candidate
    -> execute parent and challenger under matched controls
    -> obtain independent task and safety evidence
    -> retain exactly one candidate
    -> persist the selected identity
```

A candidate descriptor binds an immutable repository commit, Git tree, portable
content SHA-256, entrypoint, and sorted external-output receipts. Branch names
are mutable publication conveniences and never candidate identity. Output
receipts bind caller-owned external artifacts by URI and SHA-256; Metering does
not create, interpret, store, install, or deploy those artifacts.

The trusted Controller, Observer, Forecast Assay, Selection Gate, and ledger
must not rewrite themselves. Adaptation happens in versioned, untrusted
artifacts at the edge. An external agent connected through a reviewed command
may create those artifacts, but it may not access the protected scorer, approve
its own candidate, install the winner, or alter the retention policy.

Executable candidates remain untrusted. The typed harness runs bootstrap and
cells in its reviewed Docker profile with no host credentials or evaluator
mount, no network, bounded writable storage/resources, and fixed matched
controls. Callers must supply an equivalent reviewed container or VM for every
other executable Git form. A path allowlist, digest checks, process cleanup, and
timeouts alone are not a sandbox.

Initially change one declared candidate axis per generation while freezing the
others. This preserves attribution and makes evaluator gaming easier to detect.
No environment-specific benchmark integration or model-training roadmap is part
of the accepted Metering scope.

## Acceptance criteria

The rewrite is complete only when:

- the four formulas match known exact values and independent identities;
- uniform distributions of 2 and 8 outcomes report 1 and 3 bits;
- independent variables report zero mutual information and a perfectly
  correlated fair binary pair reports one bit;
- KL identity, asymmetry, and infinite support mismatch are tested;
- every malformed input category in this plan is rejected;
- the Python public exports contain only the four measures and
  `ProbabilityError`;
- the CLI accepts every documented request, emits valid canonical JSON,
  represents infinity explicitly, and returns documented exit statuses;
- the history CLI records only accepted pairs as Git commits, distinguishes the
  pair tree from commit lineage identity, rejects dirty or malformed histories,
  and replays committed results during verification;
- direct calls and CLI calls agree for the same inputs;
- the core performs no filesystem or network access, does not modify input
  containers, and documents consumption of one-shot iterators;
- the four measurement functions and ordinary `metering` CLI have no runtime
  dependency, while the optional history command has no Python dependency and
  requires the documented `git` executable;
- no legacy world, policy, controller, agent, optimizer, benchmark, replay, or
  artifact implementation remains in the installed `metering` package;
- repository-local applications use only public Metering boundaries, make
  their caller-owned probability model explicit, and keep JSONL requests
  sequential with one flushed response per input line;
- identical canonical-JSON decoding, standard-stream serving, and one-shot
  subprocess mechanics in the composable stdin apps have one shared source
  owner, while app-specific schemas, independently copyable examples,
  mathematics, and error policy remain local;
- shared support imports no domain owner, cross-application imports use public
  contracts rather than private symbols, only compatibility entry points mutate
  `sys.path`, read-only Population Driver replay imports no durable stores, and
  installed Metering imports no source control-plane module; the documented
  Population Driver example matches its pre-refactor schema-v1 state manifest;
- the Mutator changes exactly one legal locus, uses an explicit caller-owned
  draw, and reports Metering entropy and selected-mutation self-information;
- Forecast Assay rejects unsupported schema versions and Selection Gate requires
  that same report version before recomputing both reports, rejecting mismatched
  evidence, and applying its documented strict threshold and infinity ordering;
- Candidate Runner verifies Mutator content identity, constructs a normalized
  result forecast without receiving the active fixture, and exposes its exact
  fixture probability model;
- the schema version 1 controller obtains both forecasts before each Observer
  reveal, carries Mutator content IDs through Forecast Assay and Selection Gate,
  and returns the selected candidate without claiming an autonomous loop;
- schema version 2 binds normalized default-agent, UTF-8 skill, or immutable Git
  source/output artifacts to content IDs and rejects escaping, duplicate,
  ambiguous, or non-UTF-8 paths, content, and output identities;
- schema version 2 runs parent and challenger adapters on identical case
  documents before a separate evaluator command receives either submission,
  rejects malformed adapter output and decimal tokens that collapse probability
  support during double-precision conversion, and terminates timed-out POSIX
  process groups rather than leaking ordinary descendants;
- the persistent schema-version-1 Observer session also terminates its POSIX
  process group on abort or shutdown timeout rather than leaving descendants;
- schema version 2 Forecast Assay verifies reported forecast entropy, recomputes
  target self-information, and keeps pass and safety evidence separately named;
- schema version 2 Selection Gate rejects a configured safety regression and
  requires the declared integer pass-count improvement rather than selecting on
  forecast calibration;
- the agent-skill controller returns only the parent or challenger artifact and
  performs no installation, repetition, or unsupported improvement claim;
- Mutator's proposal form gives a strict proposer only the parent and declared
  context, accepts exactly one replacement `SKILL.md` or Git descriptor, and
  preserves the direct caller-supplied challenger form;
- fixed Pi and Prime Agent connectors accept the same strict proposer and runner
  protocols, disable ambient state in tool-free roles, and keep provider CLI
  details outside the applications and installed package;
- generic Git proposal mechanics have one owner under `artifacts/git/`, while
  provider-specific workspace editing and canonical commands live under
  `connectors/fixed/`;
- the explicit live-agent acceptance launches both real harness commands,
  observes a native tool call, and verifies the exact Metering response without
  treating that one request as broad provider conformance;
- the evolution driver advances only from a completed Controller result, verifies
  its canonical hash-linked state before resume, stops at explicit limits, and
  never installs its selected head;
- Population Archive verifies a canonical hash-linked candidate/experiment/run
  ledger, requires unique replicate occurrence IDs, keeps final experiments out
  of archives, seals search transitions after final evaluation starts,
  recomputes named Metering evidence, and rejects stale archive allocations;
- its bounded Pareto archive excludes infeasible candidates, computes novelty
  against other feasible candidates rather than self, retains objectives
  separately without a generic weighted score, and selects uniform parents from
  canonical candidate order with an exact rational draw;
- typed skill recombination names the source parent for every complete file
  locus, requires meaningful contribution from both parents, reconstructs the
  child identity on replay, and rejects arbitrary Git candidate merging;
- deleting and rebuilding `population.sqlite` reproduces every indexed fact,
  changed rows fail independent verification, and archive, parent allocation,
  and Population Driver recurrence never read the database;
- Population Driver starts from the declared Git seed, uses each preceding exact
  Population allocation as the next Controller parent, records matched
  incumbent/challenger evidence and fresh archives, and stops at explicit round,
  proposal-call, resource, timeout-reservation, empty-archive, or final-seal
  limits without a generic score;
- a pending Population Driver intent without a valid Controller receipt never
  repeats an indeterminate model call through ordinary resume, explicit retries
  consume durable call/time reservations, and post-Controller adapter or partial
  Population recovery completes without another proposal call;
- Population Driver verification cross-checks canonical driver and Population
  ledgers plus immutable receipts, remains independent of SQLite, rejects receipt
  tampering, and cannot continue search after the first final-role run;
- the executable-Git Darwinian test promotes a real addition descendant from a
  subtraction seed, uses exact archive allocation for recurrence, rejects a
  multiplication regression, and replays the resulting archive without treating
  the fixture as general model-improvement evidence;
- `evolutionary-harness-v1` requires every one of its nine typed loci, canonical
  policies, complete file coverage, safe paths, exact content digests, valid
  bootstrap syntax, and a supported immutable dependency lock; host validation
  never imports or executes candidate Python;
- `evolutionary-harness-runtime-v1` derives one canonical identity from agent,
  provider/model/reasoning, immutable OCI image, command, dependency allowlist,
  limits, required observations, and cost semantics; Pi/Prime Agent version and
  model pins cannot silently disagree with it;
- kernel conformance proves boot, execute, interrupt, hard timeout, snapshot,
  restore, cleanup, restart recovery, and shutdown through the same ABI used by
  live runs; the unsafe process fixture is explicit and the live profile fails
  closed without Docker/cgroup-v2 observations;
- the fixed recursive loop enforces finite model, turn, execution, output,
  snapshot, delegate-call, and depth bounds; delegates receive independent
  contexts and kernels, provider tools remain disabled, and only the sandbox-side
  kernel server calls candidate `exec`/`eval`;
- content-addressed harness receipts bind candidate/task/manifest/runtime/
  transcript identities, model usage, external model and kernel observations,
  and separately named Population resource coordinates without inventing energy
  or GPU readings;
- the reference harness command performs mutation, isolated phenotype execution,
  independent development evaluation, Population recurrence, exact final
  allocation, protected final evaluation, permanent sealing, and offline
  Git/manifest/receipt/ledger verification with no caller-written adapter;
- the kernel coding-workspace ABI imports and exports only bounded canonical
  regular-file archives, rejects `.git`, traversal, symlinks, devices,
  disallowed writes, oversized state/output, timeout, and missing isolation, and
  never mounts or falls back to a host checkout;
- the Level-2 coding assay evolves real nine-locus harness descendants, evaluates
  returned workspaces in fresh kernels, records retained/rejected Population
  evidence, final-seals one selected harness, and replays its exact descriptor;
- `darwinian-coding-task-v1` binds immutable repository/base, allowed paths,
  reviewed development/protected argv checks, rational draws, and finite budgets;
  Level 1 creates only first-parent solution commits in run-local Git storage;
- every solution/check pair runs in a fresh OCI kernel, immutable mutation and
  execution receipts close exactly over candidate ancestry and authenticated
  Population runs, and protected cases remain absent until final allocation;
- coding final selection maximizes development task rate then reliability and
  uses the caller's exact draw only for canonical-ID ties, records the derived
  Population draw without a scalar score, and cannot recur after final reveal;
- a complete coding fixture returns a non-empty selected patch from an improved
  child while leaving the source repository unchanged, passes the protected
  suite, permanently seals Population, verifies with SQLite deleted, and rejects
  receipt, ancestry, path, selection, or patch tampering;
- the constructed live-Pi acceptance loads its final cases only after the
  development generation, never feeds them back to the proposer, and fails
  unless the exact selected head passes the declared development and final
  thresholds without a safety regression;
- `git-candidate-v1` binds an immutable commit, tree, portable content digest,
  entrypoint, and sorted external-output receipts; the Git bridge runs through
  the unchanged six semantic stages, rejects disallowed paths and digest
  tampering, persists only Selection Gate's winner, and leaves branch movement,
  sandboxing, artifact storage, installation, and deployment outside the core;
- the full test suite and package build pass.

## Source

Claude E. Shannon, “A Mathematical Theory of Communication,” *The Bell System
Technical Journal*, volume 27, pages 379-423 and 623-656, 1948.

- https://doi.org/10.1002/j.1538-7305.1948.tb01338.x
- https://doi.org/10.1002/j.1538-7305.1948.tb00917.x
