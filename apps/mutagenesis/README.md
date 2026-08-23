# Mutagenesis

`mutagenesis.py` is an agent-facing measurement step, not an autonomous
evolution system.

```text
agent observes, models, and mutates
              |
              v
      mutagenesis measures
              |
              v
agent compares, selects, and repeats
```

The application contains no neural architecture, environment, mutation
generator, selection policy, loop, memory, or stopping rule. An agent owns all
of those decisions.

## Documentation

- [Architecture](docs/architecture.md) explains the responsibility boundary
  and why the adapter stays this small.
- [Agent protocol](docs/agent-protocol.md) specifies the implemented JSON
  request, response, infinity representation, and errors.

## Request

The command reads one strict JSON object from standard input:

```json
{"candidate":"mutation-17","target_probabilities":[0.5,0.25,1.0]}
```

- `candidate` is an opaque non-empty identifier chosen by the agent.
- Each `target_probabilities` item is the candidate model's probability for
  the target outcome observed by the agent in one caller-defined situation.
- Ordering and the meaning of every situation remain with the agent.

The application does not estimate, normalize, smooth, or repair these
probabilities.

Run it from the repository root:

```bash
printf '%s\n' \
  '{"candidate":"mutation-17","target_probabilities":[0.5,0.25,1.0]}' \
  | uv run python apps/mutagenesis/mutagenesis.py
```

## Response

The command returns the candidate identifier, the self-information of each
target outcome in bits, and their arithmetic mean:

```json
{"candidate":"mutation-17","measurement":{"aggregate":{"infinite":false,"mean_target_surprisal_bits":1.0},"base":2.0,"metering_measure":"self_information","outcomes":[{"infinite":false,"target_probability":0.5,"value_bits":1.0},{"infinite":false,"target_probability":0.25,"value_bits":2.0},{"infinite":false,"target_probability":1.0,"value_bits":0.0}]}}
```

The arithmetic mean is application-owned aggregation, not a fifth Metering
measure or a general score. If any supplied target probability is zero, its
self-information and the aggregate are represented with `"infinite":true` and
a null value rather than invalid JSON.

Malformed JSON, duplicate or extra keys, unsupported arguments, and invalid
probabilities fail with exit status 2 and one canonical JSON error on standard
error.

## Agent responsibility

An agent may call this once per candidate and compare the named measurements.
The agent must still define:

- what it observed;
- how its model constructed every target probability;
- what was mutated;
- how candidates are compared;
- whether a mutation is retained; and
- when to continue or stop.

Lower mean target surprisal for caller-declared outcomes does not establish
general adaptation, correctness, meaning, understanding, intelligence, or
usefulness.
