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

`metering-history` is an explicit, filesystem-writing wrapper around the public
`metering` command. The ordinary Python functions and `metering` command never
enable it implicitly. Recording one request is deliberate:

```bash
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | metering-history record PATH
```

The wrapper first asks `metering` to validate and measure the request. A rejected
request leaves the history untouched. An accepted request and its exact response
form a pair with these two identities:

```text
pair_id = SHA-256(canonical JSON of {
    "request": normalized request,
    "response": exact Metering response
})

record_id = SHA-256(canonical JSON of the complete six-field stored record)
```

`pair_id` is content identity: the same normalized request and response have the
same pair ID. `record_id` is history identity: appending the same pair at a new
place in the lineage produces a new record ID. Each immutable object contains
exactly `schema_version`, `metering_version`, `pair_id`, `parent_record_id`,
`request`, and `response`. `HEAD` points to the latest record. Objects and `HEAD`
are canonical UTF-8 JSON or lowercase SHA-256 text, respectively.

The complete command surface is:

```text
metering-history record PATH   read one Metering request and append its pair
metering-history log PATH      emit HEAD and reachable records, newest first
metering-history verify PATH   verify hashes, links, canonical form, and reachability
```

Successful commands emit one canonical JSON object. Storage or integrity failures
emit `invalid_history` through the same `error.code` and `error.message` envelope
and exit with status two. Measurement request failures preserve the error produced
by `metering` and do not create storage.

This is a linear local ledger, not a general version-control system. It has no
branches, merges, remotes, tags, checkout, signing, wall-clock metadata, or
automatic replay. Hash verification detects accidental modification and broken
lineage; it does not authenticate who created a record or prove that a stored
response was produced by trusted software. A stale `LOCK` directory after an
interrupted writer must be inspected and removed by the caller.

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
binding, finite timeouts, and report alignment. Adapter implementations own
agent invocation, hidden verifiers, workspace isolation, model and tool
settings, token or monetary budgets, and the meanings of `passed` and
`safety_passed`. The checked-in demo adapters are deterministic protocol test doubles. The
concrete text-only Pi runner and proposer disable tools and discovered
resources, then inject only the verified candidate `SKILL.md`; neither is a
coding sandbox or empirical evidence of improvement. Other agents may implement
the same external protocols without becoming Metering dependencies.

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
    history.py        explicit content-addressed measurement ledger
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
docs/
    README.md
    foundations.md
    theory.md
    history.md
    evolution-kernel.md
    agent-evolution.md
artifacts/
    git/              external Git source/model-output candidate bridge
apps/
    README.md         application index and composition boundary
    agent_protocol.py shared source-only agent artifact and adapter validation
    stdio_connector.py shared strict JSON decoding, stdio, and subprocess mechanics
    observer/         fixture observer and trusted task-evaluator boundary
    forecast_assay/   forecast and task-evidence assay
    mutator/          finite-genome mutator and skill-artifact binder
    candidate_runner/ fixture model and external-agent adapter boundary
    selection_gate/   forecast and task-capability retention policies
    controller/       fixture and agent-skill one-generation orchestrator
    evolution_driver/ bounded run-local recurrence over selected SKILL.md artifacts
```

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
earlier state format to migrate. These application changes do not change the
installed Python API, Metering JSON protocol, history schema, or numerical
definitions.

This scope reset intentionally removes the previous hidden-fault world,
actions, policies, controller, calibration, reports, general trace/replay
system, artifact schemas, and their CLI commands. Existing run artifacts remain
usable only with a checkout of the historical implementation that created them.

There is no compatibility shim. Keeping one would retain the unrelated product
inside the new one and violate the one-purpose boundary.

## Bounded Pi self-evolution

The implemented source-only driver uses Pi through a strict proposer adapter and
the existing Metering applications as its measurement and retention core. Prime
Agent was a design reference only and is not a dependency.

The irreducible transition is one metered recurrence:

```text
challenger[n] = propose_with_pi(parent[n], allowed_feedback[n])
generation[n] = controller(parent[n], challenger[n], evaluation[n])
parent[n + 1] = generation[n].next_parent
```

Controller continues to own ordering and validation within one generation; the
driver owns only recurrence between completed generations. The implementation:

- evolves exactly one normalized artifact and one challenger per generation;
  checked-in proposers support a complete non-executable `SKILL.md` or an
  immutable Git source/output descriptor;
- invokes a pinned Pi proposer through strict JSON with the current parent and
  caller-approved context, not protected evaluator cases or outcomes;
- advances the current parent only to the exact `next_parent` returned through
  Selection Gate;
- records a canonical hash-linked run header and completed Controller
  request/result pairs in a caller-selected local JSONL file;
- fails visibly on malformed, non-canonical, conflicting, or interrupted state;
- enforces generation and consecutive-rejection limits, checks the
  per-invocation wall-clock limit before each generation, and derives a bounded
  Controller timeout from the proposer, runner, and evaluator timeouts, while
  token and monetary limits remain adapter
  responsibilities because only adapters can observe them;
- keeps selected artifacts run-local and performs no installation, deployment,
  or automatic rollback; and
- requires an untouched final evaluation for any broader improvement claim.

The checked-in Signal Relay acceptance command exercises one real Pi proposal,
one development retention decision, and a separate two-case final comparison.
The final cases are loaded only after retention and never become proposer
feedback. Passing proves this exact constructed run and configuration, not broad
agent improvement; its deterministic fake-Pi regression remains the CI-safe
mechanism proof.

Pi may propose or execute a candidate, but it never judges its own retention.
Task and safety evidence control selection. Forecast entropy and target
surprisal remain separately named calibration signals that may expose
uncertainty or blind spots; they are not a capability score and cannot move the
parent by themselves.

The driver has no recursive agent tree, candidate population, learned mutation
policy, database, event bus, plugin framework, automatic global skill
installation, or production deployment. The six semantic boundaries remain
separate. Schema-version-1 fixture behavior and schema-version-2 direct
challenger requests remain compatible; internal Controller and Observer modules
are split by workflow only to keep unrelated mechanisms readable.

## Provider-neutral coding-agent connector roadmap

**Status:** parked; no connector reorganization or full-context protocol is
implemented yet. The current concrete model integrations remain Pi-specific,
and Prime Agent remains a design reference rather than a dependency. Do not
claim support for another coding agent until its connector passes the same
end-to-end evidence path.

The goal is to let an arbitrary coding agent adopt this repository as an
explicit tool: inspect the complete authorized implementation context, identify
the selected parent and bounded run state, create or execute one candidate, and
invoke the frozen applications through documented public commands. “Adopt” does
not mean that the agent may rewrite the control plane, inspect protected
assessment material, judge itself, install a winner, or rely on ambient global
memory.

This remains source-only. It must not add agent SDKs, model providers, sessions,
or connector APIs to the installed `metering` package.

### Connector cleanup and ownership

When this roadmap is activated, put every checked-in executable that translates
between a coding-agent runtime and the self-evolution protocols under one
source-only top-level directory with two explicit profiles:

```text
connectors/
    README.md
    fixed/
        README.md
        pi/
        AGENT_NAME/
    full_context/
        README.md
        context_manifest/
        pi/
        AGENT_NAME/
```

The names under `AGENT_NAME` are concrete reviewed integrations, not dynamic
plugins. Do not add a registry, provider framework, import-time discovery, or a
common “agent” class. A connector is still an ordinary strict JSON subprocess
command.

The cleanup should move the current Pi proposer/runner translations and the Git
candidate runtime translation to the appropriate connector profile without
moving mutation, evaluation, measurement, selection, recurrence, Git identity,
or artifact-store semantics out of their existing owners. Git object and output
identity helpers remain under `artifacts/`; application schemas remain under
`apps/`; deterministic agent/evaluator doubles become clearly named test
fixtures rather than production connectors.

`apps/stdio_connector.py` currently owns generic transport mechanics rather than
an agent connector. In the reviewed control-plane release that performs this
cleanup, rename it to make that distinction explicit or document why the name is
retained. Preserve one implementation owner for canonical JSON, subprocess, and
timeout mechanics; do not copy those functions into each provider directory.
Existing frozen commits remain valid, and any old source command retained for
compatibility must be a thin launcher rather than a second implementation.

### Profile 1: fixed connector

`fixed-connector-v1` is the least-privilege profile corresponding to the current
Pi-style adapters. It receives only the data required for one declared role—such
as proposing one challenger or running one candidate on one public task—and
returns one strict protocol response. It has:

- no implicit repository scan, discovered skills, context files, prior session,
  provider memory, or mutable global state;
- one caller-pinned agent, model, tool policy, command, timeout, and budget;
- an explicit candidate and public task/context payload;
- canonical JSON input and strict, no-coercion output validation; and
- no evaluator secrets, selection authority, installation, or deployment
  capability.

Use this profile for reproducible comparisons and narrow production runners.
Provider-specific code may translate the fixed request into Pi, Prime Agent, or
another coding agent's public CLI/SDK boundary, but it must not change Metering's
candidate, evidence, or retention semantics.

### Profile 2: full-context connector

`full-context-connector-v1` is the transparent repository-adoption profile. It
receives a content-identified `agent-context-v1` manifest plus read-only access
to the referenced repository snapshot. The manifest exposes all *authorized*
information needed to understand and operate the self-evolution implementation,
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

The provider-neutral claim requires behavior, not a directory name. Before this
roadmap moves from parked to implemented:

1. Define strict fixtures for both connector profiles, including duplicate-key,
   extra-key, malformed-output, timeout, stale-state, context-digest, and secret-
   exclusion failures.
2. Preserve deterministic fake-agent tests that exercise the complete six-stage
   loop and ledger resume without network or paid-model access.
3. Prove the same public context manifest and control-plane commands with Pi and
   at least one independently implemented non-Pi coding agent. Prime Agent may
   serve as that second integration only if its reviewed public boundary fits;
   it is not privileged by the design.
4. Run parent and challenger with matched agent/model/tool/budget settings and a
   separate trusted evaluator. A coding agent may propose or execute both sides
   but may not evaluate or retain itself.
5. Demonstrate one promotion, one retention, interruption-safe resume, and
   rejection of a connector that attempts to alter the frozen control plane or
   read a forbidden path.
6. Verify that existing schema-version-1, skill schema-version-2, and Git
   candidate outputs remain byte-identical for pinned requests, or release an
   explicitly versioned additive migration with exact compatibility evidence.
7. Keep the wheel public API, dependency count, and package contents unchanged.

Any live result proves only that connector, agent version, model, context
manifest, tasks, evaluator, and budget. It does not establish that every coding
agent is supported or that autonomous self-modification is safe. Production
full-context connectors still require a reviewed container or VM boundary and a
separate explicit operation to install or deploy a selected artifact.

## Environment harness and model evolution roadmap

**Status:** the general Git source/output substrate is implemented and tested;
ARC-AGI-3 integration and real Unsloth/Qwen training remain parked. The Git
bridge is source-only and adds no installed package dependency or improvement
claim.

The intended general-purpose core remains the fixed evidence transition:

```text
propose one content-identified candidate
    -> execute parent and challenger under matched controls
    -> obtain independent task and safety evidence
    -> retain exactly one candidate
    -> persist the selected identity
```

The trusted Controller, Observer, Forecast Assay, Selection Gate, and ledger
must not rewrite themselves. Adaptation happens in versioned, untrusted
artifacts at the edge. Pi may create those artifacts, but it may not access the
protected scorer, approve its own candidate, install the winner, or alter the
retention policy.

### Phase 1: prove skill evolution in an interactive environment

Use the existing single-`SKILL.md` evolution unchanged against one concrete
ARC-AGI-3 runner. The environment adapter and official scorer remain fixed and
reviewed. Parent and challenger receive identical environment versions, seeds,
action limits, model settings, and compute budgets. Each case records a complete
trajectory; `passed` means the official environment was solved, while
`safety_passed` means the run respected declared action, budget, and isolation
constraints. A separately reserved final suite is required. This phase tests
whether the current skill mechanism transfers beyond text without yet evolving
executable harness code.

### Phase 2: evolve an environment harness

The additive `git-candidate-v1` descriptor and `artifacts/git/` bridge implement
the smallest general source boundary without an environment registry. A
candidate binds an immutable repository commit, Git tree, portable SHA-256 over
paths/modes/blobs, entrypoint, and external output receipts. Branch names are
publish/audit conveniences and never candidate identity. Pi's builder may
receive the parent harness, public SDK documentation, public practice
environments, and visible contract-test failures. It must not receive protected
cases, scorer code, credentials, or retained outcomes beyond an approved
aggregate. The deterministic and live demos prove Git adapter-source mutation,
not ARC-AGI-3 performance.

Executable harness candidates are untrusted. Run them only in disposable
containers or VMs with no host credentials, evaluator mount, or network by
default; read-only SDK inputs; bounded writable storage; CPU, memory, action,
token, monetary, and wall-clock limits; and complete filesystem and action
traces. Contract and isolation checks run before task evaluation. A failed,
timed-out, malformed, or interrupted candidate never becomes the selected
harness. Selection remains run-local until a separate explicit installation
operation.

Do not evolve the strategy skill and harness in the same initial generation.
Freeze the skill while comparing harnesses, then freeze the selected harness
while comparing skills. Changing one component at a time preserves causal
attribution and makes evaluator gaming easier to detect.

### Phase 3: evolve a trained model candidate

The Git proposer now supports an optional fixed build/training command that
returns content-addressed external output receipts. The deterministic worker
proves that a model-checkpoint receipt is bound into candidate identity and
verified by a fixed executor; it does not train a useful model. After the
environment boundary is proven, connect the same contract to an external GPU
training worker. The initial live implementation target is the user-selected
Unsloth Qwen training path documented at:

- https://unsloth.ai/docs/models/qwen3.8/train

This link is a candidate implementation reference, not a current dependency or
validated protocol. Review and pin the exact model, Unsloth release, license,
training API, and hardware requirements before implementation.

A model candidate must bind at least the immutable base-model identifier,
parent checkpoint or adapter identifier, tokenizer and chat template, exact
training code and configuration, dataset-manifest hashes and licenses, random
seeds, dependency lock, hardware/runtime description, and produced checkpoint
hash. Large datasets and weights stay in an external artifact store; the
Metering ledger records identities and evidence, not model files. Training
workers receive no protected evaluator assets or deployment credentials.

One generation changes one declared axis. Initially, freeze the environment
harness and strategy skill while producing a challenger model from the parent
checkpoint. Compare parent and challenger with identical inference settings,
tasks, seeds where applicable, token limits, and compute budgets. Task and
safety evidence continue to control retention; forecast entropy and surprisal
remain calibration evidence only. Because training and inference are
stochastic, predeclare seeds and repeat counts and report dispersion rather than
promoting from one lucky run.

The eventual composite execution identity is conceptually:

```text
candidate = (model_id, strategy_skill_id, environment_harness_id,
             runner_configuration_id)
```

Do not add this abstraction to the protocol until the ARC harness and one model
training experiment prove that all four identities are necessary. During early
experiments, freeze three components and mutate only the fourth.

Before either deferred phase is accepted, require a reviewed sandbox threat
model, official environment or training interfaces, fixed baselines, matched
budgets, data provenance, interruption-safe external artifact writes, rollback,
deterministic protocol doubles, repeated live trials, and a one-use final
evaluation. No generated harness or checkpoint may automatically replace a
host adapter, installed Pi skill, served model, or production deployment.

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
- the history CLI records only accepted pairs, distinguishes pair identity from
  lineage identity, and detects corrupt or unreachable objects;
- direct calls and CLI calls agree for the same inputs;
- the core performs no filesystem or network access, does not modify input
  containers, and documents consumption of one-shot iterators;
- the package has no runtime dependency;
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
  source/output artifacts to content IDs and rejects escaping, duplicate, or
  ambiguous paths and output identities;
- schema version 2 runs parent and challenger adapters on identical case
  documents before a separate evaluator command receives either submission,
  rejects malformed adapter output, and terminates timed-out POSIX process
  groups rather than leaking ordinary descendants;
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
