# Agent connectors

Connectors make the source-only Metering applications usable from concrete agent
harnesses without putting an agent SDK, provider, model, or session runtime in
the installed `metering` package.

There are two directions:

```text
agent -> Metering       load connectors/tools/metering as an internal skill
Metering -> agent       invoke a reviewed fixed proposer or candidate runner
```

Metering remains the installed measurement tool. Source-only applications own
identity, evidence, retention, ledgers, and the concrete typed harness. Pi,
Prime Agent, or another external model transport proposes candidate artifacts
or returns one bounded action. A connector never receives protected evaluator
state and never decides retention.

## Layout

```text
connectors/
    tools/metering/          cross-harness Agent Skills tool
    fixed/
        pi/                  Pi artifact, typed-harness, and isolated coding translations
        prime_agent/         Prime Agent artifact and typed-harness translations
    full_context/            parked manifest-based profile
    live_agent_acceptance.py real-harness Metering tool acceptance
```

The fixed connectors use strict JSON standard streams and direct command arrays.
They are concrete integrations, not a provider registry or plugin framework.
Common files under `fixed/` own only identical wire validation and process
mechanics.

## Live acceptance

With a model selector available to both installed harnesses:

```bash
uv run python connectors/live_agent_acceptance.py \
  --model llamacpp/local
```

The command launches the real `pi` and `prime-agent` binaries, explicitly loads
the shared Metering skill, requires each model to call Metering through its
native tool (`bash` or `ipython`), verifies the tool event, and checks the exact
Metering receipt. Each harness receives a temporary configuration containing
only its regular `models.json`; use provider environment authentication or an
explicit reviewed `METERING_PI_CONFIG_DIR` or
`METERING_PRIME_AGENT_CONFIG_DIR`. This is model inference and is deliberately
separate from the deterministic default test suite.

The same path is available through pytest:

```bash
METERING_RUN_LIVE_AGENT_TESTS=1 \
METERING_LIVE_AGENT_MODEL=llamacpp/local \
uv run --extra test pytest -q tests/test_connectors.py -m live_agents
```

A passing run proves only those installed harness versions, model configuration,
and one measurement request. It is not evidence that every model uses tools
reliably or that a candidate improved.

## Trust boundary

Connectors and agent commands execute with caller permissions. Historical
tool-enabled Git proposers require an external container or VM. The typed
Evolutionary Harness instead makes both provider calls tool-free and executes
candidate Python only in its reviewed no-network OCI kernel. The Darwinian
coding connector also keeps Pi tool-free on the host: only fixed helpers inside
that kernel can inspect or edit the archive, and fresh kernels run caller-owned
checks. The interactive project extension is reviewed host code and accepts no
model-supplied evaluator or task command. Docker, cgroup-v2,
image preparation, and credentials remain platform prerequisites. Keep protected
evaluators, selected-parent state, credentials, and the frozen control plane
outside candidate access. Selection and installation remain separate.
