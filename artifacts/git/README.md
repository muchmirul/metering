# Git-backed evolution artifacts

This directory is an agent-neutral external candidate bridge for Metering's
frozen control plane. Concrete Pi and Prime Agent workspace translations live
under [`connectors/fixed/`](../../connectors/fixed/README.md). The bridge does
not add a seventh semantic stage. The existing six apps
still own variation, execution, observation, measurement, retention, and one
generation; Evolution Driver still owns bounded recurrence.

The bridge makes source code and externally stored outputs first-class
candidates without hiding them in `SKILL.md`:

```text
selected git-candidate-v1
    -> Mutator invokes one fixed agent Git proposer
    -> the external agent edits a disposable file-only workspace
    -> visible validation and optional build/output command run
    -> trusted bridge creates and publishes an immutable Git commit
    -> Candidate Runner invokes git_candidate_adapter.py for both candidates
    -> fixed executor verifies/runs each checkout under matched controls
    -> existing Observer, Assay, Gate, Controller, and Driver select and persist
```

## Artifact contract

A normalized candidate descriptor is:

```json
{
  "artifact_schema":"git-candidate-v1",
  "commit":"LOWERCASE_GIT_OBJECT_ID",
  "content_sha256":"SHA256_OF_PATHS_MODES_AND_BLOBS",
  "entrypoint":"adapter.py",
  "git_tree":"LOWERCASE_GIT_TREE_ID",
  "outputs":[
    {
      "kind":"model_checkpoint",
      "name":"candidate-checkpoint",
      "sha256":"EXTERNAL_CONTENT_SHA256",
      "uri":"artifact://checkpoints/candidate-17"
    }
  ],
  "repository":"PINNED_CALLER_APPROVED_REPOSITORY"
}
```

Candidate identity is Metering's existing SHA-256 over this complete normalized
artifact. A branch is deliberately absent: branches organize proposals but are
mutable and never control retention. The commit, Git tree, portable content
SHA-256, and external output digests are authoritative.

Git trees may contain only regular UTF-8-named paths with Git modes `100644` or
`100755`. Symlinks, submodules, escaping paths, duplicate output identities,
missing entrypoints, mismatched trees, and mismatched content hashes fail.
Large binaries remain outside Git; `outputs` binds their URI and SHA-256 into
the selected candidate.

## Components

- `git_artifact.py` verifies an existing commit and emits its initial descriptor.
- `git_proposer.py` owns shared trusted clone, validation, build, commit, and
  publication mechanics without launching a model.
- `connectors/fixed/{pi,prime_agent}/git_proposer.py` each let one concrete agent
  edit the workspace without `.git`; these are the canonical provider entry points.
- `git_candidate_adapter.py` verifies the descriptor and checkout, then passes it
  to one fixed executor command. It never executes candidate files itself.
- `demo_validate.py`, `demo_model_builder.py`, `demo_executor.py`, and
  `demo_evaluator.py` are deterministic protocol doubles.
- `demo.py` runs one complete live-Pi generation in a caller-selected new
  directory.

## Builder configuration

The proposer uses caller-controlled environment variables:

```text
METERING_GIT_REPOSITORY             exact allowed repository
METERING_GIT_REF_PREFIX             append-only candidate branch prefix
METERING_GIT_ALLOWED_PATHS_JSON     paths agent/building may change
METERING_GIT_VALIDATE_COMMAND       visible validation command array
METERING_GIT_VALIDATE_TIMEOUT       validation timeout
METERING_GIT_BUILD_COMMAND          optional build/output command array
METERING_GIT_BUILD_TIMEOUT          build/output timeout
METERING_PI_COMMAND                 pinned Pi command array
METERING_PRIME_AGENT_COMMAND        pinned Prime Agent command array
```

The optional build command receives this JSON on standard input:

```json
{
  "context":{},
  "parent_artifact":{},
  "protocol_version":1
}
```

It returns exactly `{"outputs":[]}`. A caller-selected external builder may
store an output outside Git and return its immutable receipt here. The checked-in
demo builder writes a tiny deterministic checkpoint; it proves the contract and
digest binding, not useful model production or quality.

## Runtime configuration

`git_candidate_adapter.py` is selected as Candidate Runner's adapter command and
receives protocol version 2. Configure:

```text
METERING_GIT_REPOSITORY
METERING_GIT_EXECUTOR_COMMAND
METERING_GIT_EXECUTOR_TIMEOUT
```

The fixed executor receives the verified checkout path, complete artifact,
candidate ID, and unchanged task. It owns container/VM isolation, environment
SDK access, action and compute budgets, and verification/fetching of every
external output URI. Parent and challenger use the same executor command.

## Deterministic proof

```bash
uv run --extra test pytest -q tests/test_git_artifact_evolution.py
```

The test creates a separate bare repository, uses fake Pi to change only
`adapter.py`, emits a hash-addressed model output, executes parent and challenger
through the complete existing loop, promotes the challenger, resumes without an
append, rejects disallowed paths and content tampering, and verifies the trusted
core files were not modified.

## Live Pi demo

Pin Pi and choose a directory that does not exist:

```bash
export PI_PROVIDER=openai-codex
export PI_MODEL=gpt-5.6-sol
export PI_REASONING_LEVEL=max
export METERING_PI_COMMAND='["pi","--provider","openai-codex","--model","gpt-5.6-sol","--thinking","max"]'
uv run python artifacts/git/demo.py \
  --root /tmp/metering-git-live-$(date +%s)
```

The expected Git diff is:

```diff
-ANSWER = "BASELINE"
+ANSWER = "ADAPTED"
```

The challenger passes one declared case, publishes an immutable candidate
branch, and contains a verified demo `model_checkpoint` output. This proves the
Git/output mechanism for that constructed run, not performance on an external
benchmark or useful model improvement.

## Security and lifecycle boundary

Agent tools and validation/build commands are not sandboxed by these Python files.
Run the complete proposer inside a disposable container or VM with no protected
evaluator mount, host credentials, or network by default. Run candidate source
only through a separately reviewed executor sandbox. The path allowlist and Git
checks are defense-in-depth, not an isolation boundary.

A failed generation never advances Evolution Driver's selected parent, but Git
branches, checkpoints, or other build products created before a later failure
may remain as unselected garbage. Artifact-store retention and cleanup are
caller responsibilities. Selection never installs, serves, merges, or deploys
the winning branch/model automatically.
