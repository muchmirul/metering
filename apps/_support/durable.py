"""Minimal durable load/store primitives for source-only state owners."""

from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path


def reject_symlink(path: Path, location: str, error_type: type[Exception]) -> None:
    """Reject an existing symbolic link without following it."""

    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode):
        raise error_type(f"{location} must not be a symbolic link")


def fsync_directory(path: Path) -> None:
    """Best-effort fsync for a directory containing an atomic transition."""

    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    """Atomically replace one file with fully fsynced caller-supplied bytes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = -1
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
