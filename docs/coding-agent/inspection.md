# Inspect every candidate and evolution loop

Open `/history`, choose a task's run, and press **t** in the dashboard. The same
browser is available from `/progress`. This adds no slash commands and starts no
worker, model, evaluator, retry, or verification job.

## Candidate trees

The browser displays actual Population ancestry, not a chronological list drawn
with decorative branches:

```text
H0 [eliminated]
├─ H1 [eliminated] · parent H0 · capacity
│  └─ H3 [selected] · parent H1
└─ H2 [retained] · parent H0
```

This is an illustration, not a claim about a particular run. **H** labels harness
candidates and **S** labels solution candidates. Labels are assigned in immutable
Population registration order, starting at zero, and stay stable as a run grows.
They are local to that experiment, not global candidate identities. Long visual
indentation is abbreviated with `…` so deep branches cannot hide node IDs. Reports
always retain the full candidate ID, Git commit/tree, parent, and source run.

Trees page through every registered candidate, including seeds and children
that are no longer retained. Tree traversal follows parents; therefore H3 can
appear before H2. The parent label remains visible across page boundaries.
Select a node with arrows/Enter, or click it when using Pi's fullscreen mouse
support. Escape returns to the dashboard; it never stops the worker.

### Status means

- **retained**: a member of the latest recorded development archive;
- **eliminated**: listed in that archive's exclusions, with its recorded reason;
- **not-yet-archived**: registered, but no archive decision for it is recorded;
- **selected**: the candidate with recorded protected-final evaluation. This
  means chosen, **not necessarily passing**; inspect its final counts.

Current archive state is separate from the pairwise Selection Gate. A child can
lose its immediate comparison yet remain a useful resource/performance trade-off.
A previously retained node can later be excluded or re-enter the archive. The
report includes archive snapshots so these changes remain inspectable. Excluded
candidates and their evidence are not deleted.

## Reports for all children, not just the selected one

Every registered candidate can show:

- immutable candidate/Git/parent identities and entrypoint;
- current archive status and recorded exclusion reason;
- cumulative development case counts, replicate counts, safety failures, and
  separately named evaluation resources (not a new fitness score or total-search cost);
- its own recorded loops and loops in which it was a parent;
- parent allocation, proposal attempts/retries and reservations, child registration,
  independent evaluation, public per-case outcomes, pairwise decision/reason,
  archive membership, and next-parent allocation;
- the proposal's explanation when a matching Controller receipt exists, explicitly
  labelled **model-authored**, not evaluator authority or hidden reasoning;
- source record IDs and receipt references for inspection/offline verification;
- its historical parent-relative Git diff, not the latest child's diff; and
- protected-final counts **only if that candidate has a final-role run record**.

An unselected child normally says **not evaluated** for the protected final. The
viewer does not open protected test profiles, invent final results, or run more
checks to fill gaps. Missing Controller receipts are explicit unavailable-detail
entries; ledger evidence remains visible. Full offline replay remains separate.

Report keys: arrows/PageUp/PageDown scroll; **n/p** page loop steps; **]/[** page
the diff; **r** reloads the read-only report; Escape returns to the tree.
There are ten event entries per report page and forty diff display fragments per
diff page. Long source lines split into 200-character fragments rather than being
silently clipped. Binary changes use Git's binary diff representation. Git output
has a 32 MiB read bound and a timeout; excessive, unreadable, or non-UTF-8 output
is explicitly unavailable rather than silently presented as a complete diff.
The immutable Git objects remain the original bytes. No per-child patch is
written to the run or automatically applied.

## Failed and pending attempts

Choose **Show loops / attempts** to inspect every recorded round, including a
pending round without a registered child. HR1 is harness round 1; SR1 is solution
round 1. Selecting it shows the recorded steps and attempts independently of
whether it produced a successful candidate.

Attempt outcomes distinguish a recorded Controller receipt, a diagnostic-only
failure, an attempt superseded by an explicitly reserved retry, and a
pending/indeterminate attempt. Older runs without failure diagnostics cannot
recover an unrecorded cause. Diagnostic digests are checked and excerpts remain
sanitized/redacted. A failed proposal is an attempt, **not a fabricated H/S node**.
A stale pending intent already represented by a committed round is not duplicated.

## Reuse, storage, and limits

A detached workflow shows its bound harness and solution trees. A reused harness
is labelled **REUSED**, references its original run, and keeps its original H
labels and evidence; none of its generations are claimed as new task work. Legacy
standalone runs expose their own native experiment tree. Missing Population
ledgers produce an explicit warning, not reconstructed fictional candidates.

Views are derived on demand from bounded, canonical, hash-linked Population and
Driver records and Git objects (64 MiB per ledger, 2 MiB per auxiliary JSON
document, at most 4,096 diagnostic files). They do not depend on SQLite, write historical
run files, or require migration. Opening a report records a disposable inspection
entry in the Pi session, not in the experiment ledger. All views remain
**projection-only**, never selection, retry, or assay authority.

Read the same projections without Pi:

```bash
uv run python -m apps.coding_agent.operator_view tree RUNS RUN_NAME [OFFSET]
uv run python -m apps.coding_agent.operator_view candidate RUNS RUN_NAME H1 [EVENT_OFFSET] [DIFF_OFFSET]
uv run python -m apps.coding_agent.operator_view loops RUNS RUN_NAME [OFFSET]
uv run python -m apps.coding_agent.operator_view loop RUNS RUN_NAME HR1 [EVENT_OFFSET]
```

Use S1/SR1 for solutions. RPC clients select **Candidate trees / child reports**
from the progress dialog, then use the tree/report navigation dialogs. The
four-command `/goal`, `/limit`, `/history`, `/progress` interface is unchanged.
