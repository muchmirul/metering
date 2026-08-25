---
name: metered-self-evolve
description: Runs one evidence-gated comparison between a default agent or existing Agent Skills directory and one staged challenger on explicit matched tasks. Use only when the user asks to improve a Pi or Prime Agent skill and provides or approves a trusted evaluator.
compatibility: Requires Python 3.11+, uv, and a checkout of the Metering repository containing application schema version 2.
disable-model-invocation: true
---

# Metered Self-Evolve

Run exactly one bounded candidate generation. Never silently modify the loaded
skill, install a challenger, repeat generations, or claim broad improvement.

## Required inputs

Establish all of these before proposing:

1. Metering repository root and clean-status context.
2. Parent: either the default agent or an existing skill directory.
3. One specific task and immutable evaluation ID.
4. Finite public case documents.
5. Reviewed agent-runner command.
6. Separate trusted evaluator command with hidden checks.
7. Explicit `task-pass-count-v1` safety and pass-improvement policy.

Stop if there is no external evaluator or if the proposer can read its hidden
checks. Self-judgment is not evidence.

## One-generation workflow

1. Read the repository `PLAN.md` and `docs/agent-evolution.md` completely.
2. Inspect unrelated working-tree changes and preserve them.
3. Copy the parent skill to a temporary staging directory. For the default
   agent, use `{"artifact_schema":"agent-default-v1"}`.
4. Make one coherent challenger edit only in staging. Record a concrete reason.
5. Encode a skill directory:

   ```bash
   uv run python apps/mutator/skill_artifact.py STAGED_SKILL > /tmp/skill-artifact.json
   ```

6. Build a schema version 2 request from
   `apps/controller/agent-skill-example-request.json`. Do not put evaluator
   secrets in task inputs or the runner command.
7. Ensure parent and challenger use identical tasks, runner command, timeout,
   model, tools, and external budgets. Use separate isolated workspaces when
   tools are enabled.
8. Execute one generation:

   ```bash
   uv run python apps/controller/controller.py < REQUEST.json > REPORT.json
   ```

9. Verify the report binds two different candidate IDs, includes every case,
   contains trusted evaluator evidence, and selects only parent or challenger.
10. Report task pass counts, safety failures, forecast surprisal separately, and
    all limitations. Lower surprisal is calibration evidence, not task quality.
11. Show the candidate diff and ask for explicit approval before copying the
    selected artifact into any Pi or Prime Agent skill location.

## Pi text-only runner

For tasks requiring no tools or mutable workspace, the runner command may be:

```json
{
  "command":[
    "uv","run","python",
    "apps/candidate_runner/pi_text_adapter.py"
  ],
  "timeout_seconds":300
}
```

Each task input must then contain exactly `prompt` and the complete evaluator
`outcomes`. This adapter disables tools, context files, discovered skills,
extensions, prompt templates, themes, and session persistence. Because Pi's
normal progressive skill disclosure requires `read`, the tool-free adapter
registers the candidate skill and injects the complete verified `SKILL.md` into
Pi's system prompt. Referenced scripts and assets remain unavailable. Pin the
model and provider in the runner environment or a reviewed wrapper command. Do
not use this adapter for coding tasks that require filesystem tools.

## Safety boundary

Adapter commands run with the current user's permissions; Metering is not a
sandbox. For tool-enabled agents use a container, VM, or equivalent isolation,
with hidden tests and credentials outside candidate access. Never allow a
candidate to alter its evaluator, parent artifact, generation report, installed
skill, or selection policy.
