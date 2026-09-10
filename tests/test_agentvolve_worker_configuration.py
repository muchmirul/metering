"""Configured orchestration only: no inference, Docker, workers, or global edits."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_digest, canonical_json  # noqa: E402
from apps.coding_agent import agentvolve_worker as worker  # noqa: E402
from apps.coding_agent import harness_workspace_editor, pi_execution  # noqa: E402
from apps.harness import experiment_replay  # noqa: E402
from apps.harness.runtime_manifest import load_runtime_manifest  # noqa: E402
from connectors.fixed.pi import runtime  # noqa: E402

SECRET = "private-auth-token-never-in-projections"


def document(path, value):
    path.write_text(canonical_json(value) + "\n", encoding="ascii")


@pytest.fixture
def configured(tmp_path, monkeypatch):
    config = tmp_path / "provisioned"
    config.mkdir()
    (config / "models.json").write_bytes(b'{ "providers": {"worker": {"baseUrl": "https://reviewed.invalid"}} }\n')
    (config / "auth.json").write_text(json.dumps({"worker": {"key": SECRET}}))
    (config / "settings.json").write_text('{"extensions":["must-not-copy"]}')
    (config / "sessions").mkdir()
    manifest = tmp_path / "runtime.json"
    data = json.loads((ROOT / "apps/harness/profiles/runtime-fixture.json").read_text())
    data["kernel"].update(kind="oci-v1", engine="docker-v1", image="reviewed@sha256:" + "b" * 64,
                          required_observations=["cpu", "memory", "processes", "storage", "wall"])
    data["assay"]["cost_mode"] = "observed-v1"
    data["model"].update(connector="pi-v1", implementation_version="0.84.4", provider="worker", model="pinned")
    document(manifest, data)
    harness = tmp_path / "selected-harness.json"
    descriptor = {"runtime_id": load_runtime_manifest(manifest).runtime_id, "candidate_id": "c" * 64,
                  "provenance": {"final_passed_count": 3, "final_task_count": 3, "final_safety_failures": 0}}
    document(harness, descriptor)
    task = tmp_path / "task.json"
    document(task, {})
    binary = tmp_path / "pi"
    binary.write_text("not executed")
    binary.chmod(0o700)
    monkeypatch.setenv("METERING_PI_COMMAND", json.dumps([str(binary)]))
    monkeypatch.delenv("PI_BIN", raising=False)
    monkeypatch.setenv("METERING_PI_CONFIG_DIR", str(tmp_path / "wrong-ambient-config"))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "interactive"))
    monkeypatch.setattr(harness_workspace_editor, "load_harness_descriptor", lambda _: descriptor)
    monkeypatch.setattr(experiment_replay, "verify_experiment", lambda _: {"assay": "coding-agent-v1"})
    monkeypatch.setattr(worker, "_preflight_workflow", lambda *_: None)
    probes, launches = [], []

    def probe(command, option, *, environment=None):
        probes.append((command, option, environment))
        return "0.84.4" if option == "--version" else " ".join(runtime.REQUIRED_FLAGS)

    monkeypatch.setattr(pi_execution, "probe_command", probe)
    monkeypatch.setattr(worker.subprocess, "Popen", lambda argv, **kw: launches.append((argv, kw)) or SimpleNamespace(pid=43210))
    approved = runtime.review_configured(manifest, harness, config)
    review_file = tmp_path / "approved.json"
    # JSON.stringify need not sort keys, add newline, or use canonical whitespace.
    review_file.write_text(json.dumps(dict(reversed(list(approved.items())))))
    args = ["start-configured", str(tmp_path / "runs"), str(task), str(manifest), str(harness), str(config), str(review_file)]
    return SimpleNamespace(config=config, manifest=manifest, data=data, harness=harness, task=task,
                           binary=binary, approved=approved, review_file=review_file, args=args,
                           runs=tmp_path / "runs", probes=probes, launches=launches, descriptor=descriptor)


def start(configured):
    c = configured
    return runtime.start_configured(c.runs, c.task, c.manifest, c.harness, c.config, c.review_file)


def request_after_start(configured):
    response = start(configured)
    root = Path(response["workflow_root"])
    return root, worker.load_workflow_request(root)


def test_configured_review_binds_permission_capable_private_run_registry_before_dispatch(configured):
    c = configured
    c.runs.mkdir(mode=0o755)
    c.runs.chmod(0o755)
    with pytest.raises(pi_execution.PiConfigurationError, match="owner-controlled 0700"):
        runtime.review_configured(c.manifest, c.harness, c.config, c.runs)
    assert list(c.runs.iterdir()) == [] and not c.launches

    c.runs.chmod(0o700)
    approved = runtime.review_configured(c.manifest, c.harness, c.config, c.runs)
    assert approved["runs_directory"] == str(c.runs)
    document(c.review_file, approved)
    c.runs.chmod(0o755)  # Filesystem/mount changed after review.
    with pytest.raises(pi_execution.PiConfigurationError, match="owner-controlled 0700"):
        runtime.start_configured(c.runs, c.task, c.manifest, c.harness, c.config, c.review_file)
    assert not list(c.runs.glob("workflow-*")) and not c.launches


def test_configured_cli_review_and_start_are_child_only_private_and_review_bound(configured, capsys):
    c = configured
    before = dict(os.environ)
    assert runtime.main(["review-configured", str(c.manifest), str(c.harness), str(c.config)]) == 0
    assert json.loads(capsys.readouterr().out) == c.approved
    assert not c.runs.exists()
    assert runtime.main(c.args) == 0
    response = json.loads(capsys.readouterr().out)
    root = Path(response["workflow_root"])
    request = worker.load_workflow_request(root)
    binding = request["pi_execution"]
    assert request["workflow_schema"] == "agentvolve-worker-request-v2"
    assert request["workflow_id"] == canonical_digest({k: v for k, v in request.items() if k != "workflow_id"})
    assert binding == {
        "execution_schema": "agentvolve-pi-execution-v1", "command": [str(c.binary)],
        "runtime_id": c.approved["runtime_id"], "implementation_version": "0.84.4",
        "configuration_directory": str(root / "pi-configuration"), "configuration_source": str(c.config),
        "models_sha256": c.approved["worker_models_sha256"],
    }
    snapshot = root / "pi-configuration"
    assert {p.name for p in snapshot.iterdir()} == {"auth.json", "models.json"}
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o700
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for name in ("auth.json", "models.json"):
        assert (snapshot / name).read_bytes() == (c.config / name).read_bytes()
        assert stat.S_IMODE((snapshot / name).stat().st_mode) == 0o600
        assert not (snapshot / name).samefile(c.config / name)
    environment = c.launches[0][1]["env"]
    assert environment["PI_CODING_AGENT_DIR"] == environment["METERING_PI_CONFIG_DIR"] == str(snapshot)
    assert json.loads(environment["METERING_PI_COMMAND"]) == [str(c.binary)]
    assert all(p[2]["PI_CODING_AGENT_DIR"] in {str(c.config), str(snapshot)} for p in c.probes)
    assert dict(os.environ) == before
    for path in root.rglob("*"):
        if path.is_file() and path.name != "auth.json":
            assert SECRET.encode() not in path.read_bytes()
    assert SECRET not in canonical_json(response) + canonical_json(c.approved)
    assert "auth_sha256" not in canonical_json(request)


@pytest.mark.parametrize("change", ["extra", "nested-extra", "duplicate", "nested-duplicate", "nonfinite", "scalar", "oversize", "boolean"])
def test_strict_approved_review_refuses_before_workflow_or_dispatch(configured, change):
    c = configured
    approved = dict(c.approved)
    if change == "extra":
        approved["unexpected"] = SECRET
    elif change == "nested-extra":
        approved["kernel"] = {**approved["kernel"], "extra": True}
    elif change == "boolean":
        approved["inference_performed"] = 0  # Python equality must not treat this as False.
    text = json.dumps(approved)
    if change == "duplicate":
        text = '{"review_schema":"duplicate",' + text[1:]
    elif change == "nested-duplicate":
        text = text.replace('"connector": "pi-v1"', '"connector":"pi-v1","connector":"pi-v1"')
    elif change == "nonfinite":
        text = text.replace("false", "NaN")
    elif change == "scalar":
        text = "[]"
    elif change == "oversize":
        text = " " * (pi_execution.MAX_REVIEW_BYTES + 1)
    c.review_file.write_text(text)
    with pytest.raises((runtime.PiRuntimeError, worker.AgentvolveWorkerError)) as error:
        start(c)
    assert SECRET not in str(error.value)
    assert c.launches == []
    assert not c.runs.exists()


@pytest.mark.parametrize("changed", ["models", "runtime", "harness", "command", "config"])
def test_changed_review_requires_new_approval(configured, monkeypatch, changed):
    c = configured
    if changed == "models":
        (c.config / "models.json").write_text('{}')
    elif changed == "runtime":
        c.data["model"]["model"] = "replacement"
        document(c.manifest, c.data)
    elif changed == "harness":
        c.harness.write_text("changed descriptor bytes")
    elif changed == "command":
        monkeypatch.setenv("METERING_PI_COMMAND", json.dumps([str(c.binary), "--different"]))
    else:
        c.config = c.config.parent / "another-config"
        c.config.mkdir()
    with pytest.raises(ValueError if changed in {"runtime", "config"} else runtime.PiRuntimeError):
        start(c)
    assert c.launches == []
    assert not c.runs.exists()


def test_copy_race_refuses_hash_mismatch_and_retains_copied_evidence(configured, monkeypatch):
    c = configured
    def race(*_):
        (c.config / "models.json").write_bytes(b"changed-after-review")
    monkeypatch.setattr(worker, "_preflight_workflow", race)
    with pytest.raises(pi_execution.PiConfigurationError, match="Copied.*SHA256.*retained"):
        start(c)
    root = next(c.runs.glob("workflow-*"))
    assert (root / "pi-configuration/models.json").read_bytes() == b"changed-after-review"
    assert worker.load_workflow_request(root)["pi_execution"]["models_sha256"] == c.approved["worker_models_sha256"]
    assert worker.close_workflow(root, "copy failed; preserve evidence")["state"] == "closed-incomplete"
    assert c.launches == []


def test_spawn_failure_retains_immutable_request_snapshot_and_jobs(configured, monkeypatch):
    def failed(*_, **__):
        raise OSError("detachment failed")
    monkeypatch.setattr(worker.subprocess, "Popen", failed)
    with pytest.raises(OSError, match="detachment failed"):
        start(configured)
    root = next(configured.runs.glob("workflow-*"))
    worker.load_workflow_request(root)
    assert (root / "pi-configuration/auth.json").is_file()
    assert len(list((root / "jobs").glob("*.json"))) == 1
    assert not worker._lock_is_held(root)


@pytest.mark.parametrize("operation", ["resume", "retry"])
def test_runtime_and_direct_worker_recovery_ignore_hostile_environment_and_missing_source(configured, monkeypatch, operation):
    c = configured
    root, request = request_after_start(c)
    snapshot = Path(request["pi_execution"]["configuration_directory"])
    # Mutable auth refresh is permitted and does not change request identity.
    document(snapshot / "auth.json", {"token": "refreshed-private-token"})
    (c.config / "models.json").unlink()
    (c.config / "auth.json").unlink()
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(snapshot))
    monkeypatch.setenv("METERING_PI_CONFIG_DIR", "/hostile/current/config")
    monkeypatch.setenv("METERING_PI_COMMAND", '["/hostile/pi"]')
    monkeypatch.setenv("PI_BIN", "/hostile/pi-bin")
    monkeypatch.setenv("METERING_PI_RUNTIME_DIR", "/hostile/cache")
    monkeypatch.setenv("PATH", "/hostile/bin")
    monkeypatch.setattr(runtime, "check", lambda *_args, **_kw: pytest.fail("must not resolve ambient command"))
    if operation == "retry":
        pending = Path(request["solution_run_root"]) / "state/pending"
        pending.mkdir(parents=True)
        document(pending / "round-intent.json", {"stage": "controller_pending", "controller_receipt": None})
    before = dict(os.environ)
    execs = []
    monkeypatch.setattr(runtime.os, "execve", lambda *args: execs.append(args))
    arguments = [operation, str(root)] + (["operator approved"] if operation == "retry" else [])
    assert runtime.main(arguments) == 0
    assert json.loads(execs[0][2]["METERING_PI_COMMAND"]) == [str(c.binary)]
    assert execs[0][2]["PI_CODING_AGENT_DIR"] == str(snapshot)
    worker.launch_existing(root, operation, "operator approved" if operation == "retry" else None)
    assert c.launches[-1][1]["env"]["PI_CODING_AGENT_DIR"] == str(snapshot)
    assert json.loads(c.launches[-1][1]["env"]["METERING_PI_COMMAND"]) == [str(c.binary)]
    assert worker.load_workflow_request(root) == request
    assert dict(os.environ) == before


@pytest.mark.parametrize("mutation", ["models", "runtime", "stored-runtime", "missing-models", "auth-mode", "snapshot-mode", "snapshot-symlink", "command-symlink", "command-version", "command-flags"])
def test_mutated_job_binding_blocks_direct_recovery_without_fallback(configured, monkeypatch, mutation):
    c = configured
    root, request = request_after_start(c)
    snapshot = root / "pi-configuration"
    if mutation == "models":
        (snapshot / "models.json").write_text("mutated")
    elif mutation == "missing-models":
        (snapshot / "models.json").unlink()
    elif mutation in {"runtime", "stored-runtime"}:
        c.data["model"]["model"] = "changed"
        target = c.manifest if mutation == "runtime" else Path(request["solution_run_root"]) / "runtime.json"
        target.parent.mkdir(exist_ok=True)
        document(target, c.data)
    elif mutation == "auth-mode":
        (snapshot / "auth.json").chmod(0o644)
    elif mutation == "snapshot-mode":
        snapshot.chmod(0o755)
    elif mutation == "snapshot-symlink":
        snapshot.rename(root / "moved")
        snapshot.symlink_to(root / "moved", target_is_directory=True)
    elif mutation == "command-symlink":
        c.binary.rename(c.binary.with_name("replacement"))
        c.binary.symlink_to(c.binary.with_name("replacement"))
    elif mutation == "command-flags":
        monkeypatch.setattr(pi_execution, "probe_command", lambda _command, option, **_kw: "0.84.4" if option == "--version" else "")
    else:
        monkeypatch.setattr(pi_execution, "probe_command", lambda *_args, **_kw: "9.9.9")
    c.launches.clear()
    with pytest.raises(worker.AgentvolveWorkerError):
        worker.launch_existing(root, "resume")
    assert c.launches == []
    assert (root / "workflow.json").is_file()
    # Corrupt execution data does not prevent inspection/explicit closure.
    assert worker.close_workflow(root, "configuration changed")["state"] == "closed-incomplete"


@pytest.mark.parametrize("invalid", ["interactive", "interactive-alias", "directory-link", "ancestor-link", "models-link", "auth-link", "models-large", "auth-large", "fifo", "hardlink"])
def test_configuration_source_rejects_aliases_unsafe_files_and_oversize(configured, monkeypatch, invalid):
    c = configured
    if invalid == "interactive":
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(c.config))
    elif invalid == "interactive-alias":
        alias = c.config.parent / "interactive-link"
        alias.symlink_to(c.config, target_is_directory=True)
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(alias))
    elif invalid == "directory-link":
        alias = c.config.parent / "config-link"
        alias.symlink_to(c.config, target_is_directory=True)
        c.config = alias
    elif invalid == "ancestor-link":
        alias = c.config.parent / "ancestor-link"
        alias.symlink_to(c.config.parent, target_is_directory=True)
        c.config = alias / c.config.name
    else:
        name = "auth.json" if invalid.startswith("auth") else "models.json"
        target = c.config / name
        target.unlink()
        if invalid.endswith("link"):
            other = c.config / "other"
            other.write_text("private-data")
            if invalid == "hardlink":
                os.link(other, target)
            else:
                target.symlink_to(other)
        elif invalid.endswith("large"):
            target.write_bytes(b"x" * (pi_execution.MAX_CONFIGURATION_BYTES + 1))
        else:
            os.mkfifo(target)
    with pytest.raises(pi_execution.PiConfigurationError):
        runtime.review_configured(c.manifest, c.harness, c.config)
    assert not c.runs.exists()
    assert c.launches == []


def test_auth_is_optional_and_refresh_before_snapshot_is_not_identity(configured):
    c = configured
    (c.config / "auth.json").unlink()
    assert runtime.review_configured(c.manifest, c.harness, c.config) == c.approved
    root, request = request_after_start(c)
    assert not (root / "pi-configuration/auth.json").exists()
    document(root / "pi-configuration/auth.json", {"refreshed": SECRET})
    (root / "pi-configuration/auth.json").chmod(0o600)
    pi_execution.child_environment(root, request)
    assert worker.load_workflow_request(root) == request


def test_v2_binding_is_workflow_identity_not_projection(configured):
    root, request = request_after_start(configured)
    request["pi_execution"]["models_sha256"] = "d" * 64
    document(root / "workflow.json", request)
    with pytest.raises(worker.AgentvolveWorkerError, match="identity does not replay"):
        worker.load_workflow_request(root)
    request["workflow_id"] = canonical_digest({k: v for k, v in request.items() if k != "workflow_id"})
    request["pi_execution"]["unexpected"] = True
    request["workflow_id"] = canonical_digest({k: v for k, v in request.items() if k != "workflow_id"})
    document(root / "workflow.json", request)
    with pytest.raises(worker.AgentvolveWorkerError, match="unexpected schema"):
        worker.load_workflow_request(root)


def test_offline_verification_does_not_require_private_configuration_or_model_client(configured, monkeypatch):
    c = configured
    root, request = request_after_start(c)
    # Credential/configuration availability is not evidence-replay authority.
    (root / "pi-configuration").rename(root / "unavailable-private-configuration")
    c.binary.unlink()
    monkeypatch.setattr(pi_execution, "child_environment", lambda *_a, **_kw: pytest.fail("offline verification must not resolve worker configuration"))
    monkeypatch.setattr(worker, "_completed_run", lambda _root, kind: kind == "solution")
    worker.launch_existing(root, "verify")
    job = sorted((root / "jobs").glob("*.json"))[-1]
    calls = []
    def verified(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(pid=123, returncode=0, poll=lambda: 0)
    monkeypatch.setattr(worker.subprocess, "Popen", verified)
    worker._execute_job(root, job)
    assert calls == [worker._run_command("solution", "verify", Path(request["solution_run_root"]))]
    assert worker.load_worker_status(root)["state"] == "verified"
    assert worker.load_workflow_request(root) == request


def test_legacy_start_remains_v1_with_ambient_environment_and_no_snapshot(configured):
    c = configured
    before = dict(os.environ)
    response = worker.start_workflow(c.runs, c.task, c.manifest)
    root = Path(response["workflow_root"])
    request = worker.load_workflow_request(root)
    assert request["workflow_schema"] == "agentvolve-worker-request-v1"
    assert "pi_execution" not in request
    assert request["harness_descriptor"] is None
    assert not (root / "pi-configuration").exists()
    assert c.launches[0][1]["env"] == before
    assert pi_execution.child_environment(root, request) == before


def test_configured_worker_requires_harness_and_reviewed_oci(configured):
    c = configured
    with pytest.raises(worker.AgentvolveWorkerError, match="explicit sealed harness"):
        worker.start_workflow(c.runs, c.task, c.manifest, execution=c.approved)
    fixture = ROOT / "apps/harness/profiles/runtime-fixture.json"
    with pytest.raises(runtime.PiRuntimeError, match="reviewed OCI"):
        runtime.review_configured(fixture, c.harness, c.config)
    c.descriptor["provenance"]["final_passed_count"] = 0
    with pytest.raises(runtime.PiRuntimeError, match="verified protected"):
        start(c)
    assert c.launches == []


def test_effect_subprocess_revalidates_and_does_not_project_private_diagnostics(configured, monkeypatch):
    c = configured
    root, request = request_after_start(c)
    job = worker._load_job(next((root / "jobs").glob("*.json")))
    monkeypatch.setenv("METERING_PI_CONFIG_DIR", "/wrong/current/config")
    calls = []
    def failed_effect(command, **kw):
        calls.append((command, kw))
        os.write(kw["stderr"], SECRET.encode())
        return SimpleNamespace(pid=123, returncode=2, poll=lambda: 2)
    monkeypatch.setattr(worker.subprocess, "Popen", failed_effect)
    runner = worker._EffectRunner(root, request, job)
    with pytest.raises(worker.AgentvolveWorkerError, match="status 2") as error:
        runner.run(["not-executed"], run_root=Path(request["solution_run_root"]), kind="solution", fallback_stage=4)
    assert SECRET not in str(error.value)
    assert calls[0][1]["env"]["PI_CODING_AGENT_DIR"] == str(root / "pi-configuration")
    with pytest.raises(worker.AgentvolveWorkerError, match="status 2"):
        worker._execute_job(root, next((root / "jobs").glob("*.json")))
    assert SECRET not in (root / "worker-status.json").read_text()
    assert worker.load_worker_status(root)["state"] == "failed"
    (root / "pi-configuration/models.json").write_text("mutated")
    calls.clear()
    with pytest.raises(worker.AgentvolveWorkerError, match="models.json changed"):
        runner.run(["not-executed"], run_root=Path(request["solution_run_root"]), kind="solution", fallback_stage=4)
    assert calls == []
