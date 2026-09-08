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
