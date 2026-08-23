# Minimal agent protocol

## Status

This document specifies the intended agent-facing boundary. The current
`observer.py` still runs its own maximum-entropy demonstration to completion;
the request/response protocol below is **not implemented yet**.

## Transport

The target is one long-running process using JSON Lines:

- standard input receives exactly one JSON object per line;
- standard output returns exactly one canonical JSON object per request;
- requests are processed sequentially;
- recoverable request errors return a JSON error and leave the session alive;
- startup or internal failures write a JSON error to standard error and exit
  with status 2.

Every response contains `protocol_version`, `catalogue_id`, `ok`, and `step`.
Version 1 needs only three actions.

## `state`

`state` reads the current public state without changing it.

```json
{"action":"state"}
```

Successful response shape:

```json
{
  "available_probes":[
    {
      "probe":{"operation":"read","path":"config/mode.txt"},
      "result_entropy":{"base":2.0,"infinite":false,"measure":"entropy","value":1.0}
    }
  ],
  "belief":{"v1":0.25,"v2":0.25,"v3":0.25,"v4":0.25},
  "catalogue_id":"HEX_SHA256",
  "ok":true,
  "protocol_version":1,
  "step":0
}
```

The public probe catalogue exposes probe identities and their measured result
entropy. It does not expose the internal mapping from every hypothetical result
to the versions that would produce it.

## `observe`

`observe` performs exactly one allowed probe and one belief transition.

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

The application constructs the result probability, asks Metering to measure
it, observes the sandbox, and conditions the belief. The agent chooses the
probe; the application does not substitute a policy.

Version 1 supports only:

```json
{"operation":"list"}
{"operation":"read","path":"RELATIVE_UTF8_PATH"}
```

A read path must exactly match a path advertised by the current observation
catalogue. Absolute paths, `..`, symbolic-link traversal, and extra probe keys
are rejected.

## `finish`

`finish` submits one snapshot identity and ends the session.

```json
{"action":"finish","snapshot_id":"HEX_SHA256"}
```

Successful response shape:

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

The controller may require the belief to contain exactly one nonzero candidate
before accepting `finish`. This keeps completion separate from an observation.

## Errors

Malformed or out-of-order requests return:

```json
{
  "catalogue_id":"HEX_SHA256",
  "error":{"code":"invalid_request","message":"..."},
  "ok":false,
  "protocol_version":1,
  "step":0
}
```

Version 1 should reject invalid JSON, duplicate keys, unknown actions, missing
or extra keys, observations outside the catalogue, and actions after finish.
It must not silently repair a request.

## Deliberately absent

There is no action for changing the observation catalogue, editing fixtures,
altering Metering, installing tools, creating sub-agents, or persisting a
session. Those are separate future applications or controller responsibilities,
not part of the fundamental observation loop.
