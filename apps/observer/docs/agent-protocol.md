# External-agent JSONL protocol

This page specifies the fixture-session protocol. Observer's separate one-shot
`--evaluate` boundary for schema version 2 agent tasks is specified in the
[agent-artifact evolution protocol](../../../docs/agent-evolution.md).

## Status

Protocol version 1 is implemented by `apps/observer/observer.py --jsonl`.
The ordinary command without `--jsonl` remains the deterministic built-in
greedy maximum-predicted-result-entropy demonstration.

Start one session from the repository root:

```bash
uv run python apps/observer/observer.py --jsonl --active v3
```

`--active` is controller configuration used to materialize the private sandbox;
it is not sent in protocol responses. `--history PATH` may be combined with
`--jsonl` to record every Metering request made by successful `state` and
`observe` actions.

## Transport

The process is a sequential UTF-8 JSON Lines server over standard streams:

- standard input receives exactly one JSON object per line;
- standard output returns exactly one canonical JSON object per input line;
- each response is flushed before the next request is read;
- recoverable request errors are returned on standard output and leave the
  session alive;
- end-of-file closes the session with status 0, even if it was not finished; and
- startup or internal failures write one JSON error to standard error and exit
  with status 2.

Blank lines, malformed JSON, invalid UTF-8, duplicate keys, missing or extra
keys, unknown actions, out-of-catalogue probes, and out-of-order actions are
recoverable request errors. There is no concurrent request processing inside
one session; response order is request order.

Every action response contains `protocol_version`, `catalogue_id`, `ok`, and
`step`. `protocol_version` is `1`. `step` counts only successfully delivered
observations; `state`, rejected actions, and `finish` do not increment it.

The catalogue identifier is:

```text
SHA-256(canonical JSON of {"probes": [ordered probe documents]})
```

It identifies operation and path definitions, not fixture contents, session
state, or measurement history.

## `state`

`state` reports the current public belief and the entropy of each catalogue
probe without changing the belief or step:

```json
{"action":"state"}
```

Initial response shape:

```json
{
  "available_probes":[
    {
      "probe":{"operation":"list"},
      "result_entropy":{"base":2.0,"infinite":false,"measure":"entropy","value":0.0}
    },
    {
      "probe":{"operation":"read","path":"config/mode.txt"},
      "result_entropy":{"base":2.0,"infinite":false,"measure":"entropy","value":1.0}
    },
    {
      "probe":{"operation":"read","path":"service/port.txt"},
      "result_entropy":{"base":2.0,"infinite":false,"measure":"entropy","value":1.0}
    }
  ],
  "belief":{"v1":0.25,"v2":0.25,"v3":0.25,"v4":0.25},
  "catalogue_id":"HEX_SHA256",
  "ok":true,
  "protocol_version":1,
  "snapshots":[
    {"name":"v1","snapshot_id":"HEX_SHA256","tree_id":"HEX_SHA256"},
    {"name":"v2","snapshot_id":"HEX_SHA256","tree_id":"HEX_SHA256"},
    {"name":"v3","snapshot_id":"HEX_SHA256","tree_id":"HEX_SHA256"},
    {"name":"v4","snapshot_id":"HEX_SHA256","tree_id":"HEX_SHA256"}
  ],
  "step":0
}
```

The controller calculates each result distribution from its current uniform
candidate belief and asks Metering for Shannon entropy. `snapshots` publishes
all possible identities so an agent can map a final belief name to the
`snapshot_id` required by `finish`; listing every possibility does not reveal
which one is active. The response exposes probe identities and entropy, but not
the private mapping from every hypothetical result to fixture versions.

## `observe`

`observe` performs exactly one advertised probe and one deterministic belief
transition:

```json
{"action":"observe","probe":{"operation":"read","path":"config/mode.txt"}}
```

Successful response shape:

```json
{
  "belief":{"v1":0.0,"v2":0.0,"v3":0.5,"v4":0.5},
  "belief_entropy_after":{"base":2.0,"infinite":false,"measure":"entropy","value":1.0},
  "belief_entropy_before":{"base":2.0,"infinite":false,"measure":"entropy","value":2.0},
  "catalogue_id":"HEX_SHA256",
  "done":false,
  "observed_probability":0.5,
  "observed_result":{"kind":"text","text":"fast\n"},
  "observed_surprisal":{"base":2.0,"infinite":false,"measure":"self_information","value":1.0},
  "ok":true,
  "protocol_version":1,
  "step":1
}
```

Version 1 supports only the exact catalogue forms:

```jsonl
{"operation":"list"}
{"operation":"read","path":"RELATIVE_UTF8_PATH"}
```

A read path must exactly match an immutable advertised probe. Absolute paths,
`..`, symbolic-link traversal, unknown paths, and extra probe keys are rejected.
An uninformative probe is legal and still increments `step`; the external agent
owns action choice. Once `done` is true, another `observe` is rejected and the
agent must call `finish` or close the stream.

## `finish`

`finish` is accepted only when exactly one candidate remains:

```json
{"action":"finish","snapshot_id":"HEX_SHA256"}
```

Before responding, the controller verifies that the canonical sandbox
regular-file manifest matches the remaining candidate's `tree_id`. This
identity covers paths, byte lengths, and content hashes, not filesystem metadata
or empty directories. The response ends the session logically, although the
process continues reading so later lines can receive explicit errors:

```json
{
  "catalogue_id":"HEX_SHA256",
  "correct":true,
  "ok":true,
  "protocol_version":1,
  "snapshot":{"name":"v3","snapshot_id":"HEX_SHA256","tree_id":"HEX_SHA256"},
  "step":2
}
```

`snapshot_id` must be a lowercase 64-character SHA-256 identifier. A well-formed
but wrong identifier produces `"correct":false`; the response still reveals the
identified snapshot and finishes the session. Every later action is rejected.

## Recoverable errors

A malformed or out-of-order line returns:

```json
{
  "catalogue_id":"HEX_SHA256",
  "error":{"code":"invalid_request","message":"..."},
  "ok":false,
  "protocol_version":1,
  "step":0
}
```

The error is written to standard output to preserve one-response-per-line
alignment. The session state is unchanged. Message wording is diagnostic;
agents should branch on `ok` and `error.code`.

A startup or internal controller failure is not recoverable. It is written to
standard error as:

```json
{"error":{"code":"observer_error","message":"..."}}
```

## Deliberately absent

There is no action for changing the observation catalogue, editing fixtures,
altering Metering, installing tools, creating sub-agents, persisting a session,
or setting a nonuniform prior. The protocol exposes one finite deterministic
observation loop; it does not implement an agent or policy.
