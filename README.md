# Metering

Metering is a small, deterministic tool for measuring information in finite
discrete probability distributions.

It implements four named measures:

- self-information;
- Shannon entropy;
- Kullback-Leibler divergence;
- mutual information.

That is the entire measurement surface. Metering does not run agents, choose
actions, estimate probabilities, update beliefs, rank systems, or interpret
meaning. The caller supplies the probability model; Metering validates it and
returns a number. A separate opt-in command can retain accepted measurement
request/response pairs without changing that surface.

[`PLAN.md`](PLAN.md) is the normative contract. [`docs/theory.md`](docs/theory.md)
explains why the measures stay separate.

## Install

Metering requires Python 3.11 or newer and has no runtime dependencies. From a
checkout with [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync --extra test
```

## Python API

```python
from metering import entropy, kl_divergence, mutual_information, self_information

print(self_information(0.125))
print(entropy([0.5, 0.5]))
print(kl_divergence([0.5, 0.5], [0.75, 0.25]))
print(mutual_information([[0.5, 0.0], [0.0, 0.5]]))
```

```text
3.0
1.0
0.2075187496394219
1.0
```

Base 2 is the default, so these values are bits. Pass `base=math.e` for nats or
another real value that converts to a finite float greater than one.

Inputs must already be normalized probability distributions. Metering rejects
bad input instead of guessing what the caller intended:

```python
from metering import ProbabilityError, entropy

try:
    entropy([1, 1, 2])
except ProbabilityError as error:
    print(error)
```

It does not silently turn counts into probabilities.

## Agent and shell tool

The `metering` command is a strict JSON filter. This is the integration point
for other agents: JSON goes in through standard input and JSON comes out through
standard output.

```bash
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering
```

```json
{"base":2.0,"infinite":false,"measure":"entropy","value":1.0}
```

The four request forms are:

```json
{"measure":"self_information","probability":0.125}
{"measure":"entropy","probabilities":[0.5,0.5]}
{"measure":"kl_divergence","p":[0.5,0.5],"q":[0.75,0.25]}
{"measure":"mutual_information","joint":[[0.5,0.0],[0.0,0.5]]}
```

Add `"base":2` to any request to set the logarithm base explicitly.

Successful responses always contain exactly `base`, `infinite`, `measure`, and
`value`. Since JSON has no legal infinity number, an infinite mathematical
result uses `"infinite":true` and `"value":null`:

```bash
printf '%s\n' '{"measure":"self_information","probability":0}' \
  | uv run metering
```

```json
{"base":2.0,"infinite":true,"measure":"self_information","value":null}
```

Bad JSON, command-line arguments, unknown or extra keys, duplicate keys,
invalid bases, and invalid probability models exit with status 2 and emit one
JSON error on standard error:

```json
{"error":{"code":"invalid_probability","message":"probabilities must sum to 1 within 1e-12; got 2"}}
```

The object has exactly `error.code` and `error.message`. The code is
`invalid_request` for JSON, command-line, or envelope errors and
`invalid_probability` for a rejected probability model or base. The only
options are `-h`/`--help` and `--version`; abbreviations are rejected.

The command handles one request per process. It does not access application
files, call a network service, load a model, or choose which measure to run.

## Versioned measurement history

`metering-history` is the explicit filesystem-writing boundary. It wraps the
ordinary `metering` command and appends only successful request/response pairs:

```bash
history_dir="$(mktemp -d)"
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering-history record "$history_dir"
```

The result contains the normalized request, exact Metering response, package
version, `pair_id`, `parent_record_id`, and `record_id`. The pair ID identifies
the request/response content. The record ID also binds that pair to its parent,
so repeated pairs at different positions remain distinct history records.

Inspect newest-first history or check its structural integrity with:

```bash
uv run metering-history log "$history_dir"
uv run metering-history verify "$history_dir"
```

The directory contains an immutable object per record and a `HEAD` pointer.
Writes are serialized with a `LOCK` directory and update `HEAD` atomically. An
invalid Metering request does not create or advance the history. A process killed
during a write may leave a stale `LOCK`; inspect the directory before removing
that lock.

This is deliberately smaller than Git. It is one local linear lineage, with no
branches, merges, remotes, tags, checkout, signatures, timestamps, or automatic
replay. `verify` checks canonical encoding, hashes, parent links, and
reachability. Hashes detect modification; they do not authenticate the author or
prove that trusted software created an object.

## Example application: folder observer

[`apps/folder_observer`](apps/folder_observer) is a small application that
demonstrates Metering as a subprocess tool. Four immutable fixture directories
represent versions of one sandbox. The observer starts with a uniform
distribution over those versions, predicts the possible results of listing or
reading the sandbox, and asks Metering to measure each result distribution.

Run the deterministic demonstration with:

```bash
uv run python apps/folder_observer/observer.py --active v3
```

Add `--history PATH` to append every Metering call made by the observer to one
measurement history. Without the flag, the observer creates no persistent
state.

The application chooses the observation with the greatest result entropy,
observes the materialized sandbox, filters the candidate versions itself, and
repeats until one version remains. It prints canonical JSON Lines containing
the explicit probability requests and Metering responses.

The version fixtures, inference rule, snapshot hashes, action choice, and loop
belong to the application. None of them is part of the `metering` package. The
reported bits describe the application's declared finite model; they do not
measure the meaning or usefulness of the files.

## Example application: mutagenesis

[`apps/mutagenesis`](apps/mutagenesis) is a small agent-facing adapter, not an
autonomous evolution system. An agent supplies an opaque candidate identifier
and the candidate model's probability for each caller-declared target outcome.
The adapter uses Metering's public `self_information` function to measure those
outcomes.

Run the deterministic example with:

```bash
printf '%s\n' \
  '{"candidate":"mutation-17","target_probabilities":[0.5,0.25,1.0]}' \
  | uv run python apps/mutagenesis/mutagenesis.py
```

The adapter reports every target surprisal and their explicitly named
arithmetic mean. It does not contain observations, a neural architecture,
mutation logic, selection, a loop, memory, or a stopping rule. Those remain
agent responsibilities. Lower surprisal for caller-declared outcomes does not
establish general adaptation, correctness, meaning, understanding, or
intelligence.

## Definitions and edge cases

For logarithm base `b > 1`:

```text
self-information:      -log_b(p)
entropy:                -sum p_i log_b(p_i)
KL divergence:           sum p_i log_b(p_i / q_i)
mutual information:      sum p(x,y) log_b(p(x,y) / (p(x)p(y)))
```

- `0 log 0` contributes zero.
- Self-information at probability zero is positive infinity.
- KL divergence is positive infinity when `p_i > 0` and `q_i = 0`.
- Distributions must sum to one within an absolute tolerance of `1e-12`.
- Booleans, negative values, values above one, NaN, and infinity are rejected.
- Inputs are converted to double precision; conversion may not collapse a
  nonzero probability to zero or a value distinct from one to one.
- Joint distributions must be rectangular.
- If a joint's total mass is accepted within tolerance as `S`, its independent
  comparison uses `row * column / S`; the supplied cells are not rescaled.
- KL inputs must have equal lengths and matching positional meaning.

Metering does not renormalize accepted values. It uses double-precision
floating-point arithmetic; compare nontrivial results with an appropriate
numerical tolerance.

## What is deliberately absent from the package

There is no world, policy, controller, optimizer, benchmark, model adapter,
MCP server, HTTP service, general trace/report system, replay engine, overall
score, or information-gain guess. The fixed measurement ledger stores only the
accepted JSON pair, package version, and parent-bound identifiers.

The initial scope is finite discrete distributions. Continuous entropy and
estimators from samples need modeling decisions and are not silently bundled
into this package.

## Development

```bash
uv run --extra test pytest -q
uv build
```

## Compatibility

The current design is a deliberate breaking replacement of the earlier
hidden-fault harness. Old policies, commands, manifests, traces, reports, and
run directories require the historical checkout that produced them. The new
package does not carry a compatibility layer.
