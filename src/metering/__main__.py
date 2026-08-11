"""Command-line entry point for Metering v0."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from .calibration import (
    DEFAULT_CALIBRATION_SEED,
    CalibrationFailure,
    run_calibration,
)
from .report import ReportError, regenerate_report
from .runner import DEFAULT_ACTION_BUDGET
from .trace import TraceError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m metering",
        description="Run or replay the controlled Metering v0 experiment.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    calibrate = commands.add_parser(
        "calibrate", help="run the complete deterministic v0 calibration suite"
    )
    calibrate.add_argument(
        "--output",
        type=Path,
        default=Path("runs/calibration-v0"),
        help="new or empty calibration directory (default: runs/calibration-v0)",
    )
    calibrate.add_argument(
        "--seed", type=int, default=DEFAULT_CALIBRATION_SEED, help="random baseline seed"
    )
    calibrate.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_ACTION_BUDGET,
        help="action budget for reference runs",
    )
    calibrate.add_argument(
        "--force",
        action="store_true",
        help="replace a non-empty output directory",
    )

    replay = commands.add_parser(
        "report", help="regenerate one report.json from saved raw artifacts"
    )
    replay.add_argument("run_dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "calibrate":
        try:
            result = run_calibration(
                arguments.output,
                seed=arguments.seed,
                action_budget=arguments.budget,
                force=arguments.force,
            )
        except CalibrationFailure as exc:
            print(f"calibration failed: {exc}", file=sys.stderr)
            return 1
        aggregates = result.summary["aggregates"]
        print(f"calibration passed: {result.output_dir}")
        print(
            "balanced diagnostics: "
            f"{aggregates['balanced']['diagnostic_observations_total']}; "
            "sequential diagnostics: "
            f"{aggregates['sequential']['diagnostic_observations_total']}"
        )
        return 0

    if arguments.command == "report":
        try:
            report = regenerate_report(arguments.run_dir)
        except (ReportError, TraceError, OSError, ValueError) as exc:
            print(f"report regeneration failed: {exc}", file=sys.stderr)
            return 1
        print(
            f"regenerated {arguments.run_dir / 'report.json'} "
            f"for run {report['run_id']}"
        )
        return 0

    return 2  # argparse makes this unreachable


if __name__ == "__main__":
    raise SystemExit(main())
