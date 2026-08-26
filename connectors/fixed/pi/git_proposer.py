"""Fixed Pi connector that edits one disposable Git candidate workspace."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from artifacts.git.git_proposer import ProposerError, run_main  # noqa: E402
from connectors.fixed.command import command_prefix  # noqa: E402
from connectors.fixed.pi.environment import isolated_configuration  # noqa: E402


def _edit_workspace(workspace: Path, prompt: str) -> None:
    command = command_prefix("METERING_PI_COMMAND", "PI_BIN", "pi")
    command.extend(
        [
            "--no-session",
            "--no-skills",
            "--no-extensions",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "-p",
            prompt,
        ]
    )
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ProposerError(f"cannot start Pi: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"Pi exited with {completed.returncode}"
        raise ProposerError(detail)
    if completed.stderr:
        raise ProposerError("Pi wrote unexpected standard error")


def main() -> int:
    try:
        with isolated_configuration(include_auth=False):
            return run_main(agent_name="Pi", edit_workspace=_edit_workspace)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
