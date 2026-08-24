# Measurement history

`metering-history` is the installed, opt-in filesystem boundary for retaining
accepted Metering request/response pairs. It wraps the public `metering` JSON
command; it does not add a measure, interpret a result, choose a request, or run
an application policy.

The ordinary Python measures and `metering` command never create history unless
a caller explicitly invokes this separate command.

## Commands and transport

The complete command surface is:

```text
metering-history record PATH
metering-history log PATH
metering-history verify PATH
```

`-h`/`--help` and `--version` are also supported. Command abbreviations are
disabled.

`record` reads exactly one Metering request from standard input. It first runs
that request through `python -m metering` with the same Python interpreter. A
rejected request preserves Metering's `invalid_request` or
`invalid_probability` error and does not create or advance the history.

Every successful command writes one canonical UTF-8 JSON object to standard
output and exits with status 0. Command-envelope failures use `invalid_request`;
storage or integrity failures use `invalid_history`. Errors are canonical JSON
on standard error, leave standard output empty, and exit with status 2:

```json
{"error":{"code":"invalid_history","message":"..."}}
```

## Record schema and identity

An accepted request is decoded to the numeric representation accepted by the
public command, so JSON integer and decimal numeric tokens are stored in the
record as double-precision numbers. The exact canonical Metering response is
stored beside that normalized request.

The pair identity is:

```text
pair_id = SHA-256(canonical JSON of {
    "request": normalized request,
    "response": exact Metering response
})
```

The stored schema version 1 object has exactly these fields:

```json
{
  "metering_version":"METERING_VERSION",
  "pair_id":"HEX_SHA256",
  "parent_record_id":null,
  "request":{"measure":"entropy","probabilities":[0.5,0.5]},
  "response":{"base":2.0,"infinite":false,"measure":"entropy","value":1.0},
  "schema_version":1
}
```

Its record identity is the SHA-256 digest of the canonical JSON for that entire
six-field stored object. `record_id` is not stored inside the object it hashes;
it is the object filename and is added to `record` and `log` responses.

`pair_id` identifies request/response content. Repeating the same accepted pair
therefore produces the same pair ID. `record_id` also binds the package version
and `parent_record_id`, so appending that pair at a different lineage position
produces a different record ID.

`record` validates the history path and `HEAD` representation and serializes the
write, but it does not perform a complete reachability or object audit before
appending. Run `verify` before a write when existing-history integrity matters,
and after a write when the resulting ledger is an artifact you intend to keep.

## Filesystem layout

After one successful record, the caller-owned history has this shape:

```text
PATH/
    HEAD
    objects/
        RECORD_ID.json
```

`HEAD` contains one lowercase record ID plus a newline. Each object is canonical
UTF-8 JSON plus a newline. A `LOCK` directory exists only while a writer holds
the history lock; object and `HEAD` replacement are atomic. A killed writer may
leave a stale `LOCK`. Inspect the history before removing it because the command
cannot decide whether another writer is active.

The history root, `objects`, `HEAD`, record objects, and object-directory
entries must have the expected real directory or file types. Symlinks at those
validated boundaries are rejected.

## Reading and verification

`log` follows `HEAD` through `parent_record_id` and returns reachable records
newest first:

```json
{
  "head":"HEX_SHA256",
  "records":[
    {
      "metering_version":"METERING_VERSION",
      "pair_id":"HEX_SHA256",
      "parent_record_id":null,
      "record_id":"HEX_SHA256",
      "request":{"measure":"entropy","probabilities":[0.5,0.5]},
      "response":{"base":2.0,"infinite":false,"measure":"entropy","value":1.0},
      "schema_version":1
    }
  ]
}
```

An existing empty history with an `objects` directory and no `HEAD` returns
`{"head":null,"records":[]}`.

`verify` checks the lock state, `HEAD`, canonical object encoding, exact record
and response keys, schema version, request/response measure agreement, pair and
record hashes, parent links, cycles, object filenames, unexpected
object-directory entries, and unreachable objects. Its success response is:

```json
{"head":"HEX_SHA256","records":1,"valid":true}
```

Verification does not replay measurements, compare them with the current
Metering version, authenticate an author, prove which executable created a
record, or sign the lineage. Hashes expose modification and broken structure;
they are content and lineage identifiers, not trust evidence.

## Deliberate limits

This is one local linear ledger. It has no branches, merges, remotes, tags,
checkout, wall-clock timestamps, signatures, automatic replay, candidate
lineage, application state, sandbox snapshots, or retention decisions. Folder
snapshot IDs and application candidate IDs have different schemas and meanings
from measurement pair and record IDs.
