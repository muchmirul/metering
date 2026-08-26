# Fixed connectors

A fixed connector receives only one role-specific protocol request and starts one
caller-pinned agent command. It loads no ambient session, context file, skill,
extension, prompt template, or theme unless the connector explicitly supplies
the content-identified candidate.

Each implemented harness exposes:

```text
skill_proposer.py   parent candidate + approved context -> complete SKILL.md
text_runner.py      candidate + public text task -> forecast + submission
git_proposer.py     immutable Git parent + approved context -> Git challenger
```

Pi commands may be pinned with `METERING_PI_COMMAND`, a JSON string array. It
falls back to `PI_BIN` and then `pi`. Prime Agent commands use
`METERING_PRIME_AGENT_COMMAND`, then `PRIME_AGENT_BIN`, then `prime-agent`.
A command array can include explicit provider, model, reasoning, or wrapper
arguments without shell parsing. Each connector uses a minimal temporary harness
configuration by default; the provider README documents the explicit reviewed
configuration override and credential boundary.

The surrounding Mutator and Candidate Runner own finite timeouts. The connector
owns only CLI translation and strict response decoding. Model/tool/token/budget
matching and OS isolation remain caller responsibilities.

The former Pi paths under `apps/` and `artifacts/git/` are compatibility
launchers. New requests and documentation should use `connectors/fixed/pi/`.
