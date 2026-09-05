#!/usr/bin/env python3
"""Compatibility CLI and status projection for solution evolution."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import write_document  # noqa: E402
from apps.coding_agent.experiment_config import (  # noqa: E402
    SolutionExperimentError as SolutionExperimentError,
)
from apps.coding_agent.experiment_replay import verify_experiment as verify_experiment  # noqa: E402
from apps.coding_agent.experiment_runtime import (  # noqa: E402
    continue_experiment as continue_experiment,
    run_experiment as run_experiment,
)
from apps.coding_agent.final_assay import CodingFinalError  # noqa: E402
from apps.coding_agent.harness_workspace_editor import CodingMutationError  # noqa: E402
from apps.coding_agent.process_tracker import (  # noqa: E402
    ProcessTrackerError,
    load_process_status,
    process_document,
)
from apps.coding_agent.protocol import CodingTaskError  # noqa: E402
from apps.harness.protocol import HarnessProtocolError  # noqa: E402
from apps.harness.runtime_manifest import RuntimeManifestError  # noqa: E402
from apps.population_driver.population_driver_protocol import PopulationDriverError  # noqa: E402
from artifacts.git.git_repository import GitCandidateError  # noqa: E402


def solution_process_status(root: Path) -> dict[str, object]:
    root = root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise SolutionExperimentError(f"experiment root is absent or unsafe: {root}")
    status = load_process_status(root, expected_run_kind="solution")
    if status is not None:
        return status
    if (root / "selected-solution.json").is_file():
        return process_document(6, "solution")
    if (root / "protected-final.json").is_file():
        return process_document(5, "solution")
    if (root / "state" / "driver.jsonl").is_file():
        return process_document(4, "solution")
    raise SolutionExperimentError("coding solution process has not started")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(arguments) == 2 and arguments[0] == "verify":
            result = verify_experiment(Path(arguments[1]))
        elif len(arguments) == 2 and arguments[0] == "status":
            result = solution_process_status(Path(arguments[1]))
        elif len(arguments) == 2 and arguments[0] == "resume":
            result = continue_experiment(Path(arguments[1]))
        elif len(arguments) == 3 and arguments[0] == "retry":
            result = continue_experiment(Path(arguments[1]), retry_reason=arguments[2])
        elif len(arguments) == 5 and arguments[0] in {"fixture", "pi"}:
            result = run_experiment(
                arguments[0],
                Path(arguments[1]),
                Path(arguments[2]),
                Path(arguments[3]),
                Path(arguments[4]),
            )
        else:
            raise SolutionExperimentError(
                "usage: solution_experiment.py {fixture|pi} TASK.json NEW_ROOT "
                "RUNTIME.json SELECTED-HARNESS.json | status ROOT | resume ROOT | "
                "retry ROOT REASON | verify ROOT"
            )
    except (
        CodingFinalError,
        CodingMutationError,
        CodingTaskError,
        GitCandidateError,
        HarnessProtocolError,
        OSError,
        PopulationDriverError,
        ProcessTrackerError,
        RuntimeManifestError,
        SolutionExperimentError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    write_document(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
