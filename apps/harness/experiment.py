#!/usr/bin/env python3
"""Compatibility CLI and status projection for the fixed harness experiment."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import decode_json_object, write_document  # noqa: E402
from apps.coding_agent.process_tracker import (  # noqa: E402
    ProcessTrackerError,
    load_process_status,
    process_document,
)
from apps.harness.experiment_config import ExperimentError as ExperimentError  # noqa: E402
from apps.harness.experiment_replay import verify_experiment as verify_experiment  # noqa: E402
from apps.harness.experiment_runtime import (  # noqa: E402
    continue_experiment as continue_experiment,
    run_experiment as run_experiment,
)
from apps.harness.final_assay import FinalAssayError  # noqa: E402
from apps.harness.protocol import HarnessProtocolError  # noqa: E402
from apps.harness.receipts import HarnessReceiptError  # noqa: E402
from apps.harness.runtime_manifest import RuntimeManifestError  # noqa: E402
from apps.population_driver.population_driver_protocol import PopulationDriverError  # noqa: E402
from artifacts.git.git_repository import GitCandidateError  # noqa: E402


def harness_process_status(root: Path) -> dict[str, object]:
    root = root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise ExperimentError(f"experiment root is absent or unsafe: {root}")
    status = load_process_status(root, expected_run_kind="harness")
    if status is not None:
        return status
    if (root / "selected-harness.json").is_file():
        return process_document(3, "harness")
    driver_path = root / "state" / "driver.jsonl"
    if driver_path.is_file():
        lines = driver_path.read_text(encoding="ascii").splitlines()
        header = decode_json_object(lines[0] if lines else "", ExperimentError)
        configuration = header.get("configuration")
        generation = (
            configuration.get("generation") if type(configuration) is dict else None
        )
        if (
            type(generation) is dict
            and generation.get("evaluation")
            == "evolutionary-harness/development-coding-agent-v1"
        ):
            return process_document(2, "harness")
    raise ExperimentError("coding harness process has not started")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(arguments) == 2 and arguments[0] == "verify":
            result = verify_experiment(Path(arguments[1]))
        elif len(arguments) == 2 and arguments[0] == "status":
            result = harness_process_status(Path(arguments[1]))
        elif len(arguments) == 2 and arguments[0] == "resume":
            result = continue_experiment(Path(arguments[1]))
        elif len(arguments) == 3 and arguments[0] == "retry":
            result = continue_experiment(Path(arguments[1]), retry_reason=arguments[2])
        elif len(arguments) == 2 and arguments[0] in {"fixture", "coding-fixture"}:
            result = run_experiment(
                "fixture",
                Path(arguments[1]).absolute(),
                None,
                assay=(
                    "coding-agent-v1"
                    if arguments[0] == "coding-fixture"
                    else "arithmetic-v1"
                ),
            )
        elif len(arguments) == 3 and arguments[0] in {
            "pi",
            "prime-agent",
            "coding-pi",
            "coding-prime-agent",
        }:
            selected_agent = arguments[0].removeprefix("coding-")
            result = run_experiment(
                selected_agent,
                Path(arguments[1]).absolute(),
                Path(arguments[2]),
                assay=(
                    "coding-agent-v1"
                    if arguments[0].startswith("coding-")
                    else "arithmetic-v1"
                ),
            )
        else:
            raise ExperimentError(
                "usage: experiment.py {fixture|coding-fixture} NEW_ROOT | "
                "{pi|prime-agent|coding-pi|coding-prime-agent} NEW_ROOT "
                "RUNTIME.json | status ROOT | resume ROOT | retry ROOT REASON | "
                "verify ROOT"
            )
    except (
        ExperimentError,
        FinalAssayError,
        GitCandidateError,
        HarnessProtocolError,
        HarnessReceiptError,
        OSError,
        ProcessTrackerError,
        PopulationDriverError,
        RuntimeManifestError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    write_document(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
