"""Compatibility and effect-boundary regressions for experiment composition."""

from __future__ import annotations

import hashlib
import importlib
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json  # noqa: E402
from apps.coding_agent import experiment_artifacts  # noqa: E402
from apps.coding_agent.experiment_config import SolutionExperimentError  # noqa: E402


@pytest.fixture(params=["harness", "coding_agent"])
def entrypoint(request: pytest.FixtureRequest) -> tuple[str, ModuleType]:
    owner = request.param
    module = "experiment" if owner == "harness" else "solution_experiment"
    return owner, importlib.import_module(f"apps.{owner}.{module}")


def test_compatibility_exports_are_the_owning_implementations(entrypoint):
    owner, cli = entrypoint
    runtime = importlib.import_module(f"apps.{owner}.experiment_runtime")
    replay = importlib.import_module(f"apps.{owner}.experiment_replay")
    config = importlib.import_module(f"apps.{owner}.experiment_config")
    assert cli.run_experiment is runtime.run_experiment
    assert cli.continue_experiment is runtime.continue_experiment
    assert cli.verify_experiment is replay.verify_experiment
    error_name = "ExperimentError" if owner == "harness" else "SolutionExperimentError"
    assert getattr(cli, error_name) is getattr(config, error_name)


@pytest.mark.parametrize("operation", ["verify", "status", "resume", "retry"])
def test_existing_commands_dispatch_without_changing_arguments(
    entrypoint, operation, tmp_path, monkeypatch, capsys
):
    owner, cli = entrypoint
    status_function = (
        "harness_process_status" if owner == "harness" else "solution_process_status"
    )
    function = {
        "verify": "verify_experiment",
        "status": status_function,
        "resume": "continue_experiment",
        "retry": "continue_experiment",
    }[operation]
    calls = []
    result = {"status": "unchanged"}

    def handle(root, **kwargs):
        calls.append((root, kwargs))
        return result

    monkeypatch.setattr(cli, function, handle)
    arguments = [operation, str(tmp_path)]
    if operation == "retry":
        arguments.append("operator-reviewed retry")
    assert cli.main(arguments) == 0
    expected_kwargs = (
        {"retry_reason": "operator-reviewed retry"} if operation == "retry" else {}
    )
    assert calls == [(tmp_path, expected_kwargs)]
    output = capsys.readouterr()
    assert output.out == canonical_json(result) + "\n"
    assert output.err == ""


def test_compatibility_cli_rejects_invalid_arguments_from_another_directory(
    entrypoint, tmp_path
):
    _, cli = entrypoint
    completed = subprocess.run(
        [sys.executable, cli.__file__, "unexpected"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.startswith("usage: ")
    assert "Traceback" not in completed.stderr


def test_final_profile_read_and_copy_are_separate_effects(tmp_path, monkeypatch):
    checks = [{"argv": ["python", "check.py"], "case_id": "case", "timeout_ms": 1000}]
    source = tmp_path / "operator-final.json"
    payload = (
        canonical_json(
            {
                "checks": checks,
                "final_schema": "darwinian-coding-final-v1",
                "schema_version": 1,
            }
        )
        + "\n"
    ).encode("ascii")
    source.write_bytes(payload)
    root = tmp_path / "run"
    root.mkdir()
    profile = {
        "final_assay": {
            "path": str(source),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "goal": "Solve the reviewed task",
    }

    def forbid_reveal(*args, **kwargs):
        pytest.fail("read-only replay attempted to reveal the operator final profile")

    with monkeypatch.context() as guard:
        guard.setattr(experiment_artifacts, "load_final_profile", forbid_reveal)
        with pytest.raises(SolutionExperimentError, match="final profile is absent"):
            experiment_artifacts.load_protected_final_tasks(root, profile)
    assert list(root.iterdir()) == []

    expected = experiment_artifacts.copy_protected_final_tasks(root, profile)
    destination = root / "protected-final.json"
    assert destination.read_bytes() == payload
    source.unlink()
    assert experiment_artifacts.load_protected_final_tasks(root, profile) == expected
    assert experiment_artifacts.copy_protected_final_tasks(root, profile) == expected
    assert destination.read_bytes() == payload


def test_legacy_inline_final_does_not_create_a_profile(tmp_path):
    profile = {
        "goal": "Legacy task",
        "final_checks": [
            {"argv": ["python", "check.py"], "case_id": "case", "timeout_ms": 1000}
        ],
    }
    loaded = experiment_artifacts.load_protected_final_tasks(tmp_path, profile)
    assert experiment_artifacts.copy_protected_final_tasks(tmp_path, profile) == loaded
    assert list(tmp_path.iterdir()) == []
