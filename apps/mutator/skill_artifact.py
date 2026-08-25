"""Encode one local Agent Skills directory as an agent-skill-v1 artifact."""

from __future__ import annotations

import sys
from pathlib import Path

APPS_ROOT = Path(__file__).resolve().parents[1]
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from agent_protocol import (  # noqa: E402
    ProtocolError,
    canonical_json,
    decode_agent_artifact,
)


class ArtifactError(ValueError):
    """Raised when a local skill cannot be represented by the v1 artifact."""


def encode_skill_directory(root: Path) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError(f"skill root must be a real directory: {root}")
    try:
        resolved = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ArtifactError(f"cannot resolve skill root: {root}") from exc

    files: list[dict[str, object]] = []
    for path in sorted(resolved.rglob("*")):
        relative = path.relative_to(resolved).as_posix()
        if path.is_symlink():
            raise ArtifactError(f"skill may not contain a symlink: {relative}")
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactError(f"skill file is not UTF-8 text: {relative}") from exc
        except OSError as exc:
            raise ArtifactError(f"cannot read skill file {relative}: {exc}") from exc
        files.append(
            {
                "content": content,
                "executable": bool(path.stat().st_mode & 0o111),
                "path": relative,
            }
        )
    try:
        return decode_agent_artifact(
            {"artifact_schema": "agent-skill-v1", "files": files}
        )
    except ProtocolError as exc:
        raise ArtifactError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        error = {
            "error": {
                "code": "invalid_request",
                "message": "usage: skill_artifact.py PATH",
            }
        }
        print(canonical_json(error), file=sys.stderr)
        return 2
    try:
        artifact = encode_skill_directory(Path(arguments[0]))
    except (ArtifactError, OSError) as exc:
        error = {"error": {"code": "invalid_artifact", "message": str(exc)}}
        print(canonical_json(error), file=sys.stderr)
        return 2
    print(canonical_json(artifact))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
