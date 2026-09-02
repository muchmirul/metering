"""Fixed tool-free Prime Agent transport for one harness model action."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from connectors.fixed.command import command_prefix  # noqa: E402
from connectors.fixed.harness_model_runtime import (  # noqa: E402
    agent_arguments,
    run_main,
)
from connectors.fixed.prime_agent.environment import (  # noqa: E402
    isolated_configuration,
)


def _command(request: dict[str, object]) -> list[str]:
    return [
        *command_prefix(
            "METERING_PRIME_AGENT_COMMAND",
            "PRIME_AGENT_BIN",
            "prime-agent",
        ),
        *agent_arguments(request),
    ]


def main() -> int:
    try:
        with isolated_configuration():
            return run_main(agent_name="Prime Agent", command_builder=_command)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
