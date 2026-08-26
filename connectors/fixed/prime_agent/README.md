# Prime Agent fixed connector

These commands translate the same Metering protocols to the public
`prime-agent` CLI:

```text
uv run python connectors/fixed/prime_agent/skill_proposer.py
uv run python connectors/fixed/prime_agent/text_runner.py
uv run python connectors/fixed/prime_agent/git_proposer.py
```

The skill proposer and text runner disable tools, sessions, discovered resources,
and context files, then inject only the verified candidate skill. The Git
proposer permits Prime Agent's IPython tool inside a disposable file-only
workspace and therefore requires an external sandbox.

Pin the command with a JSON array, for example:

```bash
export METERING_PRIME_AGENT_COMMAND='["prime-agent","--provider","openai-codex","--model","gpt-5.6-sol","--thinking","max"]'
```

Prime Agent remains an external proposer or runner. By default the connector
creates a temporary configuration directory and copies only regular
`auth.json` and `models.json` files from the normal configuration root; it does
not copy settings, sessions, logs, or continual-harness state. Set
`METERING_PRIME_AGENT_CONFIG_DIR` to an existing absolute caller-reviewed
configuration directory when a different credential/model catalogue is needed.
The Git proposer does not copy `auth.json`; supply model authentication through
a sandbox-scoped environment or command. Never point its reviewed configuration
at a directory containing credentials accessible to candidate code. The
connector never receives selection authority or protected evaluator data.
