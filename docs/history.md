# Measurement history

This document specifies the history mechanism. Its relation to the repository's
information, identity, biology-analogy, and hypothesis boundaries is summarized
in the [system foundations](foundations.md).

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

Equivalently, for canonical JSON serialization `C`, record `R_t`, and digest
function `d(m) = SHA-256(UTF-8(C(m)))`:

```text
R_t.parent_record_id = null            when t = 0
R_t.parent_record_id = d(R_(t-1))      when t > 0
record_id_t           = d(R_t)
```

Changing a stored ancestor changes its digest under the collision-resistance
assumption of SHA-256. The next unchanged descendant still names the old digest,
so the reachable chain no longer verifies.

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

## Why this design is narrow

- **Separate command:** recording is a visible filesystem mutation and never
  changes the purity of the four Python functions or ordinary `metering` CLI.
- **Pair ID versus record ID:** content identity remains stable when the same
  request/response pair is repeated, while the record ID binds one occurrence
  to its lineage position.
- **Canonical objects:** one accepted logical record has one serialized byte
  form, so identity and verification do not depend on key order or whitespace.
- **Linear parent link:** one `HEAD` is enough for the actual append-only use
  case; branches, merges, remotes, and checkout would add unrelated version-
  control semantics.
- **Validate before append:** rejected measurements never become history.
- **Explicit verification:** append latency stays small, while callers decide
  when a complete reachability audit is worth its cost.

## Falsifiable integrity hypothesis

> Altering a canonical stored record without finding a SHA-256 collision or
> consistently rebuilding its descendants causes `metering-history verify` to
> reject the old lineage.

A modified object accepted under its old filename, a broken parent link, cycle,
unreachable object, noncanonical record, or invalid `HEAD` accepted by `verify`
falsifies this implementation claim.

The hypothesis deliberately excludes authentication and rollback detection. A
party that can rewrite all objects and `HEAD` can build another internally
consistent lineage, and a party can restore an older valid directory without an
external checkpoint being present. There are no signatures, trusted
timestamps, or remote witnesses.

## Primary sources

- NIST, *Secure Hash Standard (SHS), FIPS 180-4*, specifies SHA-256 and the
  message-digest integrity property used here:
  [FIPS 180-4](https://csrc.nist.gov/pubs/fips/180-4/upd1/final).
- S. Haber and W. S. Stornetta, “How to Time-Stamp a Digital Document,” 1991,
  is historical primary work on hash-linked records. `metering-history` does
  not implement its signatures or timestamping system:
  [DOI](https://doi.org/10.1007/BF00196791).
