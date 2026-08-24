# Observer

Observer is a minimal application showing how an external agent can use
Metering around an observation loop. It is source-only example code, not part of
the installed `metering` package.

## Status

The executable has two modes over the same four immutable fixtures:

- the default deterministic reference demo chooses observations by maximum
  result entropy and runs to identification; and
- `--jsonl` runs one stateful session in which an external agent chooses each
  observation through the implemented version 1 protocol.

| Capability | Reference demo | External-agent JSONL |
|---|---|---|
| Versioned sandbox fixtures | Implemented | Same fixtures |
| Tree and parent-bound snapshot IDs | Implemented | Verified by `finish` |
| Metering through `python -m metering` | Implemented | Implemented |
| Observation choice | Built-in maximum-entropy policy | External agent |
| Belief | Uniform candidate set | Explicit version-probability response |
| Interaction | Complete automatic JSONL transcript | One request and response per line |
| Measurement history | Optional parent-linked ledger | Optional with `--history` |

## Run the current demo

From the repository root:

```bash
uv run python apps/observer/observer.py --active v3
```

`--active` accepts `v1` through `v4` and defaults to `v1`. `--history PATH`
enables the explicit measurement ledger, `--jsonl` switches to the external
agent protocol, and `-h`/`--help` prints command help. Option abbreviations are
rejected.

The output is canonical JSON Lines. With `v3`, the demo reads
`config/mode.txt`, narrows the candidates to `v3` and `v4`, reads
`service/port.txt`, and identifies `v3`.

To persist every Metering request/response pair made while choosing and applying
those observations:

```bash
history_dir="$(mktemp -d)"
uv run python apps/observer/observer.py \
  --active v3 --history "$history_dir"
uv run metering-history log "$history_dir"
uv run metering-history verify "$history_dir"
```

The history is opt-in and caller-owned. The ordinary run remains ephemeral.

## Run an external-agent session

Start a persistent JSONL session with:

```bash
uv run python apps/observer/observer.py --jsonl --active v3
```

Write one `state`, `observe`, or `finish` action per input line. The process
flushes one canonical response per line and keeps recoverable request errors in
that response stream. For example:

```jsonl
{"action":"state"}
{"action":"observe","probe":{"operation":"read","path":"config/mode.txt"}}
```

The agent chooses probes; Observer owns the sandbox, result-distribution
construction, Metering calls, belief conditioning, and final tree verification.
The repository [Evolution Controller](../controller/README.md) demonstrates
capturing two Candidate Runner forecasts before each `observe` action. See the
[external-agent protocol](docs/agent-protocol.md) for exact schemas, ordering
rules, errors, and completion behavior.

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
- [Agent protocol](docs/agent-protocol.md) defines the implemented version 1
  JSONL interface and separates agent policy from controller behavior.

## Files

```text
observer/
    observer.py       reference demo and external-agent JSONL session
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
  traversal. JSONL actions are further restricted to the immutable advertised
  catalogue. UTF-8 decoding preserves the file's original line endings.
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
