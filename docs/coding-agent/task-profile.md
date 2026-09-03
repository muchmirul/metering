# Agentvolve coding task profile

An Agentvolve Level-1 task is one canonical JSON object followed by one newline.
It binds an immutable repository base, writable paths, development checks,
finite budgets, exact allocation draws, and a separately permissioned
protected-final profile.

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

Development checks are reviewed argv arrays, not shell strings. A zero exit
status before timeout is a pass. Each candidate/check pair runs in a separate
fresh container.

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
`final_assay.sha256` authenticates its exact bytes. Fixed code opens and copies
the profile only after development recurrence has stopped and final allocation
has been recorded.

Protected checks never enter mutation prompts, development requests, Population
development archives, or ancestry feedback. A final failure seals the run and
cannot trigger more search.

## Validation rules

Before execution, fixed code requires:

- normalized absolute repository and profile paths;
- final-profile separation from the repository;
- profiles no larger than 2 MiB;
- unique sorted relative POSIX writable paths;
- no `.git`, traversal, backslashes, NUL, symlink, or device semantics;
- non-empty reviewed argv commands;
- unique case IDs within each suite;
- finite positive per-check and global bounds;
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
checks run. Final evidence never changes the selected candidate.

For workspace and trust details, see the [architecture and threat model](architecture.md).
For commands, see the [operations guide](operations.md).
