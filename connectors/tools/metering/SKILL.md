---
name: metering
description: Measure caller-supplied finite probability models, record named results in Git, and invoke evidence-gated Metering application workflows. Use when uncertainty, forecast surprisal, candidate comparison, or metered evolution must be explicit and reproducible.
compatibility: Requires Python 3.11+ and a Metering source checkout or installed metering command. Git is required only for measurement history.
---

# Metering tool

Use Metering as a strict tool. Do not estimate, normalize, smooth, or invent a
probability model. Never describe entropy, surprisal, KL divergence, or mutual
information as meaning, correctness, usefulness, intelligence, or a universal
candidate score.

## One measurement

From this skill directory, send exactly one JSON object to `invoke.py`:

```bash
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | python3 invoke.py
```

The supported measures are `self_information`, `entropy`, `kl_divergence`, and
`mutual_information`. Preserve successful JSON exactly when another process will
verify it. An error exits with status 2 and writes one JSON error to standard
error.

From Prime Agent, call the same command through `subprocess` in IPython. From Pi,
call it through the shell tool. Resolve `invoke.py` relative to this `SKILL.md`;
do not assume the current working directory is the skill directory.

## Git measurement history

When the caller explicitly requests persistence, use the installed
`metering-history` command with a dedicated absent or empty directory:

```bash
history="$(mktemp -d)"
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | metering-history record "$history"
metering-history verify "$history"
```

The repository commits only canonical configuration, named result, and
provenance files. `record_id` is a Git commit and `pair_id` is the Git tree for
the configuration/result pair. Verification checks Git integrity, rejects dirty
state, and replays every result. Git identity is not authorship, model validity,
or evidence that a result should control selection. Do not put evaluator secrets
in this repository.

Legacy schema-version-1 `objects/` histories are not migrated automatically.
Read `docs/history.md` before modifying or publishing a history.

## Candidate evolution

For one evidence-gated parent/challenger comparison, first read the checkout's
`docs/capabilities.md`, `PLAN.md`, and `docs/agent-evolution.md`, then call the
documented source applications. The external agent proposes or executes
candidates. Metering only validates artifacts, measures declared forecasts,
applies the explicit task and safety gate, and records selected identity. A
selected candidate remains run-local until a separate caller-approved
installation or deployment.

The generation path compares one parent and one child, and the bounded driver
follows one selected head. The separate source-only `apps/population` command can
record multiple externally evaluated candidates, retain a development-only
Pareto archive, and return one exact uniform parent allocation. It does not run
that parent, expose final evidence to selection, learn allocation policy,
co-evolve evaluators, or deploy automatically. Read
`apps/population/README.md` before using that optional boundary.

Use only a reviewed fixed connector under `connectors/fixed/`. Keep candidate
processes away from protected evaluator data and the frozen Metering control
plane. Forecast calibration is not a substitute for task and safety evidence.
