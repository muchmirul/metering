"""Isolate Prime Agent state from ambient continual-harness memory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from connectors.fixed.environment import isolated_agent_configuration


@contextmanager
def isolated_configuration(*, include_auth: bool = True) -> Iterator[None]:
    """Use an empty or caller-reviewed Prime Agent configuration directory."""

    with isolated_agent_configuration(
        active_environment="PRIME_AGENT_CODING_AGENT_DIR",
        reviewed_environment="METERING_PRIME_AGENT_CONFIG_DIR",
        default_directory=Path.home() / ".prime" / "agent",
        temporary_prefix="metering-prime-agent-config-",
        include_auth=include_auth,
    ):
        yield
