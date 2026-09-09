"""Version-independent operator UI, exact-version experiment transport."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from connectors.fixed.pi import runtime  # noqa: E402

PINNED = Path("/mnt/Tforce/dev/metering-agentvolve-e2e/pi-0.84.4/node_modules/.bin/pi")


def executable(path: Path, version: str, *, flags=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = runtime.REQUIRED_FLAGS if flags is None else flags
    path.write_text(
        f'#!{sys.executable}\nimport sys\nprint({version!r} if sys.argv[1] == "--version" else {" ".join(sorted(flags))!r})\n'
    )
    path.chmod(0o755)
    return path


@pytest.fixture
def clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("METERING_PI_COMMAND", raising=False)
    monkeypatch.delenv("PI_BIN", raising=False)
    monkeypatch.setenv("METERING_PI_RUNTIME_DIR", str(tmp_path / "cache"))
    return tmp_path


def test_new_operator_resolves_old_runtime_without_changing_pin(
    clean: Path, monkeypatch: pytest.MonkeyPatch
):
    executable(clean / "bin/pi", "9.2.0")
    old = executable(clean / "cache/0.84.4/node_modules/.bin/pi", "0.84.4")
    monkeypatch.setenv("PATH", str(clean / "bin"))
    result = runtime.resolve("0.84.4")
    assert result["command"] == [str(old)]
    assert result["implementation_version"] == "0.84.4"
    assert result["source"] == "version-cache"
    assert result["inference_performed"] is False
    assert "METERING_PI_COMMAND" not in os.environ


def test_new_release_has_no_hardcoded_upper_version_bound(
    clean: Path, monkeypatch: pytest.MonkeyPatch
):
    binary = executable(clean / "bin/pi", "9.2.0")
    monkeypatch.setenv("PATH", str(clean / "bin"))
    assert runtime.resolve("9.2.0")["command"] == [str(binary)]


def test_missing_cache_and_explicit_mismatch_fail_without_installation(
    clean: Path, monkeypatch: pytest.MonkeyPatch
):
    binary = executable(clean / "bin/pi", "9.2.0")
    monkeypatch.setenv("PATH", str(clean / "bin"))
    with pytest.raises(runtime.PiRuntimeError, match="Install a separate copy"):
        runtime.resolve("0.84.4")
    assert not (clean / "cache").exists()
    executable(clean / "cache/0.84.4/node_modules/.bin/pi", "0.84.4")
    monkeypatch.setenv("PI_BIN", str(binary))
    with pytest.raises(runtime.PiRuntimeError, match="Explicit Pi reports 9.2.0"):
        runtime.resolve("0.84.4")


def test_false_cache_version_missing_isolation_flags_and_ranges_rejected(
    clean: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("PATH", str(clean / "missing"))
    executable(clean / "cache/0.84.4/node_modules/.bin/pi", "0.85.1")
    with pytest.raises(runtime.PiRuntimeError, match="Cached Pi reports"):
        runtime.resolve("0.84.4")
    binary = executable(clean / "bin/pi", "0.85.1", flags={"--mode"})
    monkeypatch.setenv("PI_BIN", str(binary))
    with pytest.raises(runtime.PiRuntimeError, match="missing required isolation"):
        runtime.resolve("0.85.1")
    for version in ("latest", "*", "../0.84.4", ">=0.84.4"):
        with pytest.raises(runtime.PiRuntimeError, match="exact release"):
            runtime.resolve(version)


def test_wrapper_passes_exact_transport_only_to_unchanged_worker(
    clean: Path, monkeypatch: pytest.MonkeyPatch
):
    selected = ["/absolute/versioned/pi"]
    monkeypatch.setattr(runtime, "check", lambda _path: {"command": selected})
    calls = []
    monkeypatch.setattr(
        runtime.os,
        "execve",
        lambda executable, args, env: calls.append((executable, args, env)),
    )
    arguments = [
        "start",
        "/new/runs",
        "/approved/task.json",
        "/approved/runtime.json",
        "/sealed/harness.json",
    ]
    assert runtime.main(arguments) == 0
    assert calls[0][1] == [
        sys.executable,
        "-m",
        "apps.coding_agent.agentvolve_worker",
        *arguments,
    ]
    assert json.loads(calls[0][2]["METERING_PI_COMMAND"]) == selected
    assert "METERING_PI_COMMAND" not in os.environ
    calls.clear()
    monkeypatch.setattr(
        runtime,
        "check",
        lambda _path: (_ for _ in ()).throw(runtime.PiRuntimeError("incompatible")),
    )
    assert runtime.main(arguments) == 2
    assert calls == []
    assert runtime.main(["retry", "/old/run", ""]) == 2


def test_execution_review_requires_compatible_verified_harness_and_separate_config(clean, monkeypatch):
    from types import SimpleNamespace
    from apps.coding_agent import harness_workspace_editor
    from apps.harness import experiment_replay

    manifest = SimpleNamespace(model={"connector": "pi-v1", "provider": "pinned-provider", "model": "pinned-model", "reasoning": "medium", "implementation_version": "0.84.4"},
        runtime_id="a" * 64, isolation_enforced=True, document={"kernel": {"image": "reviewed@sha256:" + "b" * 64}},
        max_model_calls=4, model_timeout_seconds=60)
    descriptor = {"runtime_id": "a" * 64, "candidate_id": "c" * 64,
        "provenance": {"final_passed_count": 3, "final_task_count": 3, "final_safety_failures": 0}}
    harness = clean / "selected-harness.json"
    harness.write_text("verified fixture descriptor")
    config = clean / "worker-config"
    config.mkdir()
    (config / "models.json").write_text('{"providers":{"pinned-provider":{"baseUrl":"https://reviewed.invalid"}}}')
    monkeypatch.setenv("METERING_PI_CONFIG_DIR", str(config))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(clean / "interactive"))
    monkeypatch.setattr(runtime, "load_runtime_manifest", lambda _: manifest)
    monkeypatch.setattr(harness_workspace_editor, "load_harness_descriptor", lambda _: descriptor)
    verified = []
    monkeypatch.setattr(experiment_replay, "verify_experiment", lambda root: verified.append(root) or {"assay": "coding-agent-v1"})
    monkeypatch.setattr(runtime, "check", lambda _: {"command": ["/pinned/pi"], "authority": "diagnostic-only", "runtime_id": manifest.runtime_id})
    reviewed = runtime.review(clean / "runtime.json", harness)
    assert verified == [clean]
    assert reviewed["model"] == manifest.model
    assert reviewed["worker_configuration"] == str(config)
    assert reviewed["max_model_calls_per_execution"] == 4
    assert reviewed["level_2_setup"] == "none; reused verified seal"
    (config / "models.json").write_text('{"providers":{}}')
    assert runtime.review(clean / "runtime.json", harness)["worker_models_sha256"] != reviewed["worker_models_sha256"]
    descriptor["runtime_id"] = "d" * 64
    with pytest.raises(runtime.PiRuntimeError, match="differs from required.*separately approve/budget"):
        runtime.review(clean / "runtime.json", harness)
    descriptor["runtime_id"] = manifest.runtime_id
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(config))
    with pytest.raises(runtime.PiRuntimeError, match="separate reviewed worker"):
        runtime.review(clean / "runtime.json", harness)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(clean / "interactive"))
    monkeypatch.setattr(experiment_replay, "verify_experiment", lambda _: (_ for _ in ()).throw(ValueError("invalid seal")))
    with pytest.raises(ValueError, match="invalid seal"):
        runtime.review(clean / "runtime.json", harness)


def test_fixed_worker_model_routing_and_configuration_do_not_use_interactive_selection(clean, monkeypatch):
    from connectors.fixed.pi.environment import isolated_configuration
    from connectors.fixed.pi.harness_model import _command

    config = clean / "worker-config"
    config.mkdir()
    (config / "models.json").write_text('{"providers":{"worker":{"baseUrl":"https://reviewed.invalid"}}}')
    interactive = clean / "interactive"
    monkeypatch.setenv("METERING_PI_CONFIG_DIR", str(config))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(interactive))
    monkeypatch.setenv("PI_PROVIDER", "interactive-provider")
    monkeypatch.setenv("PI_MODEL", "interactive-model")
    monkeypatch.setenv("METERING_PI_COMMAND", '["/pinned/pi"]')
    for key, value in {"PROVIDER": "worker", "MODEL": "worker-model", "REASONING": "medium"}.items():
        monkeypatch.setenv("METERING_HARNESS_" + key, value)
    with isolated_configuration():
        assert Path(os.environ["PI_CODING_AGENT_DIR"]) == config
        args = _command({"system_prompt": "fixed", "prompt": "isolated payload"})
        assert args[:7] == ["/pinned/pi", "--provider", "worker", "--model", "worker-model", "--thinking", "medium"]
        assert {"--no-session", "--no-extensions", "--no-skills", "--no-tools", "--no-context-files", "--no-prompt-templates"} <= set(args)
        assert "interactive-model" not in args
    assert os.environ["PI_CODING_AGENT_DIR"] == str(interactive)


@pytest.mark.parametrize(
    "binary", [shutil.which("pi"), str(PINNED) if PINNED.is_file() else None]
)
def test_real_pi_releases_expose_required_cli_without_inference(
    binary: str | None, clean: Path, monkeypatch: pytest.MonkeyPatch
):
    if binary is None:
        pytest.skip("Pi release not installed")
    monkeypatch.setenv("PI_BIN", binary)
    version = runtime._probe([binary], "--version")
    result = runtime.resolve(version)
    assert result["implementation_version"] == version
    assert result["cli_contract"] == "tool-free-json-cli-v1"
