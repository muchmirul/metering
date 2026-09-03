"""Create one verified git-candidate-v1 descriptor from an immutable commit."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.agent_protocol import (  # noqa: E402
    GIT_ARTIFACT_SCHEMA,
    ProtocolError,
    decode_agent_artifact,
    require_exact_keys,
    require_nonempty_string,
)
from apps._support.wire import (  # noqa: E402
    canonical_json,
    decode_json_object,
)

from artifacts.git.git_repository import (  # noqa: E402
    GitCandidateError,
    clone_commit,
    clone_verified,
    content_sha256,
)


class ArtifactError(ValueError):
    """Raised when a Git commit cannot become a candidate artifact."""


def create_artifact(source: str) -> dict[str, object]:
    request = decode_json_object(source, ArtifactError)
    try:
        require_exact_keys(
            request, {"commit", "entrypoint", "outputs", "repository"}, "request"
        )
        repository = require_nonempty_string(request["repository"], "repository")
        commit = require_nonempty_string(request["commit"], "commit")
        entrypoint = require_nonempty_string(request["entrypoint"], "entrypoint")
    except ProtocolError as exc:
        raise ArtifactError(str(exc)) from exc
    with tempfile.TemporaryDirectory(prefix="metering-git-artifact-") as temporary:
        checkout = Path(temporary) / "checkout"
        _, tree = clone_commit(repository, commit, checkout)
        candidate = {
            "artifact_schema": GIT_ARTIFACT_SCHEMA,
            "commit": commit,
            "content_sha256": content_sha256(checkout, commit),
            "entrypoint": entrypoint,
            "git_tree": tree,
            "outputs": request["outputs"],
            "repository": repository,
        }
        try:
            artifact = decode_agent_artifact(candidate)
            verified = Path(temporary) / "verified"
            clone_verified(artifact, verified)
        except ProtocolError as exc:
            raise ArtifactError(str(exc)) from exc
    return artifact


def main() -> int:
    try:
        artifact = create_artifact(sys.stdin.read())
    except (
        ArtifactError,
        GitCandidateError,
        ProtocolError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(artifact))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
