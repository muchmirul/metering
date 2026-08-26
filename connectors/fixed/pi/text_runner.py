"""Fixed tool-free Pi connector for text-only candidate evaluation tasks."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from connectors.fixed.command import command_prefix, read_skill_text  # noqa: E402
from connectors.fixed.pi.environment import isolated_configuration  # noqa: E402
from connectors.fixed.text_runner_runtime import canonical_json, run_main  # noqa: E402


def _pi_command(skill_path: str | None, prompt: str) -> list[str]:
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
    if skill_path is not None:
        skill_file = Path(skill_path) / "SKILL.md"
        if not skill_file.is_file():
            raise ValueError("candidate skill does not contain SKILL.md")
        skill_text = read_skill_text(skill_file, "candidate SKILL.md")
        candidate_instructions = (
            "The following is the complete, caller-selected candidate skill. "
            "Apply it to the user task.\n\n"
            f"<candidate_skill path={canonical_json(str(skill_file))}>\n"
            f"{skill_text}\n"
            "</candidate_skill>"
        )
        command.extend(
            [
                "--skill",
                str(skill_file),
                "--append-system-prompt",
                candidate_instructions,
            ]
        )
    command.extend(["-p", prompt])
    return command


def main() -> int:
    try:
        with isolated_configuration():
            return run_main(agent_name="Pi", command_builder=_pi_command)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
