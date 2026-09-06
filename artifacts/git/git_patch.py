"""Byte-preserving Git patches and independent, disposable-index verification."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from artifacts.git.git_repository import GitCandidateError, run_git, run_git_bytes

PATCH_FLAGS = (
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--no-renames",
    "--binary",
)


def create_patch(repository: Path, base: str, selected: str) -> bytes:
    return run_git_bytes(["diff", *PATCH_FLAGS, base, selected], cwd=repository)


def verify_patch_tree(
    repository: Path, base: str, selected_tree: str, patch: bytes
) -> None:
    """Apply to a temporary clone's index, never the source or recorded run.

    Index-only application avoids checkout filters and newline conversion. It
    verifies file modes and binary blobs as well as textual patch applicability.
    All Git object and index writes remain in the disposable clone.
    """
    with tempfile.TemporaryDirectory(prefix="metering-patch-verify-") as temporary:
        clone = Path(temporary) / "candidate.git"
        run_git(
            [
                "-c",
                "protocol.file.allow=always",
                "clone",
                "--quiet",
                "--bare",
                "--no-local",
                str(repository.absolute()),
                str(clone),
            ]
        )
        environment = {**os.environ, "GIT_INDEX_FILE": str(Path(temporary) / "index")}
        run_git(["read-tree", base], cwd=clone, environment=environment)
        if patch:
            run_git_bytes(
                ["apply", "--cached", "--binary", "--whitespace=nowarn", "-"],
                cwd=clone,
                input_bytes=patch,
                environment=environment,
            )
        tree = run_git(["write-tree"], cwd=clone, environment=environment).strip()
        if tree != selected_tree:
            raise GitCandidateError("patch does not reproduce the selected Git tree")
