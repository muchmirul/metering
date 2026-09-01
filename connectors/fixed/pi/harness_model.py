"""Fixed tool-free Pi transport for one evolutionary harness model action."""

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
from connectors.fixed.pi.environment import isolated_configuration  # noqa: E402


def _command(request: dict[str, object]) -> list[str]:
    return [
        *command_prefix("METERING_PI_COMMAND", "PI_BIN", "pi"),
        *agent_arguments(request),
    ]


def main() -> int:
    try:
        with isolated_configuration():
            return run_main(agent_name="Pi", command_builder=_command)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
