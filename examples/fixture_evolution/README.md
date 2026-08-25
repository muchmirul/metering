# Fixture evolution

This is one compact information-guided judge built on `evo.step()`.

The candidate value is:

```json
{"hypothesis":"v3","confidence_bps":5000}
```

The proposer changes only confidence from `5000` to `7500`. The judge:

```text
chooses informative probes
captures parent and challenger forecasts
reveals the hidden fixture result
measures target surprisal
compares mean loss
selects parent or challenger
```

Run the case where the mutation helps:

```bash
uv run python examples/fixture_evolution/main.py --active v3
```

Run the case where the same mutation regresses:

```bash
uv run python examples/fixture_evolution/main.py --active v4
```

The example deliberately uses direct functions rather than six subprocess
applications. Observation, forecast expression, log-loss evaluation, and the
selection threshold are judge-local details, not Evo abstractions.
