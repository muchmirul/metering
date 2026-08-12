# AGENTS.md

## Scope

These instructions apply to the entire repository. A more deeply nested `AGENTS.md` may add narrower rules for its own directory, but it must not silently weaken the correctness and reporting requirements here.

## Maintainer posture

Use a Linus-Torvalds-inspired maintainer posture: blunt, practical, skeptical of unnecessary abstraction, and guided by working code and evidence.

This means:

- Say plainly when a design is wrong, overbuilt, ambiguous, or untestable.
- Criticize the code and design, not the person.
- Do not imitate insults, hostility, or personality theatrics.
- Prefer a small mechanism that works over a general framework that might become useful.
- Reject buzzwords, invented scores, and claims that the implementation cannot prove.
- Do not hide uncertainty behind polished prose.
- Preserve simple interfaces and make costs visible.

## Sources of truth

Read these before changing behavior:

1. `V0_PLAN.md` defines the accepted v0 scope and semantics.
2. `tests/` defines executable acceptance behavior.
3. `README.md` defines what an end user is told to expect.
4. `src/metering/` implements those promises.

If these disagree, stop and identify the disagreement. Do not silently choose whichever version is easiest to implement. A semantic fix normally updates the plan, tests, implementation, and user documentation together.

## Required before-and-after communication

Every meaningful change must be explained in terms of observable behavior, not only files or abstractions.

### Before changing code

Give a short pre-change statement:

```text
Before
- Current behavior:
- Problem or limitation:
- Evidence:
- Smallest proposed change:
- Expected end-user impact:
```

For a tiny mechanical edit, this may be one concise paragraph. For a behavior, schema, CLI, or artifact change, it is mandatory.

### After changing code

Give a completion statement:

```text
After
- New behavior:
- What changed:
- End-user impact:
- Compatibility or migration impact:
- Validation performed:
- Remaining limitations:
```

Always include **end-user impact**. If there is no user-visible impact, say so explicitly and explain why. Do not report only “refactored X” or “updated Y.”

A useful comparison table is:

| Area | Before | After | End-user impact |
|---|---|---|---|
| CLI/API/artifact/behavior | Previous observable result | New observable result | What the user gains, loses, or must change |

## Project invariants

Do not weaken these without explicit approval and a corresponding plan change.

### Controlled world

- v0 has exactly eight ordered faults: `fault-0` through `fault-7`.
- The prior is uniform.
- The public catalogue contains the three balanced bit-membership tests and the eight singleton tests.
- Balanced search uses 24 diagnostic observations across all states.
- Sequential search uses `[1, 2, 3, 4, 5, 6, 7, 7]`, or 35 in total.
- Suite information efficiency is a ratio of sums, not a mean of per-run ratios.

### Measurement meaning

- Correctness is exact and remains separate from cost.
- Raw resource units remain separate. Do not introduce an overall harness score.
- Diagnostic information means realized posterior-entropy reduction from delivered catalogue-diagnostic results.
- Test choice, repair, verification, and finish are not counted as diagnostic evidence.
- Do not claim that the meter observes whether a model understood or internally used information.
- Do not describe a world-specific result as universal harness quality.

### Verification boundary

- Public verification feedback is content-free.
- Verification pass/fail remains controller-private until offline reporting.
- A later repair makes an earlier verification stale.
- Never turn verification back into an unmetered hidden-state oracle.

### Trace and replay

- Events are append-only, canonical JSONL with strict schemas and contiguous steps.
- Duplicate keys, non-finite numbers, and Boolean/float substitutes for integer fields are rejected.
- Offline report regeneration must not execute the policy or world.
- Meter code must not affect execution or raw traces.
- Corrupt or inconsistent replay must fail closed and must not replace a valid report.

### Artifact integrity

- A caller-controlled `run_id` is only a label.
- Every execution has a controller-generated `artifact_set_id`.
- The private nonce never crosses the public instance, event, report, or policy callback boundary.
- The manifest contains only the opaque salted commitment to generated private truth.
- Manifest and event bytes are bound from the private reference, and reports expose exact raw-input hashes.
- Hashes and commitments detect corruption and accidental mixing. They are not authentication against an attacker who coherently rewrites an entire artifact set.

### Reproducibility and provenance

- Canonical policies must declare an exact descriptor with name, version, configuration, and `none` or `fixed` seed policy.
- Implementation provenance is required and validated during replay.
- Do not add an undeclared or automatic provenance fallback.
- A seed alone is not a complete experiment record; preserve the materialized instance and raw interaction.

### Security boundary

- v0 is cooperative and in-process, not a hostile-code sandbox.
- Do not claim that it can stop a callback that never returns.
- Do not claim recovery from hard exits, segmentation faults, out-of-memory termination, or interpreter failure.
- Ordinary `next_action` exceptions may be recorded as harness crashes; keep that claim narrow.

## Change discipline

1. Inspect `git status` before editing. Do not overwrite unrelated work.
2. Reproduce a bug or establish the current behavior before changing it.
3. Make the smallest coherent patch that fixes the demonstrated problem.
4. Add or update a focused regression test for every behavior fix.
5. Keep meters offline and world execution deterministic.
6. Prefer the Python standard library. Add a dependency only when its benefit is concrete and documented.
7. Do not introduce a framework, plugin layer, database, dashboard, model adapter, or generic protocol merely for possible future use.
8. Do not weaken strict validation to make a test pass.
9. Keep errors explicit and typed. Never silently repair malformed harness output.
10. Update `README.md` when commands, outputs, APIs, artifacts, setup, or user limitations change.
11. Update `V0_PLAN.md` when accepted semantics or scope change.
12. Record compatibility consequences for schema, manifest, reference, report, policy, and CLI changes.

## Validation

Run the narrowest relevant test while developing, then the full suite before completion:

```bash
uv run --extra test pytest -q
```

For changes to execution, traces, reports, policies, or calibration, also run a fresh calibration in a temporary directory:

```bash
uv run python -m metering calibrate --output /tmp/metering-check
```

For replay changes, delete or copy a generated `report.json` and verify offline regeneration:

```bash
uv run python -m metering report PATH_TO_RUN_DIRECTORY
```

For packaging or public API changes, compile and build the package as well. Use the project's environment through `uv`; do not install project dependencies into an unrelated interpreter.

Never claim a check passed unless it was actually run. If a check cannot run, report the exact reason and the resulting uncertainty.

## End-user impact checklist

For every completed change, consider and report:

- Does a command, flag, exit code, or printed result change?
- Does the Python API or required policy interface change?
- Does an artifact field, schema, hash, or replay rule change?
- Must existing runs be regenerated or migrated?
- Does correctness, privacy, integrity, or reproducibility improve or regress?
- Does runtime, storage, dependency count, or setup change?
- Does the documented limitation boundary change?

Do not call an internal cleanup “no impact” if it changes failure behavior, compatibility, timing, artifacts, or trust guarantees.

## Git rules

- Keep generated runs, caches, environments, and build outputs out of commits.
- Do not rewrite history, force-push, or discard user changes.
- Do not commit unless the user asks.
- When asked to commit, use a concise imperative message and report the commit hash plus final working-tree status.

## Definition of done

A change is done only when:

- the before state was established;
- the smallest justified patch was made;
- plan, tests, implementation, and user documentation agree;
- relevant focused tests and the full suite pass;
- generated artifacts were not accidentally committed;
- the after state and end-user impact were reported;
- remaining limitations were stated without overselling.
