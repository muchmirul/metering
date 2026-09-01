# Pi fixed connector

These commands translate Metering's documented proposer and runner protocols to
the public `pi` CLI.

```text
uv run python connectors/fixed/pi/skill_proposer.py
uv run python connectors/fixed/pi/text_runner.py
uv run python connectors/fixed/pi/git_proposer.py
uv run python connectors/fixed/pi/harness_proposer.py
uv run python connectors/fixed/pi/harness_model.py
uv run python connectors/fixed/pi/harness_runner.py
```

The skill proposer and text runner disable tools, sessions, discovered resources,
and context files. They inject the complete verified `SKILL.md` because normal
Pi progressive disclosure needs a read tool. The historical Git proposer leaves
Pi's normal workspace tools enabled inside a file-only candidate workspace; it
must run in a reviewed external sandbox.

The typed harness path is stricter. `harness_proposer.py` supplies bounded
candidate locus text to a tool-free Pi call and applies only declared whole-file
edits. `harness_model.py` translates one provider-neutral turn with every Pi tool
and ambient resource disabled. `harness_runner.py` verifies Pi `--version` and
the runtime's provider/model/reasoning pins, then delegates recurrence, IPython,
subagents, snapshots, compaction, and receipts to fixed code under
[`apps/harness`](../../../apps/harness/README.md). Candidate Python runs only in
the required OCI kernel.

Pin the command with a JSON array, for example:

```bash
export METERING_PI_COMMAND='["pi","--provider","openai-codex","--model","gpt-5.6-sol","--thinking","max"]'
```

By default the connector creates a temporary Pi configuration directory and
copies only regular `auth.json` and `models.json` files for tool-free roles; it
does not copy settings, sessions, packages, or other ambient resources. Set
`METERING_PI_CONFIG_DIR` to an existing absolute caller-reviewed directory when
needed. The Git proposer does not copy `auth.json`; provide sandbox-scoped model
authentication through the environment or command, and never expose credentials
to candidate tools. The connector does not infer a model or retain a session. Harness commands use
`METERING_HARNESS_PROVIDER`, `METERING_HARNESS_MODEL`, and
`METERING_HARNESS_REASONING`; `experiment.py` derives these values from the
canonical runtime profile and rejects disagreement.
