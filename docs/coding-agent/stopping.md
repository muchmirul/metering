# Agentvolve stopping policies

Agentvolve Level-1 solution evolution supports a numeric round limit and an
optional evaluator-backed development goal. Every run remains finite.

This page uses **round** for one selected parent (the seed first, then a
Population allocation), one child proposal, matched parent/child evaluation,
and one archive refresh. A round is sometimes informally called a loop. It is
not an individual model turn or an in-game action.

## Two modes

### Numeric limit only

Every task profile declares finite limits. Omit `stopping` to continue until the
first configured limit applies:

```json
{
  "limits":{
    "max_proposal_calls":100,
    "max_rounds":100,
    "max_wall_seconds":100000
  }
}
```

This is only an excerpt; a complete canonical profile must contain all fields in
the [task-profile reference](task-profile.md). A Level-1 profile accepts from 1
to 256 rounds. `max_proposal_calls` must be at least `max_rounds`; reservations
above that count are available only for explicit retries.

### Evaluated goal or numeric limit

Add a worded `goal` and the versioned `stopping` policy:

```json
{
  "goal":"Solve this until we finish the game.",
  "limits":{
    "max_proposal_calls":100,
    "max_rounds":100,
    "max_wall_seconds":100000
  },
  "stopping":{
    "minimum_replicates":1,
    "type":"all-development-cases-pass-v1"
  }
}
```

The run stops at whichever occurs first:

1. an independently evaluated development archive proves the configured goal;
2. `max_rounds` is reached; or
3. another finite proposal, wall-reservation, resource, archive, or final-seal
   condition stops recurrence.

The finite numeric fallback is mandatory. Agentvolve never accepts an unbounded
"continue until done" request.

## What the words do

`goal` is bounded text passed to the fixed proposer as mutation guidance. It is
not parsed as a trusted predicate. A candidate cannot end recurrence by writing
"finished," calling `finish`, or claiming success in model output.

`all-development-cases-pass-v1` is fixed control-plane logic. After each round,
it inspects the latest independently computed development archive and requires
one member that:

- passed Population survival/admission checks;
- has at least `minimum_replicates` accumulated evaluations; and
- passed every accumulated public development case.

When those conditions hold, the Driver returns
`development_goal_reached` and does not create an unused next-parent allocation.
Protected-final cases are never consulted. Final selection and the protected
assay still run once, after development has stopped.

Increasing `minimum_replicates` requests stronger repeated evidence. It cannot
exceed `max_rounds`. Because all accumulated public cases must pass, an earlier
failed replicate for the same candidate remains part of its reliability
record.

## Exact draws for a numeric cap

A profile binds exactly `max_rounds - 1` rational recurrence draws even if goal
stopping may leave some unused. For 100 rounds, provide 99 draws. This prints a
canonical fixed-zero draw array suitable for insertion into a profile:

```bash
uv run python - <<'PY'
import json
rounds = 100
draws = [{"denominator": 1, "numerator": 0} for _ in range(rounds - 1)]
print(json.dumps(draws, separators=(",", ":"), sort_keys=True))
PY
```

Explicit draws are part of the run identity and make allocation replayable. They
are not a hidden random seed. A caller may choose other valid rational draws.

## Stop statuses

| Status | Meaning |
|---|---|
| `development_goal_reached` | A feasible archived candidate met the evaluator-backed public goal. |
| `round_limit` | The run completed `max_rounds` without an earlier stop. |
| `proposal_call_limit` | No approved proposal-call reservation remains. |
| `wall_reservation_limit` | Another round would exceed timeout reservations. |
| `candidate_cost_limit` | Another matched evaluation would exceed a resource coordinate. |
| `empty_archive` | No retained candidate can be allocated. |
| `final_evidence_sealed` | Final work has begun, so development cannot reopen. |

If the goal is first proven on the last permitted round,
`development_goal_reached` is the reported development status. Offline
verification replays the same predicate from canonical records.

## Interactive-game use

For a game, fixed adapter code must map the authoritative game state to a public
development-case pass—for example, pass only when the environment reports the
game finished. The worded goal alone is insufficient.

`max_rounds` limits evolution rounds, not actions within one gameplay episode. A
game adapter must separately bind action, reset, token, model-call, and episode
budgets. The current coding harness supports `execute`, `delegate`, and `finish`;
a persistent ARC-style action adapter is a separate implementation requirement.

## Compatibility and scope

- Existing profiles without `stopping` retain numeric limit-only behavior and
  their identities do not change.
- The optional policy is included in new task, runtime, and Driver configuration
  identities and the canonical Driver ledger.
- The same policy is available in the generic Population Driver request.
- The checked-in Level-2 harness reference remains a fixed two-round
  configuration; this task-profile setting controls Level-1 solution evolution.

Next: [task profile](task-profile.md), [operations](operations.md), or
[architecture and threat model](architecture.md).
