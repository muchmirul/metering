"""Isolate Pi connector state from ambient user configuration."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def isolated_configuration(*, include_auth: bool = True) -> Iterator[None]:
    """Use a minimal temporary or caller-reviewed Pi configuration directory."""

    reviewed = os.environ.get("METERING_PI_CONFIG_DIR")
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if reviewed:
        path = Path(reviewed)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError(
                "METERING_PI_CONFIG_DIR must name an existing absolute directory"
            )
        configuration = str(path)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="metering-pi-config-")
        configuration_path = Path(temporary.name)
        source_name = os.environ.get("PI_CODING_AGENT_DIR")
        source = (
            Path(source_name).expanduser()
            if source_name
            else Path.home() / ".pi" / "agent"
        )
        filenames = (
            ("auth.json", "models.json") if include_auth else ("models.json",)
        )
        for filename in filenames:
            source_file = source / filename
            if source_file.is_file() and not source_file.is_symlink():
                target = configuration_path / filename
                shutil.copyfile(source_file, target)
                target.chmod(0o600)
        configuration = str(configuration_path)

    name = "PI_CODING_AGENT_DIR"
    previous = os.environ.get(name)
    os.environ[name] = configuration
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous
        if temporary is not None:
            temporary.cleanup()
