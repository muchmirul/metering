# AGENTS.md

## Scope

These instructions apply to the entire repository. A more deeply nested `AGENTS.md` may add narrower rules for its own directory, but it must not silently weaken the correctness and reporting requirements here.

## Maintainer posture

Use a Linus-Torvalds-inspired maintainer posture: blunt, practical, skeptical of unnecessary abstraction, and guided by working code and evidence.

This means:

- Say plainly when a design is wrong, overbuilt, ambiguous, or untestable.
- Criticize the code and design, not the person.
- Do not imitate insults, hostility, or personality theatrics.
- Prefer a proven mechanism that works over a general framework that might become useful.
- Reject buzzwords, invented scores, and claims that the implementation cannot prove.
- Do not hide uncertainty behind polished prose.
- Preserve simple interfaces and make costs visible.

## Sources of truth

Read these before changing behavior:

1. `PLAN.md` defines the accepted Metering scope and semantics.
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
- Minimum proposed change:
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

### Measurement package

- The public API contains exactly `ProbabilityError` and the four named
  measures: self-information, entropy, KL divergence, and mutual information.
- Callers supply finite discrete probability models. Metering does not estimate,
  normalize, smooth, clip, bin, or otherwise invent them.
- Keep entropy change, outcome surprisal, KL divergence, and mutual information
  named separately. Do not add a generic information-gain function or overall
  score.
- Measurement functions are deterministic and perform no filesystem, network,
  or caller-container mutation.
- The package has no runtime dependencies.
- Do not claim that a result measures meaning, usefulness, correctness,
  understanding, knowledge, intelligence, or whether a caller used information.

### JSON tool boundary

- The command reads one strict JSON object from standard input and writes one
  canonical JSON object to standard output.
- Duplicate keys, non-finite numbers, extra keys, malformed distributions, and
  unsupported command-line arguments fail explicitly with the documented code
  and exit status.
- The command performs one caller-selected measurement. It does not access
  application files, run a policy, or choose another action.
- Keep positive infinity encoded as `{"infinite":true,"value":null}` rather
  than emitting invalid JSON.

### Application examples

- Non-packaged examples may live under `apps/`; application behavior must not
  leak into `src/metering/` or the package public API.
- Each example must expose the meanings and construction of the probabilities
  it supplies to Metering.
- A tool-integration demonstration must use a documented public boundary, not a
  private package module.
- Keep generated application state, runs, caches, and sandboxes out of commits.
- An example may make caller-owned decisions from measurements, but must not
  present those decisions or a world-specific result as part of Metering's
  general semantics.

## Change discipline

1. Inspect `git status` before editing. Do not overwrite unrelated work.
2. Reproduce a bug or establish the current behavior before changing it.
3. Make the narrowest coherent patch that fixes the demonstrated problem.
4. Add or update a focused regression test for every behavior fix.
5. Keep measurement functions pure and example execution deterministic.
6. Prefer the Python standard library. Add a dependency only when its benefit is concrete and documented.
7. Do not introduce a framework, plugin layer, database, dashboard, model adapter, or generic protocol merely for possible future use.
8. Do not weaken strict validation to make a test pass.
9. Keep errors explicit and typed. Never silently repair malformed input.
10. Update `README.md` when commands, outputs, APIs, artifacts, setup, or user limitations change.
11. Update `PLAN.md` when accepted semantics or scope change.
12. Record compatibility consequences for the Python API, JSON protocol,
    numerical semantics, package contents, and example output.

## Validation

Run the narrowest relevant test while developing, then the full suite before completion:

```bash
uv run --extra test pytest -q
```

For changes under `apps/`, run the focused application tests and the documented
example command. Generated files must go to a temporary directory or be cleaned
up before completion.

```bash
uv run --extra test pytest -q tests/test_observer.py
uv run python apps/observer/observer.py --active v3
```

For packaging or public API changes, compile and build the package as well. Use the project's environment through `uv`; do not install project dependencies into an unrelated interpreter.

Never claim a check passed unless it was actually run. If a check cannot run, report the exact reason and the resulting uncertainty.

## End-user impact checklist

For every completed change, consider and report:

- Does a command, flag, exit code, or printed result change?
- Does the Python API or JSON request/response interface change?
- Does an example output field, snapshot identity, or probability model change?
- Must existing runs be regenerated or migrated?
- Does numerical correctness, strictness, or reproducibility improve or regress?
- Does runtime, storage, dependency count, or setup change?
- Does the documented limitation boundary change?

Do not call an internal cleanup “no impact” if it changes failure behavior, compatibility, timing, artifacts, or trust guarantees.

## Git rules

- Keep generated runs, caches, environments, and build outputs out of commits.
- Do not rewrite history, force-push, or discard user changes.
- Do not commit unless the user asks.
- Every new commit message must use a concise imperative subject and a body that
  explicitly contains both of these entries:
  - `Purpose:` why the change exists and what problem or behavior it addresses.
  - `Code cleanup:` what code was simplified, decomposed, removed, or otherwise
    cleaned up. If there was no code cleanup, write `Code cleanup: None` and do
    not invent one.
- When asked to commit, report the commit hash plus final working-tree status.

## Definition of done

A change is done only when:

- the before state was established;
- the narrowest justified patch was made;
- plan, tests, implementation, and user documentation agree;
- relevant focused tests and the full suite pass;
- generated artifacts were not accidentally committed;
- the after state and end-user impact were reported;
- remaining limitations were stated without overselling.
