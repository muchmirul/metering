# Reviewed OCI kernel profile

This directory supplies the concrete live isolation profile for
`evolutionary-harness-v1`. Docker is a platform prerequisite; the Python package
does not depend on it.

## Build and identify the image

Choose and review an immutable Python base digest, then build from the repository
root:

```bash
docker build \
  --file apps/harness/isolation/Containerfile \
  --build-arg PYTHON_IMAGE='python:3.12.8-slim-bookworm@sha256:<reviewed-digest>' \
  --tag registry.example/metering-harness-runtime:ipython-8.31.0 \
  .
docker push registry.example/metering-harness-runtime:ipython-8.31.0
docker image inspect \
  registry.example/metering-harness-runtime:ipython-8.31.0 \
  --format '{{json .RepoDigests}}'
```

Copy `runtime.pi.example.json` outside the candidate repository and replace its
all-zero placeholder image digest with the pushed `name@sha256:<digest>`. Review
and pin the agent version, provider, model, reasoning, kernel limits, model
call/output/timeout limits, and supported dependency-lock digest. For Prime
Agent, set connector `prime-agent-v1` and its
exact `prime-agent --version` value. The resulting canonical file is copied into
the experiment directory and its SHA-256-derived `runtime_id` is immutable for
that run.

A local image ID alone is not accepted by the profile: use a registry digest or
another reviewed Docker image reference with an immutable manifest digest.
Changing the image, model settings, command, dependency allowlist, observation
requirements, or limits creates another runtime identity.

## Enforced invocation

The host supervisor constructs the Docker command. Candidates cannot add flags
or mounts. The fixed profile uses:

- `--network none`;
- `--read-only`, a size-bounded `/tmp` tmpfs, and no shared IPC namespace;
- `--cap-drop ALL` and `no-new-privileges`;
- numeric non-root UID/GID `65532:65532`;
- explicit pids, memory, CPU, file-descriptor, and core-dump limits;
- no host path, Docker socket, device, credential, or evaluator mount; and
- a fixed kernel-server command from the immutable image.

Candidate bootstrap and model-generated cells enter over stdin only. Model
credentials remain in the tool-free host connector and are never passed into the
container. Candidate policy cannot enable network, host tools, Pi extensions, or
another command.

On Linux/cgroup v2, the host resolves the container PID through `docker inspect`
and reads `cpu.stat`, `memory.peak`, `pids.peak`/`pids.current`, and `io.stat`.
Live execution fails closed if CPU, memory, process, storage, or wall observation
is unavailable. The tmpfs bound enforces writable storage even when cgroup I/O
reports zero physical writes.

Set `METERING_DOCKER_BIN` only to a reviewed Docker-compatible executable. The
current schema deliberately accepts `docker-v1` only; Podman, Kubernetes,
bubblewrap, and VM transports require separately reviewed profiles rather than
silent command substitution.

## Conformance and run

Before model inference, `experiment.py` runs boot, execute, interrupt, hard
timeout, snapshot, restore, cleanup, restart recovery, and shutdown conformance
against the exact image and candidate bootstrap. A standalone command is:

```bash
uv run python apps/harness/conformance.py \
  /absolute/path/runtime.pi.json apps/harness/reference
```

Then run the bounded experiment:

```bash
uv run python apps/harness/experiment.py \
  pi /tmp/metering-harness-pi /absolute/path/runtime.pi.json
```

An unsupported host fails before candidate acceptance. Docker absence, inability
to create the container, missing cgroup observations, image/dependency mismatch,
agent version mismatch, and unavailable model credentials are explicit failures;
they do not fall back to host execution.

`process-fixture-v1` is only a deterministic CI mechanism. Its receipts say
`enforced:false` and `fixture-host-process`, and live connector commands reject
it unless the explicit unsafe fixture switch is present.
