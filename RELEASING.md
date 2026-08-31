# Releasing Metering

Git tags published as GitHub Releases are the source of package versions. Do
not hard-code a package version in `pyproject.toml` or `src/metering/`.

## Version format

Use a numeric semantic-version tag:

```text
MAJOR.MINOR.PATCH
```

`setuptools-scm` derives package metadata from the checked-out tag. Untagged
development builds receive a generated development version.

The replacement of the historical hidden-fault harness is a breaking release.
Old run artifacts require the historical commit that created them; the new
package does not include a replay compatibility layer.

## Release checks

Start from a clean branch synchronized with its remote, then run:

```bash
uv run --extra test pytest -q
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering
history_dir="$(mktemp -d)"
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering-history record "$history_dir"
uv run metering-history verify "$history_dir"
uv run python apps/controller/controller.py \
  < apps/controller/agent-skill-example-request.json \
  > /tmp/metering-agent-generation.json
rm -f /tmp/metering-self-evolve.jsonl /tmp/metering-self-evolve.jsonl.lock
uv run python apps/evolution_driver/evolver.py \
  --state /tmp/metering-self-evolve.jsonl \
  < apps/evolution_driver/example-request.json \
  > /tmp/metering-self-evolve-result.json
uv run --extra test pytest -q tests/test_connectors.py -m 'not live_agents'
uv run --extra test pytest -q tests/test_git_artifact_evolution.py
uv build
```

The measurement smoke check must emit a finite entropy value of `1.0` at base
`2.0`; the history smoke check requires Git and must commit and replay-verify one
pair; the agent-skill
example must select its deterministic challenger; the bounded evolution smoke
must promote once, then stop after one retained-parent decision. The wheel should
contain only the four package modules and packaging metadata. The source
archive also contains tests, Markdown sources, build configuration, the
non-packaged applications under `apps/`, the external bridge under `artifacts/`,
and concrete source-only integrations under `connectors/`. Inspect both
archives for legacy harness modules, generated application runs or sandboxes,
caches, and other build output; none belongs in a release.

When one model is available through both installed harnesses, run the optional
live internal-tool conformance and preserve its report:

```bash
uv run python connectors/live_agent_acceptance.py \
  --model llamacpp/local \
  > /tmp/metering-live-agent-conformance.json
```

When a pinned Pi provider is intentionally available, the optional constructed
candidate acceptance can also be run once with a fresh state path:

```bash
state=/tmp/metering-signal-relay-$(date +%s).jsonl
uv run python apps/evolution_driver/signal_relay_acceptance.py \
  --state "$state" \
  > /tmp/metering-signal-relay-report.json
```

The Git-backed live demo is also optional when tool-enabled Pi execution is
intended:

```bash
uv run python artifacts/git/demo.py \
  --root /tmp/metering-git-live-$(date +%s)
```

These paid, model-dependent smokes are not deterministic release gates. Preserve
their reports when citing them, and do not describe published final cases as
untouched after reuse.

Create and push an annotated numeric tag only after those checks pass:

```bash
git tag -a 1.0.0 -m "Release 1.0.0"
git push origin 1.0.0
```

Do not move an existing release tag. Publish a new version when a release needs
correction.
