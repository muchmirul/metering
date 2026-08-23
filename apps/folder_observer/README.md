# Folder observer

Folder observer is a minimal application showing how an external agent can use
Metering around an observation loop. It is source-only example code, not part of
the installed `metering` package.

## Status

The current executable is a deterministic reference demo. It materializes one
of four fixture versions, chooses observations by maximum result entropy, and
runs until it identifies the active version.

The intended next boundary is smaller than a complete agent system: an external
agent chooses one observation at a time through a strict JSON Lines protocol,
while the application only observes, measures, and conditions its belief. That
agent protocol is specified in the mini-docs but is **not implemented yet**.

| Capability | Current demo | Agent-facing target |
|---|---|---|
| Versioned sandbox fixtures | Implemented | Retained |
| Tree and parent-bound snapshot IDs | Implemented | Retained |
| Metering through `python -m metering` | Implemented | Retained |
| Observation choice | Built-in maximum-entropy policy | External agent |
| Belief | Implicit uniform candidate set | Explicit version-probability map |
| Interaction | Complete automatic JSONL transcript | One JSON action and response at a time |
| Measurement history | Optional parent-linked ledger | Retained as an explicit caller choice |

## Run the current demo

From the repository root:

```bash
uv run python apps/folder_observer/observer.py --active v3
```

The output is canonical JSON Lines. With `v3`, the demo reads
`config/mode.txt`, narrows the candidates to `v3` and `v4`, reads
`service/port.txt`, and identifies `v3`.

To persist every Metering request/response pair made while choosing and applying
those observations:

```bash
history_dir="$(mktemp -d)"
uv run python apps/folder_observer/observer.py \
  --active v3 --history "$history_dir"
uv run metering-history log "$history_dir"
uv run metering-history verify "$history_dir"
```

The history is opt-in and caller-owned. The ordinary run remains ephemeral.

The four fixture directories are immutable versions of one UTF-8 text sandbox.
Each version has:

- a `tree_id` derived from canonical paths and file bytes; and
- a `snapshot_id` derived from its `tree_id` and parent snapshot ID.

The current model is uniform. If `k` of `n` remaining versions produce a given
observation result, the application assigns that result probability `k / n`.
It asks Metering for the entropy of predicted results and the self-information
of the result that occurs. Candidate filtering belongs to this application, not
to Metering.

## Mathematical foundation and hypothesis

The current demo is **finite, noiseless Bayesian hypothesis identification
with greedy Shannon-entropy query selection**. A deterministic probe partitions
the candidate versions by result. Because its result is fixed by the active
version, result entropy equals mutual information and the expected one-step
reduction in candidate entropy under the declared model. The loop therefore
selects the probe with maximum result entropy.

The implemented-system hypothesis is:

> Given an active sandbox exactly equal to one of `v1` through `v4`, a uniform
> prior, deterministic noiseless reads, and the current fixed fixtures, the
> reference policy identifies the correct snapshot in exactly two delivered
> read observations, and every selected probe maximizes current result entropy.

For these fixtures, candidate entropy must follow `2 -> 1 -> 0` bits and each
delivered result must have probability `0.5` and surprisal `1` bit. This is a
falsifiable claim about the reference fixture, not a claim about realistic
folders, agent intelligence, or global query optimality. See [Mathematical
foundation and hypothesis](docs/theory-and-hypothesis.md) for the derivation,
assumptions, falsifiers, and primary research sources.

## Mini-docs

- [Architecture](docs/architecture.md) defines the irreducible roles, state,
  probability model, and version boundary.
- [Mathematical foundation and hypothesis](docs/theory-and-hypothesis.md)
  identifies the current demo as finite noiseless Bayesian hypothesis
  identification, derives its entropy rule, states its falsifiable hypothesis,
  and records the assumptions that limit the result.
- [Agent protocol](docs/agent-protocol.md) defines the minimal proposed JSONL
  interface and clearly separates it from current behavior.

## Files

```text
folder_observer/
    observer.py       current deterministic reference demo
    versions.json     ordered fixture lineage
    fixtures/         immutable sandbox versions
    docs/              architecture, theory, hypothesis, and agent protocol
```

## Boundaries

- This is not an agent, planner, filesystem watcher, or general version-control
  system.
- Version names cannot escape `fixtures/`, fixture roots cannot be symlinks,
  and malformed parent values fail explicitly.
- Read probes accept only normalized relative paths and reject symbolic-link
  traversal. UTF-8 decoding preserves the file's original line endings.
- Identification is emitted only when the canonical sandbox file manifest
  matches the selected snapshot's `tree_id`, so extra or changed files fail
  instead of being ignored.
- The temporary directory is cooperative isolation, not a security sandbox.
- `--active` is reproducible controller configuration, not a protected secret
  from the person starting the process.
- Snapshot hashes are identifiers, not signatures or authentication.
- The reported bits do not measure file meaning, usefulness, correctness,
  understanding, or whether an agent used the observation.
- Observation evolution is outside the initial loop. A changed observation
  catalogue must become a new immutable version rather than silently mutating a
  running session.
- Measurement records version exact JSON pairs, not the sandbox itself. Folder
  snapshot IDs and measurement record IDs have different meanings.
