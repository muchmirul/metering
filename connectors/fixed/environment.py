"""Shared least-privilege configuration isolation for fixed connectors."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _temporary_environment(name: str, value: str) -> Iterator[None]:
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


@contextmanager
def isolated_agent_configuration(
    *,
    active_environment: str,
    reviewed_environment: str,
    default_directory: Path,
    temporary_prefix: str,
    include_auth: bool,
) -> Iterator[None]:
    """Expose only a reviewed directory or copied model/auth files."""

    reviewed = os.environ.get(reviewed_environment)
    if reviewed is not None:
        path = Path(reviewed)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError(
                f"{reviewed_environment} must name an existing absolute directory"
            )
        with _temporary_environment(active_environment, str(path)):
            yield
        return

    source_name = os.environ.get(active_environment)
    source = (
        Path(source_name).expanduser() if source_name else default_directory
    )
    filenames = ("auth.json", "models.json") if include_auth else ("models.json",)
    with tempfile.TemporaryDirectory(prefix=temporary_prefix) as temporary:
        configuration = Path(temporary)
        for filename in filenames:
            source_file = source / filename
            if not source_file.is_file() or source_file.is_symlink():
                continue
            target = configuration / filename
            try:
                shutil.copyfile(source_file, target)
                target.chmod(0o600)
            except OSError as exc:
                raise ValueError(f"cannot isolate {source_file}: {exc}") from exc
        with _temporary_environment(active_environment, str(configuration)):
            yield
