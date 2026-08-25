# Pi skill evolution

This example treats one Markdown skill as an Evo candidate and delegates
proposal and judging to one external command.

Run the deterministic adapter test double:

```bash
uv run python examples/pi_skill_evolution/main.py \
  --skill examples/pi_skill_evolution/SKILL.md \
  --adapter "uv run python examples/pi_skill_evolution/demo_adapter.py"
```

The demo proposes one instruction and selects it with one deterministic hidden
check. It is a protocol test, not a claim of autonomous improvement.

## Adapter protocol

The adapter receives one JSON object on standard input and emits one JSON object
on standard output.

### Propose

Request:

```json
{"action":"propose","candidate":{"id":"...","text":"..."}}
```

Response:

```json
{"candidate":{"id":"...","text":"modified skill"}}
```

The example independently recomputes the content ID and rejects a mismatch.

### Judge

Request:

```json
{
  "action":"judge",
  "parent":{"id":"...","text":"..."},
  "challenger":{"id":"...","text":"..."}
}
```

Response:

```json
{"selected_id":"...","evidence":{"checks":[]}}
```

`selected_id` must identify the parent or challenger; Evo enforces this.

## Pi or Prime Agent integration

A real adapter may use Pi or Prime Agent to:

```text
propose a bounded skill edit
run parent and challenger on identical hidden tasks
collect tests, safety checks, latency, and cost
select one identity
return the complete evidence
```

Model providers, sessions, sandboxes, and task datasets remain outside this
repository. Replacing the adapter does not change `evo.step()`.
