"""Bounded workspace documents for coding inside the isolated harness kernel."""

from __future__ import annotations

import base64
import hashlib
import shutil
from pathlib import Path, PurePosixPath
from typing import cast

from apps._support.wire import canonical_digest

MAX_WORKSPACE_BYTES = 8_388_608
MAX_WORKSPACE_FILES = 2_000
MAX_WORKSPACE_OUTPUT_CHARACTERS = 65_536


class WorkspaceError(ValueError):
    """Raised when a coding workspace is unsafe, oversized, or malformed."""


def normalized_path(value: object, location: str) -> str:
    if type(value) is not str or not value or "\x00" in value or "\\" in value:
        raise WorkspaceError(f"{location} must be a normalized relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", "..", ".git"} for part in path.parts)
    ):
        raise WorkspaceError(f"{location} must be a normalized relative POSIX path")
    return value


def _integer(value: object, location: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise WorkspaceError(
            f"{location} must be an integer from {minimum} through {maximum}"
        )
    return value


def normalize_policy(value: object) -> dict[str, object]:
    location = "workspace policy"
    if type(value) is not dict or set(value) != {
        "allowed_write_paths",
        "command_timeout_ms",
        "max_bytes",
        "max_files",
        "max_output_characters",
    }:
        raise WorkspaceError(f"{location} is malformed")
    raw_paths = value["allowed_write_paths"]
    if type(raw_paths) is not list or not raw_paths:
        raise WorkspaceError(f"{location}.allowed_write_paths must be non-empty")
    paths: list[str] = []
    for index, raw in enumerate(raw_paths):
        path = normalized_path(raw, f"{location}.allowed_write_paths[{index}]")
        if path in paths:
            raise WorkspaceError(f"{location}.allowed_write_paths contains a duplicate")
        paths.append(path)
    if paths != sorted(paths):
        raise WorkspaceError(f"{location}.allowed_write_paths must be sorted")
    return {
        "allowed_write_paths": paths,
        "command_timeout_ms": _integer(
            value["command_timeout_ms"],
            f"{location}.command_timeout_ms",
            10,
            3_600_000,
        ),
        "max_bytes": _integer(
            value["max_bytes"], f"{location}.max_bytes", 1, MAX_WORKSPACE_BYTES
        ),
        "max_files": _integer(
            value["max_files"], f"{location}.max_files", 1, MAX_WORKSPACE_FILES
        ),
        "max_output_characters": _integer(
            value["max_output_characters"],
            f"{location}.max_output_characters",
            128,
            MAX_WORKSPACE_OUTPUT_CHARACTERS,
        ),
    }


def _decode_files(
    value: object,
    *,
    location: str,
    max_files: int,
    max_bytes: int,
) -> list[dict[str, object]]:
    if type(value) is not list or not value or len(value) > max_files:
        raise WorkspaceError(
            f"{location} must contain from 1 through {max_files} files"
        )
    files: list[dict[str, object]] = []
    paths: list[str] = []
    total = 0
    for index, raw in enumerate(value):
        item_location = f"{location}[{index}]"
        if type(raw) is not dict or set(raw) != {
            "content_base64",
            "executable",
            "path",
        }:
            raise WorkspaceError(f"{item_location} is malformed")
        path = normalized_path(raw["path"], f"{item_location}.path")
        if path in paths:
            raise WorkspaceError(f"{location} contains duplicate path: {path}")
        encoded = raw["content_base64"]
        if type(encoded) is not str or type(raw["executable"]) is not bool:
            raise WorkspaceError(f"{item_location} content or mode is malformed")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (TypeError, ValueError) as exc:
            raise WorkspaceError(f"{item_location}.content_base64 is invalid") from exc
        if base64.b64encode(content).decode("ascii") != encoded:
            raise WorkspaceError(
                f"{item_location}.content_base64 is not canonical base64"
            )
        total += len(content)
        if total > max_bytes:
            raise WorkspaceError(f"{location} exceeds {max_bytes} bytes")
        paths.append(path)
        files.append(
            {
                "content_base64": encoded,
                "executable": raw["executable"],
                "path": path,
            }
        )
    if paths != sorted(paths):
        raise WorkspaceError(f"{location} must be sorted by path")
    return files


def decode_files(
    value: object,
    *,
    location: str = "workspace files",
    max_files: int = MAX_WORKSPACE_FILES,
    max_bytes: int = MAX_WORKSPACE_BYTES,
) -> list[dict[str, object]]:
    return _decode_files(
        value, location=location, max_files=max_files, max_bytes=max_bytes
    )


def files_digest(files: list[dict[str, object]]) -> str:
    return canonical_digest({"files": files})


def decode_export(value: object, policy: dict[str, object]) -> dict[str, object]:
    normalized_policy = normalize_policy(policy)
    if type(value) is not dict or set(value) != {"changed_paths", "files", "sha256"}:
        raise WorkspaceError("workspace export is malformed")
    files = _decode_files(
        value["files"],
        location="workspace export.files",
        max_files=cast(int, normalized_policy["max_files"]),
        max_bytes=cast(int, normalized_policy["max_bytes"]),
    )
    raw_changed = value["changed_paths"]
    if type(raw_changed) is not list:
        raise WorkspaceError("workspace export.changed_paths must be an array")
    changed: list[str] = []
    for index, raw in enumerate(raw_changed):
        path = normalized_path(raw, f"workspace export.changed_paths[{index}]")
        if path in changed:
            raise WorkspaceError("workspace export.changed_paths contains a duplicate")
        changed.append(path)
    if changed != sorted(changed):
        raise WorkspaceError("workspace export.changed_paths must be sorted")
    body = {"changed_paths": changed, "files": files}
    expected = canonical_digest(body)
    if value["sha256"] != expected:
        raise WorkspaceError("workspace export digest does not match")
    return {**body, "sha256": expected}


def snapshot_directory(
    root: Path,
    *,
    max_files: int = MAX_WORKSPACE_FILES,
    max_bytes: int = MAX_WORKSPACE_BYTES,
    ignore_git: bool = True,
) -> list[dict[str, object]]:
    root = root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise WorkspaceError("workspace source must be a non-symlink directory")
    files: list[dict[str, object]] = []
    total = 0
    try:
        entries = sorted(root.rglob("*"))
    except OSError as exc:
        raise WorkspaceError(f"cannot inspect workspace source: {exc}") from exc
    for path in entries:
        relative_path = path.relative_to(root)
        if ignore_git and relative_path.parts and relative_path.parts[0] == ".git":
            continue
        relative = normalized_path(relative_path.as_posix(), "workspace source path")
        if path.is_symlink():
            raise WorkspaceError(f"workspace source contains a symlink: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise WorkspaceError(
                f"workspace source contains a non-regular entry: {relative}"
            )
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise WorkspaceError(
                f"cannot read workspace source {relative}: {exc}"
            ) from exc
        total += len(content)
        if len(files) >= max_files:
            raise WorkspaceError(f"workspace source exceeds {max_files} files")
        if total > max_bytes:
            raise WorkspaceError(f"workspace source exceeds {max_bytes} bytes")
        files.append(
            {
                "content_base64": base64.b64encode(content).decode("ascii"),
                "executable": bool(path.stat().st_mode & 0o111),
                "path": relative,
            }
        )
    if not files:
        raise WorkspaceError("workspace source must contain at least one file")
    return files


def changed_paths(
    before: list[dict[str, object]], after: list[dict[str, object]]
) -> list[str]:
    def identities(files: list[dict[str, object]]) -> dict[str, tuple[str, bool]]:
        return {
            str(item["path"]): (
                hashlib.sha256(
                    base64.b64decode(str(item["content_base64"]), validate=True)
                ).hexdigest(),
                bool(item["executable"]),
            )
            for item in files
        }

    old = identities(before)
    new = identities(after)
    return sorted(
        path for path in set(old) | set(new) if old.get(path) != new.get(path)
    )


def require_allowed_changes(paths: list[str], allowed: list[str]) -> None:
    for path in paths:
        if not any(
            path == prefix or path.startswith(prefix.rstrip("/") + "/")
            for prefix in allowed
        ):
            raise WorkspaceError(f"workspace changed disallowed path: {path}")


def materialize_files(files: object, destination: Path) -> None:
    normalized = decode_files(files)
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise WorkspaceError("workspace destination is unsafe")
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for item in normalized:
        relative = str(item["path"])
        target = destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = base64.b64decode(str(item["content_base64"]), validate=True)
        target.write_bytes(content)
        target.chmod(0o755 if item["executable"] else 0o644)
