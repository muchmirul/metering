"""Run one live Pi Git-adapter/model-artifact evolution in a new directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.agent_protocol import (  # noqa: E402
    GIT_ARTIFACT_SCHEMA,
    decode_agent_artifact,
)
from apps.stdio_connector import (  # noqa: E402
    JsonProcessError,
    canonical_json,
    decode_json_object,
    run_json_process,
)

from artifacts.git.git_repository import content_sha256, run_git  # noqa: E402

EVOLVER = ROOT / "apps" / "evolution_driver" / "evolver.py"
PROPOSER = ROOT / "connectors" / "fixed" / "pi" / "git_proposer.py"
ADAPTER = HERE / "git_candidate_adapter.py"
VALIDATE = HERE / "demo_validate.py"
BUILDER = HERE / "demo_model_builder.py"
EXECUTOR = HERE / "demo_executor.py"
EVALUATOR = HERE / "demo_evaluator.py"


class DemoError(RuntimeError):
    """Raised when the Git artifact demonstration cannot complete."""


def _initialize_repository(root: Path) -> tuple[Path, dict[str, object]]:
    seed = root / "seed"
    remote = root / "candidate.git"
    seed.mkdir()
    run_git(["init", "--quiet"], cwd=seed)
    (seed / "adapter.py").write_text('ANSWER = "BASELINE"\n', encoding="utf-8")
    run_git(["add", "adapter.py"], cwd=seed)
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_AUTHOR_EMAIL": "metering-demo@example.invalid",
        "GIT_AUTHOR_NAME": "Metering Demo",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_EMAIL": "metering-demo@example.invalid",
        "GIT_COMMITTER_NAME": "Metering Demo",
    }
    commit = run_git(
        ["commit-tree", run_git(["write-tree"], cwd=seed).strip()],
        cwd=seed,
        input_text="Seed candidate\n",
        environment=environment,
    ).strip()
    run_git(["update-ref", "refs/heads/main", commit], cwd=seed)
    run_git(["init", "--quiet", "--bare", str(remote)])
    run_git(["remote", "add", "origin", str(remote)], cwd=seed)
    run_git(["push", "--quiet", "origin", "main:refs/heads/main"], cwd=seed)
    tree = run_git(["rev-parse", f"{commit}^{{tree}}"], cwd=seed).strip()
    artifact = decode_agent_artifact(
        {
            "artifact_schema": GIT_ARTIFACT_SCHEMA,
            "commit": commit,
            "content_sha256": content_sha256(seed, commit),
            "entrypoint": "adapter.py",
            "git_tree": tree,
            "outputs": [],
            "repository": str(remote),
        }
    )
    return remote, artifact


def _request(parent: dict[str, object]) -> dict[str, object]:
    return {
        "generation": {
            "evaluation": "git-artifact/live-demo-v1",
            "evaluator": {
                "command": [sys.executable, str(EVALUATOR)],
                "timeout_seconds": 30,
            },
            "runner": {
                "command": [sys.executable, str(ADAPTER)],
                "timeout_seconds": 60,
            },
            "selection_policy": {
                "minimum_pass_improvement": 1,
                "reject_safety_regression": True,
                "type": "task-pass-count-v1",
            },
            "tasks": [
                {
                    "case_id": "git-live-demo",
                    "input": {"environment": "demo-v1"},
                }
            ],
        },
        "initial_parent_artifact": parent,
        "limits": {
            "max_consecutive_rejections": 1,
            "max_generations": 1,
            "max_wall_seconds": 1200,
        },
        "proposal": {
            "command": [sys.executable, str(PROPOSER)],
            "context": {
                "objective": (
                    'Edit only adapter.py so it contains exactly ANSWER = "ADAPTED".'
                )
            },
            "timeout_seconds": 600,
        },
        "schema_version": 1,
    }


def run_demo(root: Path) -> dict[str, object]:
    if root.exists():
        raise DemoError(f"demo root must not exist: {root}")
    for name in ("PI_PROVIDER", "PI_MODEL", "PI_REASONING_LEVEL"):
        if not os.environ.get(name):
            raise DemoError(f"{name} must pin the live Pi configuration")
    root.mkdir(parents=True)
    remote, parent = _initialize_repository(root)
    os.environ.update(
        {
            "METERING_DEMO_ARTIFACT_STORE": str(root / "model-store"),
            "METERING_GIT_ALLOWED_PATHS_JSON": canonical_json(["adapter.py"]),
            "METERING_GIT_BUILD_COMMAND": canonical_json(
                [sys.executable, str(BUILDER)]
            ),
            "METERING_GIT_BUILD_TIMEOUT": "300",
            "METERING_GIT_EXECUTOR_COMMAND": canonical_json(
                [sys.executable, str(EXECUTOR)]
            ),
            "METERING_GIT_EXECUTOR_TIMEOUT": "60",
            "METERING_GIT_REF_PREFIX": "refs/heads/evolution/live-demo",
            "METERING_GIT_REPOSITORY": str(remote),
            "METERING_GIT_VALIDATE_COMMAND": canonical_json(
                [sys.executable, str(VALIDATE)]
            ),
            "METERING_GIT_VALIDATE_TIMEOUT": "60",
        }
    )
    state = root / "evolution.jsonl"
    try:
        source = run_json_process(
            [sys.executable, str(EVOLVER), "--state", str(state)],
            _request(parent),
            cwd=ROOT,
            timeout_seconds=900,
        )
    except JsonProcessError as exc:
        detail = exc.stderr.strip() or exc.detail or exc.kind
        raise DemoError(detail) from exc
    summary = decode_json_object(source, DemoError)
    records = [
        decode_json_object(line, DemoError)
        for line in state.read_text(encoding="utf-8").splitlines()
    ]
    if len(records) != 2:
        raise DemoError("demo did not record exactly one generation")
    result = records[1]["controller_result"]
    if type(result) is not dict:
        raise DemoError("demo generation omitted its Controller result")
    selection = result.get("selection")
    if type(selection) is not dict or selection.get("decision") != "promote_challenger":
        raise DemoError("Git challenger was not promoted")
    return {
        "driver_summary": summary,
        "model_store": str(root / "model-store"),
        "repository": str(remote),
        "schema": "git-artifact-live-demo-v1",
        "selection": result["selection"],
        "state": str(state),
    }


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2 or arguments[0] != "--root":
        print("usage: demo.py --root NEW_DIRECTORY", file=sys.stderr)
        return 2
    try:
        result = run_demo(Path(arguments[1]).expanduser().absolute())
    except (DemoError, OSError, TypeError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
