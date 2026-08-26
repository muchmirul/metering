"""Isolate Pi connector state from ambient user configuration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from connectors.fixed.environment import isolated_agent_configuration


@contextmanager
def isolated_configuration(*, include_auth: bool = True) -> Iterator[None]:
    """Use a minimal temporary or caller-reviewed Pi configuration directory."""

    with isolated_agent_configuration(
        active_environment="PI_CODING_AGENT_DIR",
        reviewed_environment="METERING_PI_CONFIG_DIR",
        default_directory=Path.home() / ".pi" / "agent",
        temporary_prefix="metering-pi-config-",
        include_auth=include_auth,
    ):
        yield
