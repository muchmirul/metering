# Agentvolve coding task profile

An Agentvolve Level-1 task is one canonical JSON object followed by one newline.
It binds an immutable repository base, writable paths, development checks,
finite budgets, exact allocation draws, and a separately permissioned
protected-final profile. A caller may author it directly, select it from the
configured task directory, derive it with `/goal` and `/limit`, or approve a
session-generated draft; all four routes produce this same schema and authority.

## Interactive registration and derivation

`METERING_EVOLUTION_TASKS_DIR` defaults to the checkout sibling
`metering-live-tasks`. The Pi adapter discovers at most 200 direct
`*.task.json` files there. `/goal` offers current-repository contract summaries
for direct selection, even when only one matches, or prepares a new draft. TUI
and RPC both require task approval; an explicitly configured profile must match
the current repository. Fixed Python validation remains decisive at start.

Set `/limit N generations` (1–256), then `/goal TEXT`; a missing limit is
prompted before drafting. The last limit persists, including after a launch or
session restore; changing it never changes a running task. When a reviewed
contract is selected, fixed code derives a fresh profile and keeps its
entrypoint, allowed paths, checks, final binding, final draw, and
stopping policy; preserves the wall limit unless the operator explicitly enters
a correction for the new profile; resolves the current clean repository `HEAD`; writes `N - 1`
fixed rational recurrence draws; and preserves the template's finite retry
reservation count. The derived profile is written below the task directory's
`generated/` subdirectory.

With no selected contract, `/goal` and model-facing `workflow_from_session`
use the explicit reviewed draft path. The outer model receives user messages only, never assistant
answers or tool output, plus the current commit's bounded tracked-file list. The
operator first sees a human-readable review containing the complete goal,
repository, entrypoint, writable paths, check argv, budgets, stopping policy,
and final policy. Canonical JSON is an optional advanced correction surface,
not required conversational input. The exact slash-command goal, repository,
and saved generation limit are user-bound, not selectable by the drafting model.
Declining, cancelling, or an invalid task starts no worker. Fixed code requires a clean Git
repository and an entrypoint present at `HEAD`, writes canonical task/final
documents outside the repository, and validates the task. Its
`replay-development-checks-v1` final policy repeats the reviewed development
checks in fresh protected-final containers; this gives final execution/sealing
but intentionally makes no hidden-coverage claim. Use a separately authored
profile when held-out cases matter.

Neither route can infer whether a check actually represents a natural-language
goal. That remains operator responsibility. Missing or ambiguous executable
checks are errors, not permission for the proposer to judge itself.

## Development profile

```json
{
  "allocation_draws":[{"denominator":1,"numerator":0}],
  "allowed_paths":["src/example.py"],
  "development_checks":[
    {
      "argv":["python","-m","unittest","-q","tests/test_example.py"],
      "case_id":"visible-tests",
      "timeout_ms":20000
    }
  ],
  "final_assay":{
    "path":"/absolute/operator-approved/protected-final.json",
    "sha256":"0000000000000000000000000000000000000000000000000000000000000000"
  },
  "final_draw":{"denominator":1,"numerator":0},
  "goal":"Fix src/example.py without changing its public interface.",
  "limits":{
    "max_proposal_calls":4,
    "max_rounds":2,
    "max_wall_seconds":100000
  },
  "repository":{
    "base_commit":"IMMUTABLE_GIT_COMMIT",
    "entrypoint":"src/example.py",
    "path":"/absolute/operator-approved/repository"
  },
  "schema_version":1,
  "stopping":{
    "minimum_replicates":1,
    "type":"all-development-cases-pass-v1"
  },
  "task_schema":"darwinian-coding-task-v1"
}
```

`repository.base_commit` must resolve in the declared repository. Candidate
commits form a first-parent lineage from that exact base. The repository itself
is never mounted into a candidate container or modified by the experiment.

`allowed_paths` are writable path prefixes. Candidates may inspect the imported
repository but persisted changes outside these prefixes fail validation.

Development checks are reviewed argv arrays, not shell strings. Each
candidate/check pair runs in a separate fresh container. The legacy form above
passes on exit zero without timeout: it **does not prove that intended assertions
ran**. Candidate code can terminate early or interfere with in-process checks.
Preflight explicitly warns when either suite contains these legacy checks.

### Externally checked output values

For Level 1, add the versioned output contract to a development or final check:

```json
{
  "argv":["python","-c","import json; from solver import solve; print(json.dumps({'answers':[solve(2),solve(3)]}))"],
  "case_id":"output-values",
  "check_schema":"stdout-json-v1",
  "expected_stdout":{"answers":[4,9]},
  "timeout_ms":20000
}
```

The operator supplies the expected values. Only argv and timeout enter the
sandbox; the fixed host evaluator compares authenticated stdout with the bound
`expected_stdout` outside candidate control. Exit zero without timeout is still
required. Stdout must contain exactly one strict JSON object; whitespace and key
order are immaterial, but missing/extra fields or answers, duplicate keys,
non-finite numbers, extra output, and JSON type changes fail. An integer is not a
boolean or floating-point number. Empty output and `{"passed":true}` cannot
substitute for the declared answer values.

`expected_stdout` must be a non-empty object whose canonical JSON is at most
65,536 characters. Output contracts are explicit opt-ins, not inferred from argv
or goal text. A trivial expected pass marker is still a weak criterion; matching
outputs does not prove internal assertion control flow or coverage beyond these
operator-chosen cases. Existing Level-2 coding fixtures remain exit-status checks.

Task/final profile schema names stay v1; each output check carries its own
`stdout-json-v1` contract and produces a v2 evaluation receipt. Existing checks,
profile identities, and v1 receipt replay retain their previous meanings.

## Goal or numeric stopping

See the dedicated [stopping-policy guide](stopping.md) for complete semantics,
statuses, 100-round setup, replay behavior, and interactive-game boundaries.

`goal` is bounded natural-language guidance for the fixed proposer. For example,
a game adapter could use `"Solve this until we finish the game."` The model's
claim that it finished is never stop authority. The independently evaluated
public case must report pass.

There are two supported configurations:

- omit `stopping` to run until a numeric/resource limit; or
- include `all-development-cases-pass-v1` to stop when a feasible archived
  candidate has passed every accumulated development case for at least
  `minimum_replicates` evaluations.

The numeric `limits.max_rounds` is mandatory in both modes and is always the
finite fallback. Thus `max_rounds: 100` means at most 100 mutation/evaluation
rounds, while the example `stopping` policy may end the run sooner with
`development_goal_reached`. A 100-round profile also binds 99 exact allocation
draws and at least 100 proposal-call reservations. Protected-final checks never
participate in the goal predicate.

## Development timeout reservations

`max_wall_seconds` is the Driver's development timeout-reservation budget, not
elapsed model time or a total-workflow deadline. Fixed review/preflight computes
the same Controller reservation used by the Driver and adds the evidence-adapter
timeout. More development checks or longer check timeouts can increase it.

With one 120,000 ms check, the existing timeouts are 1,800 seconds for the
proposer, 600 for the runner, and 300 for the evaluator. Controller margins and
matched parent/challenger execution require 3,380 seconds, plus 300 for evidence:
**3,680 seconds per generation; 7,360 for two without retries**. Harness work,
protected-final work, and extra retry reservations are not part of this estimate.

New registration, derivation, worker starts, and Level-1 starts reject budgets
that cannot reserve one round with `wall_reservation_limit` and numeric details.
A budget that funds one but not all requested rounds is accepted with a warning:
the generation limit remains a cap, not a guarantee. No Driver timeout, reservation,
retry, retention, or stopping rule changes.

Pi calculates this before registration/derivation, shows the per-generation and
full-cap amounts at review, and prompts for explicit integer seconds when no
round is affordable. Cancelling starts no worker. Corrections apply only to a
new reviewed profile, never the template or an existing run. CLI derivation
preserves the template budget unless its optional final argument is supplied:

```text
uv run python -m apps.coding_agent.task_profile_tool derive TEMPLATE.task.json GOAL.txt MAX_ROUNDS TASK-DIRECTORY [MAX_WALL_SECONDS]
```

The read-only operator boundary is `task_profile_tool budget REVIEW.json`, where
`REVIEW.json` is exactly:

```json
{"check_timeouts_ms":[120000],"max_rounds":2,"max_wall_seconds":1800}
```

It returns `agentvolve-development-reservation-v1` diagnostic JSON with the
Controller/evidence/per-round reservations, requested-cap total, and
`funded_rounds_without_retries` (zero here). It validates exact JSON types,
duplicate/extra keys, check-count/timeout bounds, and finite round/wall limits.
It reads no task/final profile and executes no check, model, or candidate.
An affordable or unaffordable valid review exits 0; malformed input exits 2
with an error on stderr. This is a diagnostic, not permission to launch.

Existing profiles still parse with the same identities and offline replay;
new-start rejection does not migrate their evidence. A frozen, unfundable run
cannot advance by resuming: use explicitly approved incomplete closure, then a
separately reviewed replacement task. Do not edit its limits in place.

## Protected-final profile

The final profile is also canonical JSON plus one newline:

```json
{
  "checks":[
    {
      "argv":["python","-c","from src.example import solve; assert solve(2)==4"],
      "case_id":"protected-edge-case",
      "timeout_ms":20000
    }
  ],
  "final_schema":"darwinian-coding-final-v1",
  "schema_version":1
}
```

`final_assay.path` is an absolute path outside the repository.
`final_assay.sha256` authenticates its exact bytes. Trusted operator preflight
reads it for structural validation, without returning protected contents or
running checks. Runtime opens/revalidates and copies it only after development
recurrence has stopped and final allocation has been recorded.

Protected checks never enter mutation prompts, development requests, Population
development archives, or ancestry feedback. A final failure seals the run and
cannot trigger more search.

## Validation rules

Run trusted preflight explicitly, before any expensive workflow:

```bash
uv run python -m apps.coding_agent.task_profile_tool preflight TASK.json
# Also check the selected harness/runtime identity binding:
uv run python -m apps.coding_agent.task_profile_tool preflight TASK.json RUNTIME.json SELECTED-HARNESS.json
```

Registration, derivation, and new Level-1 runs perform preflight automatically.
It launches no models, containers, or checks and returns only diagnostic metadata
and assurance warnings—not protected case IDs, commands, answers, or counts.
Protected parser failures are deliberately generic to avoid leaking their keys.
Sealed harness provenance and kernel conformance are still verified separately;
preflight is not proof of model availability or a well-designed benchmark.

Before Level-1 inference, fixed code requires:

- normalized absolute repository and profile paths;
- final-profile separation from the repository;
- profiles no larger than 2 MiB, with exact normalized JSON types (a boolean or
  floating-point `schema_version` is not integer version 1);
- unique sorted relative POSIX writable paths;
- no `.git`, traversal, backslashes, NUL, symlink, or device semantics;
- non-empty reviewed argv commands, at most 256 arguments of 4,096 characters each;
- unique case IDs within each suite;
- finite positive per-check and global bounds, with enough development wall
  reservation for at least one round at new-start preflight;
- exactly `max_rounds - 1` recurrence draws;
- at least `max_rounds` proposal-call reservations; and
- when present, a versioned stopping policy whose `minimum_replicates` does not
  exceed `max_rounds`.

Reservations above the round count are finite capacity for explicit retries.
Ordinary resume cannot consume one.

## Final selection

The declared final policy is lexicographic:

1. maximize development task rate;
2. maximize replicate reliability; and
3. use `final_draw` only to break a canonical candidate-ID tie.

The exact corresponding Population allocation is recorded before protected
checks run. Final evidence never changes the selected candidate. If development
stops without an archive, the wrapper reports the actual Driver stop reason and
round/proposal counts without final selection or protected execution. A budget
stop with a usable archive still proceeds to final.

For workspace and trust details, see the [architecture and threat model](architecture.md).
For commands, see the [operations guide](operations.md).
