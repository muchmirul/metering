from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json  # noqa: E402
from apps.coding_agent.protocol import (  # noqa: E402
    load_final_profile,
    load_task_profile,
)
from apps.coding_agent.task_profile_tool import (  # noqa: E402
    TaskRegistrationError,
    create_profile,
    derive_profile,
    validate_draft,
)


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Task Profile Test")
    git(root, "config", "user.email", "task-profile@example.invalid")
    (root / "answer.txt").write_text("TODO\n", encoding="utf-8")
    (root / "check.py").write_text(
        "from pathlib import Path\n"
        "assert Path('answer.txt').read_text().strip() == 'done'\n",
        encoding="utf-8",
    )
    git(root, "add", "answer.txt", "check.py")
    git(root, "commit", "-m", "Create task")
    return root, git(root, "rev-parse", "HEAD")


def draft_document(root: Path) -> dict[str, object]:
    return {
        "allowed_paths": ["answer.txt"],
        "development_checks": [
            {
                "argv": ["python", "check.py"],
                "case_id": "visible-check",
                "timeout_ms": 20000,
            }
        ],
        "draft_schema": "agentvolve-session-task-draft-v1",
        "entrypoint": "answer.txt",
        "final_policy": "replay-development-checks-v1",
        "goal": "Write the independently checked answer to answer.txt.",
        "limits": {
            "max_proposal_calls": 6,
            "max_rounds": 4,
            "max_wall_seconds": 100000,
        },
        "name": "session-answer",
        "repository_path": str(root),
        "schema_version": 1,
        "stopping": {
            "minimum_replicates": 1,
            "type": "all-development-cases-pass-v1",
        },
    }


def write_draft(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("mode", ["valid", "missing-timeout", "string-timeout", "bool-timeout", "zero-timeout", "empty-checks", "empty-argv", "duplicate-check", "bad-stopping", "scalar-stdout", "array-stdout", "empty-stdout"])
def test_draft_validation_reuses_profile_rules_without_effects(tmp_path: Path, monkeypatch, mode: str):
    marker = tmp_path / "must-not-execute"
    document = draft_document(tmp_path / "not-created")
    check = document["development_checks"][0]
    check["argv"] = ["python", "-c", f"open({str(marker)!r}, 'w').write('forbidden')"]
    if mode == "missing-timeout":
        del check["timeout_ms"]
    elif mode in {"string-timeout", "bool-timeout", "zero-timeout"}:
        check["timeout_ms"] = {"string-timeout": "1000", "bool-timeout": True, "zero-timeout": 0}[mode]
    elif mode == "empty-checks":
        document["development_checks"] = []
    elif mode == "empty-argv":
        check["argv"] = []
    elif mode == "duplicate-check":
        document["development_checks"].append(check.copy())
    elif mode == "bad-stopping":
        document["stopping"]["minimum_replicates"] = 5
    elif mode in {"scalar-stdout", "array-stdout", "empty-stdout"}:
        check.update(check_schema="stdout-json-v1", expected_stdout={"scalar-stdout": "value", "array-stdout": ["value"], "empty-stdout": {}}[mode])
    path = tmp_path / "draft.json"
    write_draft(path, document)
    payload = path.read_bytes()
    monkeypatch.setattr("apps.coding_agent.task_profile_tool.run_git", lambda *_args, **_kwargs: pytest.fail("Validation must not run Git"))
    if mode == "valid":
        assert validate_draft(path) == {"authority": "diagnostic-only", "draft_validation_schema": "agentvolve-task-draft-validation-v1"}
        result = subprocess.run([sys.executable, "-m", "apps.coding_agent.task_profile_tool", "validate-draft", "existing", str(path)], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0 and result.stderr == ""
        assert json.loads(result.stdout)["authority"] == "diagnostic-only"
    else:
        with pytest.raises(ValueError):
            validate_draft(path)
    assert path.read_bytes() == payload, "Do not repair malformed model output silently"
    assert list(tmp_path.iterdir()) == [path], "No registration, workspace, final assay or check execution"


def test_create_profile_binds_reviewed_clean_repository(tmp_path: Path):
    source, commit = repository(tmp_path)
    draft = tmp_path / "draft.json"
    output = tmp_path / "registered"
    write_draft(draft, draft_document(source))

    result = create_profile(draft, output)

    assert result["registration_schema"] == "agentvolve-task-registration-v1"
    assert result["base_commit"] == commit
    assert result["final_policy"] == "replay-development-checks-v1"
    task_path = Path(str(result["profile"]))
    final_path = Path(str(result["final_profile"]))
    assert task_path.parent == output
    assert final_path.parent == output
    profile = load_task_profile(task_path)
    _, final_checks = load_final_profile(profile)
    assert profile["task_id"] == result["task_id"]
    assert profile["repository"] == {
        "base_commit": commit,
        "entrypoint": "answer.txt",
        "path": str(source),
    }
    assert len(profile["allocation_draws"]) == 3
    assert final_checks == profile["development_checks"]
    assert (
        task_path.read_text(encoding="ascii")
        == canonical_json(
            {key: value for key, value in profile.items() if key != "task_id"}
        )
        + "\n"
    )


def test_derive_profile_applies_goal_and_generation_limit(tmp_path: Path):
    source, commit = repository(tmp_path)
    draft = tmp_path / "draft.json"
    templates = tmp_path / "templates"
    generated = tmp_path / "generated"
    write_draft(draft, draft_document(source))
    registration = create_profile(draft, templates)
    template_path = Path(str(registration["profile"]))
    goal = tmp_path / "goal.txt"
    goal.write_text(
        "Complete the task described in this Pi session.\n", encoding="utf-8"
    )

    result = derive_profile(template_path, goal, 100, generated)

    profile = load_task_profile(Path(str(result["profile"])))
    assert result["registration_schema"] == "agentvolve-task-derivation-v1"
    assert result["source_profile"] == str(template_path)
    assert profile["goal"] == "Complete the task described in this Pi session."
    assert profile["repository"]["base_commit"] == commit
    assert profile["limits"] == {
        "max_proposal_calls": 102,
        "max_rounds": 100,
        "max_wall_seconds": 100000,
    }
    assert len(profile["allocation_draws"]) == 99


def test_derive_profile_rejects_dirty_repository(tmp_path: Path):
    source, _ = repository(tmp_path)
    draft = tmp_path / "draft.json"
    write_draft(draft, draft_document(source))
    registration = create_profile(draft, tmp_path / "templates")
    (source / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    goal = tmp_path / "goal.txt"
    goal.write_text("Do the task.\n", encoding="utf-8")

    with pytest.raises(TaskRegistrationError, match="must be clean"):
        derive_profile(
            Path(str(registration["profile"])), goal, 4, tmp_path / "generated"
        )


def test_registration_does_not_execute_repository_fsmonitor(tmp_path: Path):
    source, _ = repository(tmp_path)
    marker = tmp_path / "monitor-must-not-run"
    monitor = tmp_path / "monitor.sh"
    monitor.write_text(f"#!/bin/sh\nprintf forbidden > '{marker}'\n")
    monitor.chmod(0o755)
    git(source, "config", "core.fsmonitor", str(monitor))
    draft = tmp_path / "draft.json"
    write_draft(draft, draft_document(source))
    create_profile(draft, tmp_path / "registered")
    assert not marker.exists()


def test_create_profile_rejects_uncommitted_session_input(tmp_path: Path):
    source, _ = repository(tmp_path)
    (source / "uncommitted.txt").write_text("not in the reviewed commit\n")
    draft = tmp_path / "draft.json"
    write_draft(draft, draft_document(source))

    with pytest.raises(TaskRegistrationError, match="must be clean"):
        create_profile(draft, tmp_path / "registered")


def test_create_profile_rejects_missing_entrypoint(tmp_path: Path):
    source, _ = repository(tmp_path)
    document = draft_document(source)
    document["entrypoint"] = "missing.txt"
    draft = tmp_path / "draft.json"
    write_draft(draft, document)

    with pytest.raises(TaskRegistrationError, match="entrypoint must exist"):
        create_profile(draft, tmp_path / "registered")


def test_create_profile_keeps_profiles_outside_candidate_repository(tmp_path: Path):
    source, _ = repository(tmp_path)
    draft = tmp_path / "draft.json"
    write_draft(draft, draft_document(source))

    with pytest.raises(TaskRegistrationError, match="must be outside"):
        create_profile(draft, source / "registered")


def test_preflight_cli_reports_assurance_and_bounds_harness_errors(tmp_path: Path):
    source, _ = repository(tmp_path)
    draft = tmp_path / "draft.json"
    write_draft(draft, draft_document(source))
    registration = create_profile(draft, tmp_path / "registered")
    command = [
        sys.executable,
        "-m",
        "apps.coding_agent.task_profile_tool",
        "preflight",
        str(registration["profile"]),
    ]
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    metadata = json.loads(result.stdout)
    assert metadata["preflight_schema"] == "agentvolve-operator-preflight-v1"
    assert metadata["warnings"]
    assert "visible-check" not in result.stdout
    invalid = subprocess.run(
        [
            *command,
            str(ROOT / "apps/harness/profiles/runtime-fixture.json"),
            str(tmp_path / "absent.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert "bounded regular file" in invalid.stderr
    assert "Traceback" not in invalid.stderr
