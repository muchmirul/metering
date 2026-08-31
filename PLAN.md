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

Repository-local evolution applications and connectors are also tools around
external agents, not a competing agent harness. External agents propose or
execute harness, adapter, and model-output candidates. External trainers produce
weights. Metering validates declared probability models, binds candidate and
evidence identity, measures named quantities, applies explicit source-only
retention rules, and records selected lineage. It never generates a refined
harness or trains model weights itself.

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
repetition, installation, deployment, rollback, or stopping rule. A caller or
the explicit source-only evolution driver must submit another request to advance
another generation. Installation of `next_parent` always remains a separate
caller-approved operation.

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
    agent_protocol.py shared source-only agent artifact and adapter validation
    stdio_connector.py shared strict JSON decoding, stdio, and subprocess mechanics
    observer/         fixture observer and trusted task-evaluator boundary
    forecast_assay/   forecast and task-evidence assay
    mutator/          schema-v1 genome mutation plus schema-v2 artifact mutation
    candidate_runner/ fixture model and external-agent adapter boundary
    selection_gate/   schema-specific forecast/task retention implementations
    controller/       fixture and agent-skill one-generation orchestrator
    evolution_driver/ bounded run-local recurrence over selected SKILL.md artifacts
```

Historical Pi scripts under `apps/` and `artifacts/git/` are thin compatibility
launchers. Agent-specific CLI translation has one implementation owner under
`connectors/fixed/`; generic Git identity and build mechanics remain under
`artifacts/git/`.

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
schema version 1 and no
earlier state format to migrate. Moving Pi translations to `connectors/fixed/pi`
is source-path cleanup only: the former script paths remain compatibility
launchers with the same standard-stream contracts. Prime Agent is an additive
concrete connector over those existing contracts. These application and
connector changes do not change the installed Python API, Metering JSON
protocol, or numerical definitions. Measurement-history schema version 2 is a
separate intentional storage break: Git commits replace schema-version-1
`objects/` storage, which requires the historical implementation for inspection.

This scope reset intentionally removes the previous hidden-fault world,
actions, policies, controller, calibration, reports, general trace/replay
system, artifact schemas, and their CLI commands. Existing run artifacts remain
usable only with a checkout of the historical implementation that created them.

There is no compatibility shim. Keeping one would retain the unrelated product
inside the new one and violate the one-purpose boundary.

## Agent-neutral metered evolution tools

The implemented source-only driver has no model runtime. It invokes a
caller-selected strict proposer command and uses the existing Metering
applications as measurement, evidence, retention, and lineage tools. Concrete
fixed connectors translate the same request for Pi and Prime Agent without
making either a package dependency.

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
skill-proposer, text-runner, and Git-workspace roles. Deterministic tests use
fake model commands to verify both translations through the same strict
protocols. `connectors/live_agent_acceptance.py` separately launches the real Pi
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

The driver has no recursive agent tree, candidate population, learned mutation
policy, database, event bus, plugin framework, automatic global skill
installation, training loop, or production deployment. The six semantic
boundaries remain separate. Schema-version-1 fixture behavior and
schema-version-2 direct challenger requests remain compatible; internal
Controller and Observer modules are split by workflow only to keep unrelated
mechanisms readable.

## Coding-agent connector status and roadmap

**Status:** the least-privilege fixed profile is implemented for Pi and Prime
Agent. The manifest-based full-context profile remains parked. The implemented
live conformance path proves that both installed harnesses can invoke Metering as
an internal tool for one request; deterministic tests prove both concrete
translations against the proposer, text-runner, and Git-workspace protocols.
This does not yet prove identical live end-to-end candidate improvement across
providers. Connector conformance and adoption remain the current priority.

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

Pi proposer/runner translations moved behind compatibility launchers. Generic
Git clone, validation, build, identity, commit, and publication mechanics remain
under `artifacts/git/`; application schemas remain under `apps/`; mutation,
evaluation, measurement, selection, and recurrence did not move.

`apps/stdio_connector.py` retains its name because it owns generic transport
mechanics used by the source applications, not agent translation. Renaming it
would churn every application without clarifying the new top-level connector
boundary. It remains the single owner for canonical JSON, standard streams,
subprocess timeouts, and process-group cleanup. Historical source commands are
thin launchers rather than second implementations.

### Profile 1: fixed connector

`fixed-connector-v1` is the implemented least-privilege profile. Pi and Prime
Agent each expose a skill proposer, text-only candidate runner, and Git-workspace
proposer over the existing protocol versions. A connector receives only the data
required for one declared role and returns one strict protocol response. It has:

- no implicit repository scan, discovered skills, context files, prior session,
  provider memory, or mutable global state;
- one caller-pinned agent, model, tool policy, command, timeout, and budget;
- an explicit candidate and public task/context payload;
- canonical JSON input and strict, no-coercion output validation; and
- no evaluator secrets, selection authority, installation, or deployment
  capability.

Use this profile for reproducible comparisons and narrow production runners.
Provider-specific code may translate the fixed request into another coding
agent's public CLI boundary only after focused conformance tests; it must not
change Metering's candidate, evidence, or retention semantics. SDK embedding is
not part of the implemented profile.

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
3. historical Pi source paths execute the moved implementation through thin
   compatibility launchers; and
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

Executable candidates remain untrusted. Callers must run them in a reviewed
container or VM boundary with no host credentials or evaluator mount, restricted
network access, bounded writable storage and resources, and fixed matched
execution controls. The repository's path allowlist, digest checks, and process
timeouts are not a sandbox.

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
  provider-specific workspace editing lives under `connectors/fixed/` and old Pi
  commands remain thin compatibility launchers;
- the explicit live-agent acceptance launches both real harness commands,
  observes a native tool call, and verifies the exact Metering response without
  treating that one request as broad provider conformance;
- the evolution driver advances only from a completed Controller result, verifies
  its canonical hash-linked state before resume, stops at explicit limits, and
  never installs its selected head;
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
