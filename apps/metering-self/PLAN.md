# metering-self — PLAN

Normative source for scope, definitions, and acceptance criteria of the
self-refinement measurement loop. The lab notebook (what happened, iteration
by iteration) lives in `evidence/loop_log.md`; this file is what we *intend*.
The loop architecture is diagrammed in [`loop-flow.mmd`](loop-flow.mmd).

## Goal

Build a **reasoning harness**: an agent harness whose stored knowledge
(memories, skills, subagent configs, prompt notes) measurably improves the
agent's reasoning — where "improves" is defined by instrumented readings on
a known-answer world, not by plausible-sounding self-report.

`metering-self` is the experiment workspace for getting there. It uses the
[metering](https://github.com/muchmirul/metering) repo
(`/mnt/Tforce/dev/metering`) as a **read-only measurement instrument** and
evolves the agent's harness state as the experimental variable.

## Why a reasoning harness needs this loop first

A harness that writes things into itself (memories, skills) is easy to build
and hard to trust: every self-modification *sounds* like an improvement.
Before a reasoning harness can be allowed to rewrite its own reasoning
aids, there must be a gate that answers, with replayable numbers:

> Did this self-modification make diagnosis/reasoning better, worse, or
> nothing — in bits of uncertainty removed per observation?

That gate is the loop implemented here. The reasoning harness is the
destination; the fail-closed measurement loop is the admission control.

## The loop (5 steps)

1. **Generate** — `generate_adapter.py` mechanically translates harness
   state (local + global stores under `~/.prime/agent/`) into a Metering
   policy module. The generator is fixed code; the state is the only input.
   Every generated policy records the sha256 state digest in its descriptor.
2. **Measure** — run the committed suite driver from the repo root:
   `PYTHONPATH=/home/dev/metering-self uv run python examples/run_suite.py
   <module>:GeneratedPolicy --json --run-parent <dir>`
3. **Record** — per-run artifacts in `runs/<tag>/`, suite aggregates in
   `evidence/<tag>.json`, state snapshot in `evidence/<tag>_state.json`.
4. **Verify** — every run must replay via `python -m metering report <dir>`.
5. **Decide** — diff readings against the baseline; KEEP or ROLLBACK the
   harness refinement, with the evidence written to `evidence/loop_log.md`.

## Invariants (do not break)

- **Repo untouched.** The metering repo is the ruler. Only `uv run` of the
  committed driver; no writes, no commits of adapter files into the repo.
- **Fail closed.** If the harness state contains anything the generator's
  mapping does not cover, the generator MUST refuse (exit non-zero) rather
  than silently measure an uninterpreted state. Bump `GENERATOR_VERSION`
  when extending the mapping.
- **Provenance.** Every measurement is traceable: policy descriptor →
  state digest → state snapshot → harness entries. No digest, no result.
- **Durability.** Artifacts live here, never in `/tmp`. Before/after
  evidence must survive session ends and reboots.
- **Honesty of mapping.** A mapping may only change the decision rule when
  the harness entry actually encodes strategy. Context-only entries
  (process notes, paths) map to provenance, never to behavior.

## Definitions

- **Harness state** — the Prime Agent stores: session-local
  `~/.prime/agent/session-artifacts/<session>/harness/harness_state.json`
  and global `~/.prime/agent/harness/harness_state.json` (schema 1:
  `schema` / `entries` / `refinements`).
- **Iteration** — one full pass of the 5-step loop, identified by a tag
  (e.g. `baseline-default`, `iter1-memory4`).
- **Reading** — the suite aggregates: success count, diagnostic
  observations, uncertainty removed (bits), bits per observation
  (ratio of sums), excess observations (zero = 24 for the canonical
  8-fault world).

## Current state

- iter 0 `baseline-default`: empty state, digest `839ff9…`, 8/8, 24 obs,
  24.0 bits, 1.0 bit/obs, 0 excess. **Optimal baseline.**
- iter 1 `iter1-memory4`: 4 context memories + 1 refinement record,
  digest `9b9998…`, generator v2 (schema-1 parsing, memory = context-only).
  Readings identical to baseline. **KEEP** — state change detected,
  no behavioral cost.

## Roadmap toward the reasoning harness

1. ✅ Instrument gate: fail-closed generator + replayable evidence (done).
2. ⬜ **Strategy-bearing entries.** Extend the mapping so a memory/skill
   that encodes diagnostic strategy changes the generated decision rule —
   the first iteration that can produce a non-zero diff.
3. ⬜ **Degradation & recovery demonstration.** Deliberately write a
   harmful strategy entry, watch excess observations rise, roll back with
   evidence. Proves the gate catches real harm, not just no-ops.
4. ⬜ **Skill/subagent mappings.** Extend `MAPPED_KINDS` beyond `memory`
   (generator v3+), keeping fail-closed semantics.
5. ⬜ **Larger worlds.** The 8-fault/3-bit world is saturated by balanced
   search (excess 0 at baseline). Reasoning improvements need headroom:
   a bigger instance or a world without a trivial optimal strategy.
6. ⬜ **Reasoning harness v0.** An agent loop that proposes harness
   refinements, gated by this measurement loop: propose → measure →
   keep/rollback automatically, with `loop_log.md` as the audit trail.

## Acceptance criteria for "reasoning harness v0"

- At least one harness refinement is **kept** because readings improved
  (not because it sounded good), on a world with headroom.
- At least one refinement is **rolled back** on measured degradation.
- Every decision in the log is reproducible: same state digest in, same
  generated policy, same suite readings, replay-verified runs.
