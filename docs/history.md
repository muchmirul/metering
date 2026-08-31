# Git-backed measurement history

This document specifies the installed, opt-in `metering-history` boundary. Its
relation to Metering's information and identity boundaries is summarized in the
[system foundations](foundations.md).

`metering-history` stores accepted Metering configurations and exact named
results as commits in a dedicated Git repository. It wraps the public
`metering` JSON command; it does not add a measure, interpret a result, choose a
configuration, or run application policy. The four Python measures and ordinary
`metering` command remain filesystem-pure.

## Commands

```text
metering-history record PATH
metering-history log PATH
metering-history verify PATH
```

`-h`/`--help` and `--version` are also supported. Command abbreviations are
disabled.

`record` reads exactly one Metering request from standard input and first runs it
through `python -m metering` with the same interpreter. A rejected request
preserves Metering's `invalid_request` or `invalid_probability` error and does
not create `PATH`.

Every successful command writes one canonical UTF-8 JSON object to standard
output. Command-envelope failures use `invalid_request`; Git, storage, replay,
or integrity failures use `invalid_history`. Errors are canonical JSON on
standard error and exit with status 2.

## Repository layout

On the first accepted measurement, `record` requires `PATH` to be absent or an
empty real directory. It initializes a dedicated Git repository whose current
branch is `metering-history`. The committed worktree is exactly:

```text
PATH/
    .git/
    measurement/
        pair/
            configuration.json
            result.json
        provenance.json
```

- `configuration.json` is the normalized request accepted by Metering.
- `result.json` is the exact canonical named Metering response.
- `provenance.json` records schema version, Metering package version, Python
  version, an implementation-file SHA-256, an optional source commit, and a
  source-dirty flag.

No Metering source code, candidate code, evaluator secret, or environment state
is copied into the history.

All three files are canonical JSON with one trailing newline and regular Git
mode `100644`. Extra tracked paths, symlinks, executable modes, malformed JSON,
duplicate keys, unsupported schemas, and mismatched request/result measure names
are rejected.

## Git identity

Schema version 2 uses Git objects directly:

```text
pair_id          = Git tree ID of measurement/pair
record_id        = Git commit ID
parent_record_id = first parent commit ID, or null for the root
tree_id          = complete commit tree ID
```

The same normalized configuration and exact result have the same `pair_id` even
when recorded again. Each `record` invocation creates a new commit with the
previous commit as its only parent. `--allow-empty` is deliberate: repeated
pairs remain distinct occurrences while sharing pair and complete tree IDs when
provenance is unchanged.

Git object IDs use the repository's object format. Current default repositories
normally use 40-character SHA-1 IDs; repositories using Git's SHA-256 object
format use 64-character IDs. Callers must treat IDs as opaque lowercase Git
identifiers rather than assuming one hash length.

A successful `record` response contains:

```json
{
  "implementation_sha256":"LOWERCASE_SHA256",
  "metering_version":"METERING_VERSION",
  "pair_id":"GIT_TREE_ID",
  "parent_record_id":null,
  "python_version":"PYTHON_VERSION",
  "record_id":"GIT_COMMIT_ID",
  "request":{"measure":"entropy","probabilities":[0.5,0.5]},
  "response":{"base":2.0,"infinite":false,"measure":"entropy","value":1.0},
  "schema_version":2,
  "source_commit":"GIT_COMMIT_ID_OR_NULL",
  "source_dirty":false,
  "tree_id":"GIT_TREE_ID"
}
```

The source commit is advisory provenance. The implementation SHA-256 binds the
actual installed `metering` Python files used by the recorder, including an
editable checkout whose package metadata may not have refreshed. Neither value
copies or authenticates the implementation.

## Recording

`record` performs these steps:

1. ask the ordinary Metering command to validate and measure the request;
2. initialize or validate the dedicated Git repository;
3. reject a stale writer lock or dirty worktree;
4. validate the current linear commit history structurally;
5. write canonical configuration, result, and provenance files;
6. stage exactly those files with hooks and signing disabled;
7. create one commit authored as the Metering recorder; and
8. return the resulting Git identities and stored documents.

Git controls object writes and reference updates. A private
`.git/metering-history.lock` prevents two recorder processes from editing the
same worktree concurrently. Git's own index and reference locks still apply. An
interrupted process may leave the private lock or a dirty worktree; inspect the
repository before removing the lock or resetting files.

The command deliberately uses a fixed local author because commit authorship is
not evidence of who requested or approved a measurement. If authenticated
history is required, the caller must push to a protected remote or apply a
separate reviewed signing policy.

## Log and verification

`log` follows the current branch's first-parent history and returns records
newest first. It reads the committed blobs directly with Git rather than trusting
worktree files.

`verify` performs stronger checks:

1. reject a recorder lock or dirty worktree;
2. run `git fsck --full`;
3. require branch `metering-history` and a linear, merge-free first-parent chain;
4. require exactly the three documented regular files in every commit;
5. validate canonical JSON and schema/provenance fields;
6. derive pair, tree, commit, and parent IDs from Git; and
7. rerun every configuration through the current Metering executable and require
   the exact stored result.

Success is:

```json
{"head":"GIT_COMMIT_ID","records":1,"valid":true}
```

Git detects changed committed objects and working-tree drift. Replay catches a
wrong result that someone committed consistently as a new valid Git object.
Replaying with a later Metering build may expose a numerical or behavioral
change; use the recorded version, implementation digest, and source commit to
locate the historical implementation when investigating that mismatch.

## Trust and lifecycle limits

Git replaces the former custom `objects/`, `HEAD`, and parent-hash store. It also
provides standard remotes, branches, tags, checkout, and inspection without
Metering reimplementing them. The history command itself keeps one linear current
branch and does not create merges, tags, remotes, signatures, or deployment
actions.

Git and replay do not prove who produced a commit, protect against an authorized
force-push, preserve evaluator secrecy, or establish that a caller's probability
model is appropriate. Protected remotes and signatures can strengthen provenance
but remain caller-owned policy.

A measurement history is not a candidate identity. For evolutionary use, keep
candidate configuration identity separate from evaluation evidence: a candidate
Git tree should bind configuration only, while a run/evidence commit references
that candidate and records measurements. Otherwise changing only a result would
incorrectly create a new candidate identity.

Schema-version-1 histories using `PATH/HEAD` and `PATH/objects/*.json` are not
automatically migrated. Use the historical implementation to inspect them and
create a new Git history explicitly if needed.

## Falsifiable integrity hypothesis

> Modifying a tracked configuration or result makes the worktree dirty, changing
> a committed Git object breaks its object identity, and committing a false
> result causes `metering-history verify` replay to reject the history.

A dirty or malformed repository accepted as valid, a broken Git object accepted
by `git fsck`, a merge accepted in the linear history, or a false stored result
accepted by replay falsifies the implementation claim. Authentication and
rollback detection against an external checkpoint remain outside the claim.

## Primary source

- Scott Chacon and Ben Straub, *Pro Git*, second edition, documents Git objects,
  trees, commits, references, integrity, and distributed workflows:
  https://git-scm.com/book/en/v2/Git-Internals-Git-Objects
