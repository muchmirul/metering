---
name: metering
description: Measure caller-supplied finite probability models and invoke evidence-gated Metering application workflows. Use when uncertainty, forecast surprisal, candidate comparison, or metered evolution must be explicit and reproducible.
compatibility: Requires Python 3.11+ and a Metering source checkout or installed metering command.
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

## Candidate evolution

For one evidence-gated parent/challenger comparison, read the checkout's
`PLAN.md` and `docs/agent-evolution.md`, then call the documented source
applications. The external agent proposes or executes candidates. Metering only
validates artifacts, measures declared forecasts, applies the explicit task and
safety gate, and records selected identity. A selected candidate remains
run-local until a separate caller-approved installation or deployment.

Use only a reviewed fixed connector under `connectors/fixed/`. Keep candidate
processes away from protected evaluator data and the frozen Metering control
plane. Forecast calibration is not a substitute for task and safety evidence.
