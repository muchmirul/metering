"""Private task workspace preparation creates only reviewed briefs and empty seeds."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_task_profile_tool import draft_document, git, write_draft

from apps.coding_agent.protocol import load_task_profile
from apps.coding_agent.task_profile_tool import TaskRegistrationError, create_workspace_profile


UUID = "01234567-89ab-4def-8123-456789abcdef"


def workspace_draft(tmp_path: Path) -> tuple[dict, Path, Path]:
    tasks = tmp_path / "tasks"
    root = tasks / "workspaces" / f"task-{UUID}"
    document = draft_document(root)
    document.update({
        "entrypoint": "answer.txt", "allowed_paths": ["answer.txt"],
        "goal": "messy input: fix teh answer pls", "requirements": ["Write the requested answer."],
        "assumptions": ["Use UTF-8 text."],
        "development_checks": [{"argv": ["python", "-c", "from pathlib import Path; assert Path('answer.txt').read_text() == 'done'"], "case_id": "answer", "timeout_ms": 1000}],
    })
    return document, root, tasks


def test_workspace_creates_clean_empty_seed_and_preserves_reviewed_brief(tmp_path: Path):
    document, root, tasks = workspace_draft(tmp_path)
    marker = tmp_path / "must-not-execute"
    document["development_checks"][0]["argv"] = ["python", "-c", f"open({str(marker)!r}, 'w').write('not allowed during preparation')"]
    source = tmp_path / "draft.json"
    write_draft(source, document)
    result = create_workspace_profile(source, tasks)
    assert result["workspace_created"] is True
    assert result["workspace_repository"] == str(root)
    assert not marker.exists(), "Model-drafted checks must never execute on the host"
    assert git(root, "status", "--porcelain") == ""
    assert git(root, "ls-files").splitlines() == ["TASK.md", "answer.txt"]
    assert (root / "answer.txt").read_bytes() == b""
    brief = (root / "TASK.md").read_text()
    assert document["goal"] in brief
    assert "## Requirements" in brief and "Write the requested answer." in brief
    assert "## Inferred assumptions" in brief and "Use UTF-8 text." in brief
    profile = load_task_profile(Path(result["profile"]))
    assert profile["goal"] == document["goal"]
    assert profile["repository"]["base_commit"] == git(root, "rev-parse", "HEAD")
    assert profile["allowed_paths"] == ["answer.txt"]
    before = git(root, "rev-parse", "HEAD")
    with pytest.raises(TaskRegistrationError, match="new task-UUID"):
        create_workspace_profile(source, tasks)
    assert git(root, "rev-parse", "HEAD") == before
    assert not marker.exists()


@pytest.mark.parametrize("paths", [["../escape"], [".git/config"], ["TASK.md"], ["TASK.md/child"], ["a", "a/b"], ["b", "a"], ["a", "a"], []])
def test_workspace_rejects_unsafe_or_conflicting_outputs_before_writing(tmp_path: Path, paths: list[str]):
    document, root, tasks = workspace_draft(tmp_path)
    document.update(allowed_paths=paths, entrypoint=paths[0] if paths else "answer.txt")
    source = tmp_path / "draft.json"
    write_draft(source, document)
    with pytest.raises(ValueError):
        create_workspace_profile(source, tasks)
    assert not root.exists() and not tasks.exists()


@pytest.mark.parametrize("field,value", [("requirements", []), ("requirements", ["x" * 1001]), ("assumptions", "invented"), ("assumptions", [True]), ("goal", ""), ("schema_version", True), ("repository_path", "/tmp/not-agentvolve-owned")])
def test_workspace_rejects_bad_brief_and_destination_before_writing(tmp_path: Path, field: str, value: object):
    document, root, tasks = workspace_draft(tmp_path)
    document[field] = value
    source = tmp_path / "draft.json"
    write_draft(source, document)
    with pytest.raises(TaskRegistrationError):
        create_workspace_profile(source, tasks)
    assert not root.exists() and not tasks.exists()


def test_workspace_refuses_symlinked_parent(tmp_path: Path):
    document, root, tasks = workspace_draft(tmp_path)
    tasks.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (tasks / "workspaces").symlink_to(outside, target_is_directory=True)
    source = tmp_path / "draft.json"
    write_draft(source, document)
    with pytest.raises(TaskRegistrationError, match="new task-UUID"):
        create_workspace_profile(source, tasks)
    assert list(outside.iterdir()) == [] and not root.exists()


def test_failed_registration_preserves_the_new_seed_without_retry(tmp_path: Path):
    document, root, tasks = workspace_draft(tmp_path)
    document["limits"]["max_wall_seconds"] = 1
    source = tmp_path / "draft.json"
    write_draft(source, document)
    with pytest.raises(TaskRegistrationError, match="created files are retained"):
        create_workspace_profile(source, tasks)
    assert (root / "answer.txt").read_bytes() == b""
    assert git(root, "status", "--porcelain") == ""
    commit = git(root, "rev-parse", "HEAD")
    assert not list(tasks.glob("*.task.json"))
    assert not list(tasks.glob("*.final.json"))
    with pytest.raises(TaskRegistrationError, match="new task-UUID"):
        create_workspace_profile(source, tasks)
    assert git(root, "rev-parse", "HEAD") == commit
