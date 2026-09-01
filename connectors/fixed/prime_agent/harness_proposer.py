"""Tool-free Prime Agent mutator for typed evolutionary harness Git candidates."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.harness.runtime_manifest import load_runtime_manifest  # noqa: E402
from artifacts.git.git_proposer import ProposerError, run_main  # noqa: E402
from connectors.fixed.command import command_prefix  # noqa: E402
from connectors.fixed.harness_model_runtime import (  # noqa: E402
    HarnessModelAdapterError,
    pinned_model_arguments,
    verify_implementation,
)
from connectors.fixed.harness_proposer_runtime import edit_with_agent  # noqa: E402
from connectors.fixed.prime_agent.environment import (  # noqa: E402
    isolated_configuration,
)


def _command(system: str, prompt: str) -> list[str]:
    provider, model, reasoning = pinned_model_arguments()
    return [
        *command_prefix(
            "METERING_PRIME_AGENT_COMMAND", "PRIME_AGENT_BIN", "prime-agent"
        ),
        "--provider",
        provider,
        "--model",
        model,
        "--thinking",
        reasoning,
        "--no-session",
        "--no-skills",
        "--no-extensions",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--no-tools",
        "--system-prompt",
        system,
        "-p",
        prompt,
    ]


def _edit(workspace: Path, objective: str) -> None:
    edit_with_agent(
        workspace,
        objective,
        agent_name="Prime Agent",
        command_builder=_command,
    )


def main() -> int:
    try:
        path = os.environ.get("METERING_HARNESS_RUNTIME_MANIFEST")
        if not path:
            raise HarnessModelAdapterError(
                "METERING_HARNESS_RUNTIME_MANIFEST must name a profile"
            )
        runtime = load_runtime_manifest(Path(path))
        if runtime.model["connector"] != "prime-agent-v1":
            raise HarnessModelAdapterError(
                "runtime model connector must be prime-agent-v1"
            )
        verify_implementation(
            command_prefix(
                "METERING_PRIME_AGENT_COMMAND", "PRIME_AGENT_BIN", "prime-agent"
            ),
            runtime.model["implementation_version"],
            "Prime Agent",
        )
        os.environ["METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES"] = str(
            runtime.max_output_bytes
        )
        os.environ["METERING_HARNESS_MODEL_TIMEOUT"] = str(
            runtime.model_timeout_seconds
        )
        with isolated_configuration():
            return run_main(
                agent_name="Prime Agent harness mutator", edit_workspace=_edit
            )
    except (HarnessModelAdapterError, ProposerError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
