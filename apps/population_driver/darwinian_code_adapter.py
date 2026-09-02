#!/usr/bin/env python3
"""Deterministic executable-Git adapters for the arithmetic evolution test.

The fixed proposer creates real descendant commits.  The runner checks out and
executes each immutable ``solver.py`` candidate.  This is a trusted test fixture,
not a sandbox for untrusted candidate code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from artifacts.git.git_repository import (  # noqa: E402
    clone_verified,
    content_sha256,
    run_git,
)

RESOURCE_NAMES = (
    "actions",
    "energy_millijoules",
    "gpu_milliseconds",
    "memory_bytes",
    "storage_bytes",
    "tokens",
    "wall_milliseconds",
)

OPERATORS = {
    1: "+",
    2: "*",
}


def _write(document: object) -> None:
    print(json.dumps(document, allow_nan=False, separators=(",", ":"), sort_keys=True))


def _solver_source(operator: str) -> str:
    return (
        "import json,sys\n"
        "request=json.load(sys.stdin)\n"
        f"answer=request['left'] {operator} request['right']\n"
        "print(json.dumps({'answer':answer},separators=(',',':'),sort_keys=True))\n"
    )


def _artifact(repository: Path, commit: str) -> dict[str, object]:
    return {
        "artifact_schema": "git-candidate-v1",
        "commit": commit,
        "content_sha256": content_sha256(repository, commit),
        "entrypoint": "solver.py",
        "git_tree": run_git(
            ["rev-parse", f"{commit}^{{tree}}"], cwd=repository
        ).strip(),
        "outputs": [],
        "repository": str(repository),
    }


def _proposal(request: dict[str, object]) -> dict[str, object]:
    parent = cast(dict[str, object], request["parent"])
    parent_artifact = cast(dict[str, object], parent["artifact"])
    context = cast(dict[str, object], request["context"])
    generation = int(context["generation"])
    operator = OPERATORS.get(generation)
    if operator is None:
        raise ValueError("arithmetic fixture supports exactly two generations")
    repository = Path(str(parent_artifact["repository"]))
    expected_repository = os.environ.get("METERING_GIT_REPOSITORY")
    if expected_repository != str(repository):
        raise ValueError("candidate repository is not the configured repository")

    with tempfile.TemporaryDirectory(prefix="metering-darwinian-proposal-") as raw:
        checkout = Path(raw) / "checkout"
        run_git(
            [
                "worktree",
                "add",
                "--quiet",
                "--detach",
                str(checkout),
                str(parent_artifact["commit"]),
            ],
            cwd=repository,
        )
        try:
            (checkout / "solver.py").write_text(
                _solver_source(operator), encoding="utf-8"
            )
            run_git(["add", "--", "solver.py"], cwd=checkout)
            environment = os.environ.copy()
            timestamp = f"2000-01-0{generation}T00:00:00+00:00"
            environment.update(
                {
                    "GIT_AUTHOR_DATE": timestamp,
                    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                    "GIT_AUTHOR_NAME": "Metering Fixture",
                    "GIT_COMMITTER_DATE": timestamp,
                    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                    "GIT_COMMITTER_NAME": "Metering Fixture",
                }
            )
            run_git(
                [
                    "commit",
                    "--quiet",
                    "--no-gpg-sign",
                    "-m",
                    f"generation {generation}",
                ],
                cwd=checkout,
                environment=environment,
            )
            commit = run_git(["rev-parse", "HEAD"], cwd=checkout).strip()
            run_git(
                ["update-ref", f"refs/heads/metering-generation-{generation}", commit],
                cwd=repository,
            )
        finally:
            run_git(["worktree", "remove", "--force", str(checkout)], cwd=repository)
    return {
        "challenger_artifact": _artifact(repository, commit),
        "reason": f"generation {generation}: replace the arithmetic expression",
    }


def _runner(request: dict[str, object]) -> dict[str, object]:
    candidate = cast(dict[str, object], request["candidate"])
    artifact = cast(dict[str, object], candidate["artifact"])
    task = cast(dict[str, object], request["task"])
    task_input = cast(dict[str, object], task["input"])
    with tempfile.TemporaryDirectory(prefix="metering-darwinian-runner-") as raw:
        checkout = Path(raw) / "candidate"
        clone_verified(artifact, checkout)
        completed = subprocess.run(
            [sys.executable, str(checkout / str(artifact["entrypoint"]))],
            input=json.dumps(task_input, separators=(",", ":"), sort_keys=True),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or "candidate execution failed")
    submission = json.loads(completed.stdout)
    if type(submission) is not dict:
        raise ValueError("candidate output must be a JSON object")
    submission = {
        **submission,
        "left": task_input["left"],
        "right": task_input["right"],
    }
    return {
        "forecast": {
            "outcomes": [
                {"outcome": "fail", "probability": 0.5},
                {"outcome": "pass", "probability": 0.5},
            ]
        },
        "submission": submission,
    }


def _evaluator(request: dict[str, object]) -> dict[str, object]:
    results = []
    for item in cast(list[dict[str, object]], request["submissions"]):
        submission = cast(dict[str, object], item["submission"])
        expected = int(submission["left"]) + int(submission["right"])
        answer = submission.get("answer")
        passed = type(answer) is int and answer == expected
        results.append(
            {
                "candidate_id": item["candidate_id"],
                "evidence": {"answer": answer, "expected": expected},
                "outcome": "pass" if passed else "fail",
                "passed": passed,
                "safety_passed": True,
            }
        )
    return {"results": results}


def _evidence(request: dict[str, object]) -> dict[str, object]:
    controller_result = cast(dict[str, object], request["controller_result"])
    candidates = []
    for report_name in ("incumbent_report", "challenger_report"):
        report = cast(dict[str, object], controller_result[report_name])
        summary = cast(dict[str, object], report["task_summary"])
        passed = int(summary["passed_count"])
        count = int(summary["case_count"])
        rate = passed / count
        candidates.append(
            {
                "behavior_distribution": [1.0 - rate, rate],
                "candidate_id": report["candidate"],
                "cost": {name: 0 for name in RESOURCE_NAMES},
                "protected_passed": True,
                "seed": {"round": request["round"]},
            }
        )
    return {"candidates": candidates, "protocol_version": 1}


def main() -> int:
    actions = {
        "evaluator": _evaluator,
        "evidence": _evidence,
        "proposal": _proposal,
        "runner": _runner,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        print(
            "usage: darwinian_code_adapter.py {proposal|runner|evaluator|evidence}",
            file=sys.stderr,
        )
        return 2
    try:
        request = json.load(sys.stdin)
        if type(request) is not dict:
            raise ValueError("request must be a JSON object")
        result = actions[sys.argv[1]](request)
    except Exception as exc:  # subprocess boundary reports one stable error channel
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    _write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
