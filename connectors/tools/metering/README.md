# Metering Agent Skill

`SKILL.md` is one Agent Skills-compatible internal-tool description for both Pi
and Prime Agent. Load it explicitly with either harness:

```text
--no-skills --skill connectors/tools/metering/SKILL.md
```

`invoke.py` forwards one request to the public `python -m metering` boundary from
a source checkout. It does not select a measure, alter a probability model, or
interpret the result.

The skill also documents the separate `metering-history` command. That command
requires Git and commits only canonical configuration, named result, and
provenance files before replay verification. `invoke.py` itself remains
filesystem-pure and never records implicitly.

Agents should read [`docs/capabilities.md`](../../../docs/capabilities.md) before
assuming population search, training, deployment, or generic scoring behavior.
The real-harness acceptance in `connectors/live_agent_acceptance.py` verifies
that Pi uses `bash` and Prime Agent uses `ipython` to call this exact tool.
