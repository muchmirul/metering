# Pi upgrades and experiment versions

The interactive Pi application and the experiment's Pi implementation are two
separate things. Updating interactive Pi must not silently change a recorded
experiment's implementation or make an older sealed harness appear to have been
evaluated under a newer runtime.

Agentvolve's Pi launcher now resolves the worker implementation **before creating
a workflow**. The adapter checks endpoint readiness but never starts/restarts a
model service. The resolver has no hardcoded maximum
Pi version. A manifest can pin a newer release when that release supplies the
required CLI isolation flags and JSON-event contract. The unchanged model adapter
still validates the final assistant message and resource fields at execution.
This does **not** guarantee that every future breaking Pi release is compatible.

## Existing runs after an interactive Pi upgrade

Suppose your interactive Pi is 0.85.1 and the sealed harness/runtime require
0.84.4. Agentvolve uses a separately installed 0.84.4 worker without downgrading
your interactive Pi or editing the runtime manifest.

Resolution is offline and ordered:

1. An explicit `METERING_PI_COMMAND` JSON argv array or `PI_BIN` executable must
   match the exact manifest version. A wrong explicit override is an error,
   not permission to select something else.
2. Without an override, use `pi` from `PATH` if its exact version matches.
3. Otherwise look for the required release at
   `~/.cache/metering/pi/VERSION/node_modules/.bin/pi`.
   `METERING_PI_RUNTIME_DIR` can name another absolute cache root.
4. Check `--version` and `--help` with bounded output/time. Required flags include
   tools/extensions/context/session isolation and JSON output support. Reject an
   absent, incorrectly labelled, or incompatible copy before workflow creation.

To prepare a copy explicitly (example version):

```bash
npm install --prefix "$HOME/.cache/metering/pi/0.84.4" --save-exact \
  @earendil-works/pi-coding-agent@0.84.4
```

Keep version-cache installations separate; do not upgrade them in place. An
existing reviewed installation can also be linked at that version's prefix.
Nothing installs or downloads automatically, searches arbitrary task directories,
or runs on extension loading/restoration. The only probes are help/version,
not inference. Paths to selected executables become absolute for worker launch.
The worker inherits the resolved command; your interactive session is unchanged.

## Check and recovery CLI

From the source checkout:

```bash
uv run python -m connectors.fixed.pi.runtime check RUNTIME.json
uv run python -m connectors.fixed.pi.runtime review RUNTIME.json HARNESS.json
uv run python -m connectors.fixed.pi.runtime review-configured RUNTIME.json HARNESS.json CONFIG_DIRECTORY
uv run python -m connectors.fixed.pi.runtime start-configured RUNS TASK.json RUNTIME.json HARNESS.json CONFIG_DIRECTORY APPROVED_REVIEW.json
# Legacy environment-configured launch:
uv run python -m connectors.fixed.pi.runtime start RUNS TASK.json RUNTIME.json HARNESS.json
uv run python -m connectors.fixed.pi.runtime resume WORKFLOW
uv run python -m connectors.fixed.pi.runtime retry WORKFLOW 'operator-approved reason'
```

These are connector CLI operations, **not new Pi slash commands**. `/goal` uses
the configured preflight and launch path after direct approval. Say “configure
Agentvolve” to select existing runtime/harness/worker config from the current Pi
session, with no environment exports, process restart or second interactive Pi.
`review-configured` takes the worker directory explicitly; legacy `review` additionally
requires a separate explicit `METERING_PI_CONFIG_DIR` with models.json and an
explicit compatible original sealed harness; it offline-verifies provenance and
returns worker configuration/model digest, exact implementation/runtime/harness
identities and budgets. Pi includes these in task review, then rechecks before
dispatch. No newest-harness discovery or implicit Level-2 setup is allowed. Missing
compatible setup requires separate operator approval/budget and Level-2 execution.

Pi version/configuration isolation is NOT immutable control-plane deployment.
Configured jobs use v2 orchestration requests and private bounded models/auth file
copies (0700 directory/0600 files, no symlinks or hardlinks). Command/version/runtime
and models hash are job-bound; auth may refresh. No interactive configuration files
are implicitly copied. Workers still load trusted code and runtime/harness provenance
from operator-managed installed paths. Use a separate reviewed stable installation;
editing a running worker's engine checkout or job-owned routing configuration is
unsafe. This limited copy is not a controller deployment framework or host Pi sandbox.

For recovery, `resume` and `retry` resolve the
runtime from the original canonical workflow request and, for configured v2 jobs,
the job-owned command/configuration rather than ambient overrides. Offline replay
requires neither private configuration nor a live Pi executable. Legacy v1 behavior
and evidence remain unchanged. They do not override replay/lock checks, extend generation or
proposal budgets, or authorize a retry themselves. A pending failed attempt still
needs an explicit operator-approved retry and retains its original evidence.

The shared `apps.coding_agent.agentvolve_worker` CLI and fixed connectors remain
available and strict. Direct callers of those low-level interfaces must provide
the correct executable themselves. Offline verification needs neither resolution
nor a model call and keeps its existing worker/solution CLI.

## Actually upgrading an experiment

To execute candidates with a newer Pi implementation, create/review a new runtime
manifest pinning that actual release. Its runtime ID changes. A harness sealed
under a different runtime is not automatically reusable: independent evaluation
and sealing under the new runtime are required. Do not rewrite historical
manifests, weaken exact-version checks, or call 0.85.1 "0.84.4".

The resolver checks the documented CLI contract rather than imposing a release
ceiling. It does not certify unseen SDK changes, provider semantics, host binaries,
GGUF weights, or future releases. CLI probes against installed 0.84.4 and 0.85.1
are non-inference checks; deterministic tests cover a hypothetical newer version,
missing flags, mismatches, cache selection, and no-effect failures. Real local
model acceptance remains a separate test.

## Recorded one-task local check

The username-normalization workflow `workflow-pi-20260907T224029246Z` completed
with interactive Pi **0.85.1**, automatically resolved worker Pi **0.84.4**, and
the existing sealed harness/runtime. It produced **two solution descendants**;
protected final checks passed **3/3**, with no safety failures. Separate offline
verification passed. The selected commit is
`08ee8f2dae3ce04cd43c5a478519a0842a304bdb`.

The initial version-mismatch failure remains in its ledger. One explicitly
operator-authorized retry used the matching cached release; there were three
recorded proposal attempts in total, not three solution generations. The source
repository stayed unchanged and the patch was not applied.

The original task uses legacy exit-status checks. A supplementary read-only,
network-isolated Docker check additionally compared actual stdout values for
seven public examples, including Unicode whitespace/casefolding and empty input.
It passed without reopening protected evaluation or modifying selection evidence.
Updated Pi also opened Trace Viewer over the real resulting commits; candidate
source/downloads, file history, reused harness attribution, and the preserved
initial failure were inspected in Chromium.

Local test evidence is under
`/mnt/Tforce/dev/metering-trace-live-one-20260907.9CiCXz/`; it is intentionally
outside this repository. This was the **one task requested by the operator**, not
a claim that the separate three-task acceptance suite ran.
