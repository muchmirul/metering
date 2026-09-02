"""Fixed Pi proposer that applies one selected harness to a solution commit."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.coding_agent.harness_workspace_editor import (  # noqa: E402
    CodingMutationError,
    edit_solution_with_harness,
)
from apps.harness.runtime_manifest import load_runtime_manifest  # noqa: E402
from artifacts.git.git_proposer import ProposerError, run_main  # noqa: E402
from connectors.fixed.command import command_prefix  # noqa: E402
from connectors.fixed.harness_model_runtime import (  # noqa: E402
    HarnessModelAdapterError,
    verify_implementation,
)
from connectors.fixed.pi.environment import isolated_configuration  # noqa: E402

MODEL = Path(__file__).resolve().with_name("harness_model.py")


def _edit(workspace: Path, objective: str) -> None:
    edit_solution_with_harness(
        workspace,
        objective,
        model_command=[sys.executable, str(MODEL)],
        expected_connector="pi-v1",
    )


def main() -> int:
    try:
        path = os.environ.get("METERING_HARNESS_RUNTIME_MANIFEST")
        if not path:
            raise HarnessModelAdapterError(
                "METERING_HARNESS_RUNTIME_MANIFEST must name a profile"
            )
        runtime = load_runtime_manifest(Path(path))
        if runtime.model["connector"] != "pi-v1":
            raise HarnessModelAdapterError("runtime model connector must be pi-v1")
        verify_implementation(
            command_prefix("METERING_PI_COMMAND", "PI_BIN", "pi"),
            runtime.model["implementation_version"],
            "Pi",
        )
        with isolated_configuration():
            return run_main(
                agent_name="selected Pi evolutionary harness",
                edit_workspace=_edit,
            )
    except (
        CodingMutationError,
        HarnessModelAdapterError,
        ProposerError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
