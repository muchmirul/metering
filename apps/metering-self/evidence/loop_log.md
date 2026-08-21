# qwen-evolve self-refinement loop — measurement log

Repo: /mnt/Tforce/dev/metering (untouched — all artifacts live here, in metering-self/)
Driver: examples/run_suite.py, repo .venv, PYTHONDONTWRITEBYTECODE=1
Generator: generate_adapter.py v1 (fail-closed: unmapped harness entries refuse generation)

## iter 0 — baseline (default/empty harness state)
- tag: baseline-default
- harness_state_digest: 839ff99478d02a68b5eb19023858f110503ff3498a2b35c2739f824c7604f8a9
- entries: local=0 global=0
- policy: self-evolve-generated v1 (balanced, tie_break=public_catalogue_order, seed=none)
- run parent: runs/baseline-default/ (8 run dirs, replayable via `python -m metering report <dir>`)
- RESULT: 8/8 success | diagnostic_observations=24 | bits_removed=24.0 |
  bits_per_observation=1.0000 | excess_observations=0
- NOTE: baseline is already the known optimum for this 8-fault/3-bit world
  (excess 0). The loop can therefore only show *degradation* and *recovery*
  until the mapping is extended or a larger world exists.

## iter 1 — memory4 (4 memories, 1 refinement record in local store)
- tag: iter1-memory4
- generator: v2 (parses schema-1 store layout; memory entries mapped context-only;
  still fail-closed on skill/subagent/prompt/unknown)
- harness_state_digest: 9b99989deca6125daedbed62bb3df438da4bda9670caa577af249c92774fd6af
  (was 839ff9… at iter 0 — state change proven, not asserted)
- entries: local=4 global=0
  memory_ids: ipython-nested-quote-workaround, qwen-evolve-artifact-location,
  qwen-evolve-failclosed-design, qwen-evolve-self-refine-state
- policy: self-evolve-generated v2 (balanced, tie_break=public_catalogue_order, seed=none)
- run parent: runs/iter1-memory4/ (8 run dirs, all replay-verified via `python -m metering report`)
- RESULT: 8/8 success | diagnostic_observations=24 | bits_removed=24.0 |
  bits_per_observation=1.0000 | excess_observations=0
- DIFF vs iter 0: NONE. The memories are loop-process notes (paths, design
  constraints, tooling workarounds), not diagnostic strategy — and the v2
  mapping honestly treats them as provenance-only. Outcome: KEEP the entries
  (no behavioral cost measured), with digest-level evidence that the
  instrument detected the state change while the readings stayed optimal.
- NOTE: the loop's detection chain works end to end — v1 correctly refused
  the unrecognized state; v2 mapped it; digest changed; readings identical.
