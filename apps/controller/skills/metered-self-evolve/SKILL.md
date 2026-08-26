---
name: metered-self-evolve
description: Runs one or a caller-bounded sequence of evidence-gated comparisons between default, SKILL.md, or immutable Git-backed candidates. Use only when the user approves a trusted evaluator, explicit limits, and any required builder or executor sandbox.
compatibility: Requires Python 3.11+, uv, and a checkout of the Metering repository containing application schema version 2.
disable-model-invocation: true
---

# Metered Self-Evolve

Run exactly one candidate generation unless the user explicitly requests the
bounded Evolution Driver and approves its limits. Never silently modify the
loaded skill, install a challenger, exceed those limits, or claim broad
improvement.

## Required inputs

Establish all of these before proposing:

1. Metering repository root and clean-status context.
2. Parent: the default agent, an existing skill directory, or one verified
   `git-candidate-v1` descriptor.
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
    selected artifact into any Pi skill location.

## Bounded recurrence

When the user explicitly requests multiple generations, use
`apps/evolution_driver/example-request.json` as the request shape and put the
state outside the repository:

```bash
uv run python apps/evolution_driver/evolver.py \
  --state /tmp/metering-self-evolve.jsonl \
  < EVOLUTION_REQUEST.json
```

Use `apps/mutator/pi_skill_proposer.py` only with a pinned Pi model/provider and
caller-approved proposal context. State generation, consecutive-rejection, and
wall-clock limits before execution. The driver resumes only a verified matching
ledger and never installs its selected head. Do not expose protected evaluator
cases or per-case evidence to the proposer. Reserve an untouched final suite.

## Git-backed adapter or model output

Read `artifacts/git/README.md` before evolving source or build outputs. Use
`git_artifact.py` to create the parent descriptor,
`pi_git_proposer.py` as Mutator's external proposer, and
`git_candidate_adapter.py` as Candidate Runner's fixed resolver. Bind source to
an immutable commit, tree, and portable content SHA-256. Bind model checkpoints
or other large outputs by URI and SHA-256; never use a mutable branch as
candidate identity.

Pi must edit a workspace without `.git`. Trusted bridge code creates and
publishes the commit only after visible checks. Keep the fixed executor,
protected evaluator, and artifact credentials outside candidate access. Run the
builder and executor in reviewed containers or VMs. A selected descriptor is
run-local evidence; do not merge its branch, install its adapter, or serve its
model without a separate explicit operation.

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
