"""Fixed tool-free Pi connector for one complete replacement SKILL.md."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from connectors.fixed.command import command_prefix, read_skill_text  # noqa: E402
from connectors.fixed.pi.environment import isolated_configuration  # noqa: E402
from connectors.fixed.skill_proposer_runtime import (  # noqa: E402
    canonical_json,
    run_main,
)


def _pi_command(skill_file: Path | None, prompt: str) -> list[str]:
    command = command_prefix("METERING_PI_COMMAND", "PI_BIN", "pi")
    command.extend(
        [
            "--no-session",
            "--no-skills",
            "--no-extensions",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--no-tools",
        ]
    )
    if skill_file is not None:
        skill_text = read_skill_text(skill_file, "parent SKILL.md")
        instructions = (
            "The following is the complete, caller-selected current skill. Apply "
            "its useful instructions while proposing one replacement.\n\n"
            f"<current_skill path={canonical_json(str(skill_file))}>\n"
            f"{skill_text}\n"
            "</current_skill>"
        )
        command.extend(
            [
                "--skill",
                str(skill_file),
                "--append-system-prompt",
                instructions,
            ]
        )
    command.extend(["-p", prompt])
    return command


def main() -> int:
    try:
        with isolated_configuration():
            return run_main(
                agent_name="Pi",
                command_builder=_pi_command,
                temporary_prefix="metering-pi-proposer-",
            )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
