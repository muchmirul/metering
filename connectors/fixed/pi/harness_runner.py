"""Pi translation for the fixed evolutionary harness candidate executor."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.harness.harness_runner import run_main  # noqa: E402
from apps.harness.runtime_manifest import load_runtime_manifest  # noqa: E402
from connectors.fixed.command import command_prefix  # noqa: E402
from connectors.fixed.harness_model_runtime import (  # noqa: E402
    HarnessModelAdapterError,
    verify_implementation,
)

MODEL = Path(__file__).resolve().with_name("harness_model.py")


def main() -> int:
    try:
        path = os.environ.get("METERING_HARNESS_RUNTIME_MANIFEST")
        if not path:
            raise HarnessModelAdapterError(
                "METERING_HARNESS_RUNTIME_MANIFEST must name a profile"
            )
        runtime = load_runtime_manifest(Path(path))
        verify_implementation(
            command_prefix("METERING_PI_COMMAND", "PI_BIN", "pi"),
            runtime.model["implementation_version"],
            "Pi",
        )
    except (HarnessModelAdapterError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return run_main(
        default_model_command=[sys.executable, str(MODEL)],
        expected_connector="pi-v1",
    )


if __name__ == "__main__":
    raise SystemExit(main())
