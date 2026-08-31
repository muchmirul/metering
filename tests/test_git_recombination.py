from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "artifacts" / "git" / "git_recombiner.py"

sys.path.insert(0, str(ROOT / "apps"))
sys.path.insert(0, str(ROOT / "artifacts" / "git"))

from agent_protocol import candidate_record  # noqa: E402
from git_repository import content_sha256  # noqa: E402


def git(*arguments: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def make_commit(
    worktree: Path,
    files: dict[str, str],
    message: str,
    parents: tuple[str, ...] = (),
) -> str:
    for path in worktree.iterdir():
        if path.name == ".git":
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    for name, content in files.items():
        path = worktree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git("add", "--all", cwd=worktree)
    tree = git("write-tree", cwd=worktree)
    command = ["git", "commit-tree", tree]
    for parent in parents:
        command.extend(["-p", parent])
    result = subprocess.run(
        command,
        cwd=worktree,
        input=message + "\n",
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        },
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def artifact(remote: Path, worktree: Path, commit: str) -> dict[str, object]:
    tree = git("rev-parse", f"{commit}^{{tree}}", cwd=worktree)
    return candidate_record(
        {
            "artifact_schema": "git-candidate-v1",
            "commit": commit,
            "content_sha256": content_sha256(worktree, commit),
            "entrypoint": "main.py",
            "git_tree": tree,
            "outputs": [],
            "repository": str(remote),
        }
    )


def repositories(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    worktree = tmp_path / "work"
    git("init", "--bare", str(remote), cwd=tmp_path)
    git("init", str(worktree), cwd=tmp_path)
    return remote, worktree


def test_recombiner_creates_two_parent_content_verified_child(tmp_path: Path) -> None:
    remote, worktree = repositories(tmp_path)
    left = make_commit(
        worktree,
        {
            "main.py": 'print("left")\n',
            "left.txt": "L\n",
            "shared.txt": "left\n",
        },
        "left",
    )
    right = make_commit(
        worktree,
        {
            "main.py": 'print("right")\n',
            "right.txt": "R\n",
            "shared.txt": "right\n",
        },
        "right",
    )
    git("remote", "add", "origin", str(remote), cwd=worktree)
    git(
        "push",
        "origin",
        f"{left}:refs/heads/left",
        f"{right}:refs/heads/right",
        cwd=worktree,
    )
    left_candidate = artifact(remote, worktree, left)
    right_candidate = artifact(remote, worktree, right)
    request = {
        "schema_version": 1,
        "generation": 1,
        "parents": [left_candidate, right_candidate],
        "path_sources": {"main.py": 1, "shared.txt": 0},
        "entrypoint": "main.py",
        "outputs": [],
    }
    environment = {
        **os.environ,
        "METERING_GIT_REPOSITORY": str(remote),
        "METERING_GIT_REF_PREFIX": "refs/heads/evolution",
    }

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
        env=environment,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    child = response["child"]
    commit = child["artifact"]["commit"]
    inspect = tmp_path / "inspect"
    git("clone", "--quiet", str(remote), str(inspect), cwd=tmp_path)
    git("checkout", "--quiet", commit, cwd=inspect)
    assert (inspect / "main.py").read_text() == 'print("right")\n'
    assert (inspect / "shared.txt").read_text() == "left\n"
    assert (inspect / "left.txt").read_text() == "L\n"
    assert (inspect / "right.txt").read_text() == "R\n"
    parent_lines = [
        line
        for line in git("cat-file", "-p", commit, cwd=inspect).splitlines()
        if line.startswith("parent ")
    ]
    assert parent_lines == [f"parent {left}", f"parent {right}"]
    assert response["recombination"]["parent_candidate_ids"] == [
        left_candidate["candidate_id"],
        right_candidate["candidate_id"],
    ]
    assert response["recombination"]["path_provenance"]["main.py"] == (
        right_candidate["candidate_id"]
    )


def test_recombiner_requires_explicit_choice_for_conflicts(tmp_path: Path) -> None:
    remote, worktree = repositories(tmp_path)
    left = make_commit(worktree, {"main.py": "left\n"}, "left")
    right = make_commit(worktree, {"main.py": "right\n"}, "right")
    git("remote", "add", "origin", str(remote), cwd=worktree)
    git(
        "push",
        "origin",
        f"{left}:refs/heads/left",
        f"{right}:refs/heads/right",
        cwd=worktree,
    )
    request = {
        "schema_version": 1,
        "generation": 1,
        "parents": [
            artifact(remote, worktree, left),
            artifact(remote, worktree, right),
        ],
        "path_sources": {},
        "entrypoint": "main.py",
        "outputs": [],
    }

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "METERING_GIT_REPOSITORY": str(remote),
            "METERING_GIT_REF_PREFIX": "refs/heads/evolution",
        },
    )

    assert result.returncode == 2
    assert "conflicting path: main.py" in result.stderr
