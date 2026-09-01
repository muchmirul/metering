# Fixed connectors

A fixed connector receives only one role-specific protocol request and starts one
caller-pinned agent command. It loads no ambient session, context file, skill,
extension, prompt template, or theme unless the connector explicitly supplies
the content-identified candidate.

Each implemented provider exposes:

```text
skill_proposer.py    parent candidate + approved context -> complete SKILL.md
text_runner.py       candidate + public text task -> forecast + submission
git_proposer.py      immutable Git parent + approved context -> Git challenger
harness_proposer.py  typed harness files -> bounded tool-free whole-file edit
harness_model.py     one fixed recursive-loop prompt -> one strict model action
harness_runner.py    verified Git harness -> isolated phenotype completion
```

The first three are the historical generic artifact connectors. The harness
commands translate the concrete [`apps/harness`](../../apps/harness/README.md)
contract. Candidate bootstrap/cells execute only through its reviewed OCI kernel
profile; provider CLIs remain tool-free and never receive selection authority.

Pi commands may be pinned with `METERING_PI_COMMAND`, a JSON string array. It
falls back to `PI_BIN` and then `pi`. Prime Agent commands use
`METERING_PRIME_AGENT_COMMAND`, then `PRIME_AGENT_BIN`, then `prime-agent`.
A command array can include explicit provider, model, reasoning, or wrapper
arguments without shell parsing. Each connector uses a minimal temporary harness
configuration by default; the provider README documents the explicit reviewed
configuration override and credential boundary.

The surrounding Mutator and Candidate Runner own finite timeouts. The connector
owns only CLI translation and strict response decoding. It rejects model JSON
numbers that overflow double precision or change whether a value is zero or one
during conversion. Historical skill/Git workspace roles still require caller
isolation when tools are enabled. The typed harness runner instead requires the
versioned OCI profile, verifies agent/provider/model/reasoning identity, disables
provider tools and ambient state, and emits externally observed receipts. Docker,
cgroup-v2 support, image construction, credentials, and provider availability
remain documented platform responsibilities.

The former Pi paths under `apps/` and `artifacts/git/` are compatibility
launchers. New requests and documentation should use `connectors/fixed/pi/`.
