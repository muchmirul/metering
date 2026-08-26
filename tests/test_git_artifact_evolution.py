from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "git"
GIT_ARTIFACT = ARTIFACTS / "git_artifact.py"
PI_GIT_PROPOSER = ROOT / "connectors" / "fixed" / "pi" / "git_proposer.py"
PRIME_GIT_PROPOSER = (
    ROOT / "connectors" / "fixed" / "prime_agent" / "git_proposer.py"
)
GIT_ADAPTER = ARTIFACTS / "git_candidate_adapter.py"
DEMO_VALIDATE = ARTIFACTS / "demo_validate.py"
DEMO_BUILDER = ARTIFACTS / "demo_model_builder.py"
DEMO_EXECUTOR = ARTIFACTS / "demo_executor.py"
DEMO_EVALUATOR = ARTIFACTS / "demo_evaluator.py"
DEMO = ARTIFACTS / "demo.py"
EVOLVER = ROOT / "apps" / "evolution_driver" / "evolver.py"
CANDIDATE_RUNNER = ROOT / "apps" / "candidate_runner" / "candidate_runner.py"
CORE_FILES = [
    ROOT / "apps" / "agent_protocol.py",
    ROOT / "apps" / "stdio_connector.py",
    ROOT / "apps" / "mutator" / "mutator.py",
    ROOT / "apps" / "candidate_runner" / "candidate_runner.py",
    ROOT / "apps" / "observer" / "observer.py",
    ROOT / "apps" / "forecast_assay" / "forecast_assay.py",
    ROOT / "apps" / "selection_gate" / "selection_gate.py",
    ROOT / "apps" / "controller" / "controller.py",
    ROOT / "apps" / "evolution_driver" / "evolver.py",
    ROOT / "artifacts" / "git" / "git_proposer.py",
    ROOT / "connectors" / "fixed" / "command.py",
    ROOT / "connectors" / "fixed" / "pi" / "git_proposer.py",
    ROOT / "connectors" / "fixed" / "prime_agent" / "git_proposer.py",
]


def encode(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def run(
    script: Path,
    request: dict[str, object],
    *arguments: str,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=ROOT,
        input=encode(request),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=timeout,
    )


def git(*arguments: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def seed_repository(tmp_path: Path) -> tuple[Path, str]:
    work = tmp_path / "seed"
    remote = tmp_path / "candidate.git"
    work.mkdir()
    git("init", "--quiet", cwd=work)
    git("config", "user.name", "Test", cwd=work)
    git("config", "user.email", "test@example.invalid", cwd=work)
    (work / "adapter.py").write_text('ANSWER = "BASELINE"\n', encoding="utf-8")
    git("add", "adapter.py", cwd=work)
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
    }
    committed = subprocess.run(
        ["git", "commit", "--quiet", "-m", "Seed candidate"],
        cwd=work,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert committed.returncode == 0, committed.stderr
    commit = git("rev-parse", "HEAD", cwd=work)
    git("init", "--quiet", "--bare", str(remote))
    git("remote", "add", "origin", str(remote), cwd=work)
    git("push", "--quiet", "origin", "HEAD:refs/heads/main", cwd=work)
    return remote, commit


def initial_artifact(
    remote: Path, commit: str, environment: dict[str, str]
) -> dict[str, object]:
    result = run(
        GIT_ARTIFACT,
        {
            "commit": commit,
            "entrypoint": "adapter.py",
            "outputs": [],
            "repository": str(remote),
        },
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def fake_pi(tmp_path: Path, *, disallowed_change: bool = False) -> tuple[Path, Path]:
    trace = tmp_path / "pi-prompt.txt"
    script = tmp_path / ("fake-pi-bad" if disallowed_change else "fake-pi")
    extra = (
        "Path('forbidden.py').write_text('forbidden\\n',encoding='utf-8')\n"
        if disallowed_change
        else ""
    )
    script.write_text(
        f"#!{sys.executable}\n"
        "import os,sys\n"
        "from pathlib import Path\n"
        "args=sys.argv[1:]\n"
        "Path(os.environ['PI_TRACE']).write_text(args[args.index('-p')+1],encoding='utf-8')\n"
        "Path('adapter.py').write_text('ANSWER = \"ADAPTED\"\\n',encoding='utf-8')\n"
        f"{extra}"
        "print('workspace revised')\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, trace


def git_environment(
    tmp_path: Path,
    remote: Path,
    pi: Path,
    trace: Path,
) -> dict[str, str]:
    return {
        **os.environ,
        "METERING_DEMO_ARTIFACT_STORE": str(tmp_path / "model-store"),
        "METERING_GIT_ALLOWED_PATHS_JSON": encode(["adapter.py"]),
        "METERING_GIT_BUILD_COMMAND": encode([sys.executable, str(DEMO_BUILDER)]),
        "METERING_GIT_BUILD_TIMEOUT": "30",
        "METERING_GIT_EXECUTOR_COMMAND": encode(
            [sys.executable, str(DEMO_EXECUTOR)]
        ),
        "METERING_GIT_EXECUTOR_TIMEOUT": "30",
        "METERING_GIT_REF_PREFIX": "refs/heads/evolution/test-run",
        "METERING_GIT_REPOSITORY": str(remote),
        "METERING_GIT_VALIDATE_COMMAND": encode(
            [sys.executable, str(DEMO_VALIDATE)]
        ),
        "METERING_GIT_VALIDATE_TIMEOUT": "30",
        "METERING_PI_COMMAND": encode([str(pi)]),
        "PI_BIN": str(pi),
        "PI_TRACE": str(trace),
    }


def evolution_request(
    parent: dict[str, object], proposer: Path = PI_GIT_PROPOSER
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "initial_parent_artifact": parent,
        "proposal": {
            "command": [sys.executable, str(proposer)],
            "context": {
                "objective": "Adapt the environment adapter and produce a model artifact."
            },
            "timeout_seconds": 60,
        },
        "generation": {
            "evaluation": "git-artifact/demo-v1",
            "evaluator": {
                "command": [sys.executable, str(DEMO_EVALUATOR)],
                "timeout_seconds": 30,
            },
            "runner": {
                "command": [sys.executable, str(GIT_ADAPTER)],
                "timeout_seconds": 30,
            },
            "selection_policy": {
                "type": "task-pass-count-v1",
                "minimum_pass_improvement": 1,
                "reject_safety_regression": True,
            },
            "tasks": [
                {
                    "case_id": "git-artifact-case",
                    "input": {"environment": "demo-v1"},
                }
            ],
        },
        "limits": {
            "max_consecutive_rejections": 1,
            "max_generations": 1,
            "max_wall_seconds": 120,
        },
    }


def test_git_artifact_normalizes_external_outputs_and_rejects_duplicates(tmp_path):
    remote, parent_commit = seed_repository(tmp_path)
    pi, trace = fake_pi(tmp_path)
    environment = git_environment(tmp_path, remote, pi, trace)
    outputs = [
        {
            "kind": "model_checkpoint",
            "name": "z-model",
            "sha256": "b" * 64,
            "uri": "artifact://models/z",
        },
        {
            "kind": "environment_bundle",
            "name": "a-adapter",
            "sha256": "a" * 64,
            "uri": "artifact://adapters/a",
        },
    ]
    result = run(
        GIT_ARTIFACT,
        {
            "commit": parent_commit,
            "entrypoint": "adapter.py",
            "outputs": outputs,
            "repository": str(remote),
        },
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    artifact = json.loads(result.stdout)
    assert [item["kind"] for item in artifact["outputs"]] == [
        "environment_bundle",
        "model_checkpoint",
    ]
    duplicate = run(
        GIT_ARTIFACT,
        {
            "commit": parent_commit,
            "entrypoint": "adapter.py",
            "outputs": [outputs[0], {**outputs[0], "sha256": "c" * 64}],
            "repository": str(remote),
        },
        env=environment,
    )
    assert duplicate.returncode == 2
    assert "duplicate kind and name" in duplicate.stderr


@pytest.mark.parametrize(
    ("proposer", "command_environment"),
    [
        (PI_GIT_PROPOSER, "METERING_PI_COMMAND"),
        (PRIME_GIT_PROPOSER, "METERING_PRIME_AGENT_COMMAND"),
    ],
)
def test_git_artifact_runs_through_the_complete_frozen_evolution_loop(
    tmp_path: Path,
    proposer: Path,
    command_environment: str,
):
    remote, parent_commit = seed_repository(tmp_path)
    agent, trace = fake_pi(tmp_path)
    environment = git_environment(tmp_path, remote, agent, trace)
    environment[command_environment] = encode([str(agent)])
    parent = initial_artifact(remote, parent_commit, environment)
    state = tmp_path / "evolution.jsonl"
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in CORE_FILES}

    result = run(
        EVOLVER,
        evolution_request(parent, proposer),
        "--state",
        str(state),
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    records = [json.loads(line) for line in state.read_text().splitlines()]
    generation = records[1]["controller_result"]
    assert summary["status"] == "generation_limit"
    assert generation["selection"]["decision"] == "promote_challenger"
    assert generation["selection"]["comparison"]["pass_improvement"] == 1
    child = generation["mutation"]["child"]["artifact"]
    assert summary["head"]["artifact"] == child
    assert child["artifact_schema"] == "git-candidate-v1"
    assert child["commit"] != parent_commit
    assert child["outputs"][0]["kind"] == "model_checkpoint"
    assert child["outputs"][0]["name"] == "demo-trained-model"
    checkpoint = Path(child["outputs"][0]["uri"].removeprefix("file://"))
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == child["outputs"][0][
        "sha256"
    ]
    assert generation["mutation"]["mutation"]["changed_paths"] == [
        "@git-candidate"
    ]
    assert git("rev-parse", f"{child['commit']}^", cwd=remote) == parent_commit
    refs = git("for-each-ref", "--format=%(refname)", cwd=remote).splitlines()
    assert any(ref.startswith("refs/heads/evolution/test-run/") for ref in refs)
    prompt = trace.read_text()
    assert "git-artifact-case" not in prompt
    assert "demo_evaluator.py" not in prompt
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in CORE_FILES}
    assert after == before

    state_before = state.read_bytes()
    resumed = run(
        EVOLVER,
        evolution_request(parent, proposer),
        "--state",
        str(state),
        env=environment,
    )
    assert resumed.returncode == 0
    assert resumed.stdout == result.stdout
    assert state.read_bytes() == state_before


def test_documented_git_artifact_demo_runs_with_fake_pi(tmp_path):
    pi, trace = fake_pi(tmp_path)
    demo_root = tmp_path / "documented-demo"
    result = subprocess.run(
        [sys.executable, str(DEMO), "--root", str(demo_root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "METERING_PI_COMMAND": encode([str(pi)]),
            "PI_BIN": str(pi),
            "PI_MODEL": "fake-model",
            "PI_PROVIDER": "fake-provider",
            "PI_REASONING_LEVEL": "fake-reasoning",
            "PI_TRACE": str(trace),
        },
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema"] == "git-artifact-live-demo-v1"
    assert report["selection"]["decision"] == "promote_challenger"
    assert Path(report["state"]).is_file()
    assert list(Path(report["model_store"]).glob("*.bin"))


def test_git_proposer_rejects_changes_outside_the_allowed_candidate_paths(tmp_path):
    remote, parent_commit = seed_repository(tmp_path)
    pi, trace = fake_pi(tmp_path, disallowed_change=True)
    environment = git_environment(tmp_path, remote, pi, trace)
    parent = initial_artifact(remote, parent_commit, environment)
    state = tmp_path / "failed.jsonl"

    result = run(
        EVOLVER,
        evolution_request(parent),
        "--state",
        str(state),
        env=environment,
    )

    assert result.returncode == 2
    assert "disallowed path" in json.loads(result.stderr)["error"]["message"]
    records = state.read_text().splitlines()
    assert len(records) == 1
    assert json.loads(records[0])["kind"] == "run"


def test_git_executor_rejects_a_tampered_external_model_output(tmp_path):
    remote, parent_commit = seed_repository(tmp_path)
    pi, trace = fake_pi(tmp_path)
    environment = git_environment(tmp_path, remote, pi, trace)
    checkpoint = tmp_path / "checkpoint.bin"
    checkpoint.write_bytes(b"original checkpoint")
    checkpoint_digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    artifact_result = run(
        GIT_ARTIFACT,
        {
            "commit": parent_commit,
            "entrypoint": "adapter.py",
            "outputs": [
                {
                    "kind": "model_checkpoint",
                    "name": "demo-trained-model",
                    "sha256": checkpoint_digest,
                    "uri": checkpoint.resolve().as_uri(),
                }
            ],
            "repository": str(remote),
        },
        env=environment,
    )
    assert artifact_result.returncode == 0, artifact_result.stderr
    artifact = json.loads(artifact_result.stdout)
    candidate_id = hashlib.sha256(
        encode(
            {"artifact": artifact, "candidate_schema": "agent-candidate-v1"}
        ).encode("ascii")
    ).hexdigest()
    checkpoint.write_bytes(b"tampered checkpoint")

    result = run(
        CANDIDATE_RUNNER,
        {
            "adapter_command": [sys.executable, str(GIT_ADAPTER)],
            "candidate": {"artifact": artifact, "candidate_id": candidate_id},
            "schema_version": 2,
            "task": {
                "case_id": "tampered-output",
                "input": {"environment": "demo-v1"},
            },
            "timeout_seconds": 30,
        },
        env=environment,
    )

    assert result.returncode == 2
    assert "external output digest does not match" in json.loads(result.stderr)[
        "error"
    ]["message"]


def test_git_candidate_rejects_a_mismatched_content_digest(tmp_path):
    remote, parent_commit = seed_repository(tmp_path)
    pi, trace = fake_pi(tmp_path)
    environment = git_environment(tmp_path, remote, pi, trace)
    parent = initial_artifact(remote, parent_commit, environment)
    parent["content_sha256"] = "0" * 64
    state = tmp_path / "tampered.jsonl"

    result = run(
        EVOLVER,
        evolution_request(parent),
        "--state",
        str(state),
        env=environment,
    )

    assert result.returncode == 2
    assert "content SHA-256 does not match" in json.loads(result.stderr)["error"][
        "message"
    ]
    assert len(state.read_text().splitlines()) == 1
