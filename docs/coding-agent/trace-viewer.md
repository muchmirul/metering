# Trace Viewer

Trace Viewer is a local, read-only graphical interface for Agentvolve's existing
candidate commits and recorded evidence. It does not evolve candidates, execute
source, change an archive, retry work, or run verification/final checks.

## Setup and opening

From the source checkout, build the optional browser interface once:

```bash
npm ci --prefix apps/coding_agent/trace_ui
npm run build --prefix apps/coding_agent/trace_ui
```

Node/npm are build-time requirements. The interface uses pinned TypeScript,
esbuild, and Cytoscape.js; assets are served locally, never from a CDN. The
Python viewer uses the standard library and the existing Git executable. No
runtime dependency is added to the installed Metering package.

In Pi:

1. Run `/reload` after updating the extension.
2. Open `/history` and choose a run, or use `/progress` for the latest run.
3. Press **g** for Trace Viewer. Pi requests the default browser on Linux/macOS
   when its platform opener is available and always prints the local URL.
4. **t** still opens the terminal tree/report browser. Its **Open Trace Viewer**
   item launches the same graphical interface.
5. RPC clients choose **Open Trace Viewer** and receive the local URL without a
   browser process being opened on their behalf.

No fifth Agentvolve slash command is registered. Loading Pi, activation, status
polling, and model-facing tools never start this viewer.

Without Pi:

```bash
uv run python -m apps.coding_agent.trace_server launch RUNS RUN_NAME --open
# Or keep the viewer in the foreground; it prints a readiness JSON record:
uv run python -m apps.coding_agent.trace_server serve RUNS RUN_NAME
```

The URL is local to the Pi machine. Remote users need a same-port loopback tunnel,
not a public bind address or relaxed Origin checks.

The URL has a temporary bearer capability in its fragment. Treat it as private;
it is not a durable citation. The server binds only `127.0.0.1`, accepts one
selected run and its bound sources, and expires after **15 minutes without an
authenticated API request**, or **4 hours total**. Closing a tab or Pi does not
stop Agentvolve. An idle tab does not poll to keep the viewer alive. Open a new
viewer when a session expires. There is no permanent web service to install.

## Labels: depth is not round number

The graph uses stable branch labels:

```text
S0
├── S1a
│   ├── S2a ─── S3a
│   └── S2c
└── S1b ─── S2b
```

- **H** means harness; **S** means solution.
- The number is lineage depth: distance from the seed.
- The first child continues its parent's branch. Another child receives the
  next unused letter in immutable registration order: a..z, aa.. .
- Selection, elimination, layout, and later forks never rename existing nodes.
- Chronological creation rounds remain separate. Round 5 can create S2c from
  an older S1a.

These are display aliases, not new Git branches or renamed files. Existing
registration aliases (such as S3), full candidate IDs, commit/tree hashes, and
historical evidence are unchanged. Names are local to a source experiment.
Reused harnesses retain their original source and are clearly marked **REUSED**;
there is no invented genetic-parent edge from a harness to a solution.

## Trace a candidate and its files

1. Choose **Harness** or **Solution**.
2. Click a candidate circle or use the candidate selector. Search accepts a
   display label, registration alias, or full candidate identity.
3. Inspect parent, depth/branch, creation round, latest archive state, cumulative
   development counts, and that candidate's own recorded protected-final counts.
4. Browse its tracked files in the left-hand folder tree. Files page in groups
   of 100; **Graph file nodes** can show changed files or all files on that page.
5. Click a file row or a file rectangle. Inspect source, its mode/content hash,
   parent-relative diff, or exact bytes. Choose another candidate in **Compare
   with** for an exact-path comparison within that same source experiment.
6. Choose **Trace this file** to display the path's versions across the actual
   candidate ancestry. **Return to ancestry** restores the candidate graph.

Circles represent candidates; rectangles represent files. Solid arrows represent
ancestry; dashed arrows mean **contains**, not mutation. A white halo means
currently inspecting; a gold border means chosen for final evaluation, **not
necessarily passing**. Faded candidates remain inspectable after exclusion.

File identity includes the original source, candidate, commit, raw path identity,
Git blob, and file mode. Git remains the only file-version store; the viewer does
not create per-node folders or copy files into SQLite. Display paths are escaped
for readability; the URL-safe `path_id` preserves their original bytes and avoids
ambiguous path parsing. Empty files and absent files are different states.

Deleted entries belong to the comparison base, not the child. Opening one shows
that attribution explicitly. Symlink targets are inert text and are never
followed; submodule references are metadata only. Binary/non-UTF-8 files are not
pretended to be text. Raw downloads preserve CRLF, binary bytes, and the absence
of a final newline. Expand **File identity / byte metadata** for the full reference
and byte details without pushing the source offscreen. Source and diff pages are bounded display fragments; only the
raw-file download is advertised as byte-exact.

**Inspect inferred renames** runs bounded Git similarity detection separately.
It does not silently link renamed paths in file history. A detected rename is
an inference, not proof of author intent.

## Evidence and historical state

**Recorded steps / evidence** shows paged proposal/evaluation/selection/archive
steps and their record references. **Loops / attempts** includes failed and
pending proposals that never became registered candidates. Missing evidence is
explicit; no node, retry, failure cause, or protected-final result is invented.

The archive selector shows membership at an earlier recorded archive event and
hides candidates not registered at that point. The inspector continues to show
**latest recorded evaluation summaries**, explicitly labelled as such; changing
an archive filter does not claim to rewind evaluation history. Pairwise selection
and archive membership remain distinct.

Results describe whole candidate snapshots. A changed file followed by improved
results does not prove that file caused the improvement. Task/evaluator/runtime
identities and separately named resources remain available for interpreting
comparisons; there is no new fitness score or file-level attribution metric.
Protected test contents are never served. Unselected children do not inherit
another candidate's final results.

## Snapshots, links, and exports

Graph, reports, file history, and comparisons use a bounded in-memory snapshot
identified by its source Population/Driver heads, pending identities, captured
public loop details, and task/worker summaries. Public receipt availability is
frozen too: a later repair does not silently alter an older snapshot. Ordinary
page reload preserves the linked snapshot/candidate/path. **Refresh evidence** is
an explicit request for latest records. At most two snapshots are retained per
viewer; an expired snapshot fails explicitly rather than silently retargeting a
link. This is a captured projection, not an atomic filesystem transaction across
live sources. A refresh during a partially committed step can fail explicitly;
retry refresh rather than treating missing references as completed work. A failed
refresh leaves the previous view usable. Separate offline replay remains required.

- **Copy immutable reference:** source and candidate/file identities for tracing.
- **Snapshot JSON:** complete graph projection, provenance, archive records, and
  current view context/positions. It is not an export of every raw receipt/blob.
- **Candidate CSV:** all candidates' latest summary fields, with missing final
  results left empty. Text cells are spreadsheet-safe; JSON retains exact strings.
- **Visible graph PNG:** the current viewport, with the snapshot ID in its name.
- **Current file-history JSON:** exact-path history plus source provenance.

Exports are projections, not sealed assay evidence or portable replay bundles.
The viewer labels full offline verification as **not performed by the viewer**.
Git commit/tree/blob checks are not a substitute for complete experiment replay.
Keep the original runs and their immutable Git objects for reproducibility.

## Bounds and security

The service accepts only fixed assets and bounded read-only API queries. It has
strict Host/Origin checks, no CORS or cookies, no arbitrary-file endpoint, no
mutation API, no remote assets, and a restrictive content-security policy. Source
is inserted as text, never rendered as HTML or executed. Git reads ignore inherited
Git redirection/replacement settings, disable hooks/external diffs/textconv, and
have byte/time limits. Commit/tree bytes are hash-checked before file mapping;
downloaded blobs are checked against their Git object identities.

Current limits include 2,048 graph candidates; 2,000 files per snapshot; 4,096
Git tree objects per traversal level/cache bound; 64 directory levels; 4,096 bytes
per path; 8 MiB of verified tree bytes; 32 MiB of captured public loop details per
source; 1 MiB per raw-file read/download; 4 MiB per Git diff; 100 file
rows per page; and 16 MiB per HTTP response. Oversized or incomplete data produces
an explicit error/warning, not a falsely complete view. There is no cross-run
file-search database, import/call graph, automatic rename-following, or editable
workspace in this version.

The existing strictly verified Population SQLite schema is not modified. Viewer
inventory caches are disposable in-memory data, and browser build/test outputs
are ignored. Historical run files require no migration and are never rewritten.

## Validation

```bash
npm run format:check --prefix apps/coding_agent/trace_ui
npm run build --prefix apps/coding_agent/trace_ui
uv run --extra test pytest -q
cd apps/coding_agent/trace_ui
npx playwright install chromium --only-shell
npm test
```

With Pi and built assets installed, the Python suite also exercises explicit
Trace Viewer launch through deployed Pi RPC and checks that capability URLs are
not persisted in session entries. Browser tests launch the actual HTTP service
and Chromium against controlled
ledgers plus real Git objects. They cover pointer/file inspection, inert candidate
HTML, exact downloads, history/deletions, paging, pending attempts, exports,
capability rejection, deep links, and narrow-screen rendering. These fixtures
are **not live-model acceptance**. The separately gated local-Qwen multi-task
acceptance still requires approved profiles, a generation budget, the pinned
runtime, Docker, a verified harness, and offline verification of each real run.

The separately approved [one-task local check](pi-versions.md#recorded-one-task-local-check)
completed with Qwen: two solution generations, 3/3 protected final checks, and
successful offline verification. Updated Pi opened the viewer over those real
commits; Chromium checked source/exact bytes, file history, reused harness
attribution, and the preserved pre-inference failed attempt. This does not claim
that the three-task suite ran.
