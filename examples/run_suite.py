"""Run one policy across every hidden fault and print the suite readings.

This is the committed form of the driver loop that the usage guide builds up
step by step: one fresh run per hidden fault, followed by
``aggregate_reports`` over the per-run reports.  Point it at your own policy
and you have a complete suite measurement of a custom harness, including the
suite-level ``excess_observations`` reading.

Usage, from the repository root:

    uv run python examples/run_suite.py                     # balanced reference
    uv run python examples/run_suite.py sequential          # reference by name
    uv run python examples/run_suite.py my_policy:MyPolicy  # your own policy
    uv run python examples/run_suite.py balanced --json     # machine readable

A ``module:Class`` argument is imported with the current working directory on
the import path, so a ``my_policy.py`` beside your shell prompt works
directly.  The class must be constructible with no arguments, and the driver
constructs a fresh instance for every hidden state so that state kept on a
policy object cannot leak between the eight runs.  To pass configuration,
edit ``load_policy_factory`` below and return your own zero-argument factory.

The script exits 0 only when every run in the suite succeeds, so it can gate
continuous-integration checks for a harness.  The run directories are always
printed, and each one can be re-verified offline afterwards:

    uv run python -m metering report <run_dir>
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from metering import (
    BalancedSearchPolicy,
    DEFAULT_ACTION_BUDGET,
    HarnessPolicy,
    HiddenFaultSpec,
    PolicyError,
    RunnerError,
    RunResult,
    SeededRandomSearchPolicy,
    SequentialSearchPolicy,
    aggregate_reports,
    run_hidden_fault,
)

REFERENCE_POLICIES = {
    "balanced": BalancedSearchPolicy,
    "sequential": SequentialSearchPolicy,
    "seeded-random": SeededRandomSearchPolicy,
}


def load_policy_factory(spec: str) -> Callable[[], HarnessPolicy]:
    """Return a zero-argument policy factory for a name or ``module:Class`` spec."""

    if spec in REFERENCE_POLICIES:
        return REFERENCE_POLICIES[spec]
    if ":" not in spec:
        names = ", ".join(sorted(REFERENCE_POLICIES))
        raise ValueError(f"expected one of {names}, or module:ClassName")
    module_name, _, class_name = spec.partition(":")
    sys.path.insert(0, os.getcwd())
    module = importlib.import_module(module_name)
    policy_class = getattr(module, class_name)
    # To hardcode a configured policy instead, return your own zero-argument
    # factory here, for example ``lambda: MyPolicy(depth=2)``.
    return policy_class


def run_suite(
    policy_factory: Callable[[], HarnessPolicy], parent: Path, action_budget: int
) -> list[RunResult]:
    """Run one fresh policy per hidden fault, each into a fresh directory.

    A new instance per run keeps the eight runs independent.  Reusing one
    object would leak instance state across hidden states, making an honest
    stateful policy fail every run after its first and letting a policy that
    counts invocations exploit the fixed fault order.
    """

    results: list[RunResult] = []
    for fault_id in HiddenFaultSpec.default().fault_ids:
        try:
            policy = policy_factory()
        except Exception as error:  # constructing user code can raise anything
            raise PolicyError(f"could not construct policy: {error}") from error
        results.append(
            run_hidden_fault(
                policy,
                hidden_fault_id=fault_id,
                run_dir=parent / fault_id,
                action_budget=action_budget,
            )
        )
    return results


def per_run_row(fault_id: str, result: RunResult) -> dict[str, Any]:
    report = result.report
    return {
        "fault_id": fault_id,
        "run_dir": str(result.run_dir),
        "overall_task_success": report["correctness"]["overall_task_success"],
        "termination_reason": report["termination_reason"],
        "diagnostic_observations": report["resources"]["diagnostic_observations"],
        "uncertainty_removed_bits": report["diagnostic_information"][
            "total_uncertainty_removed_bits"
        ],
    }


def print_human(rows: list[dict[str, Any]], suite: dict[str, Any]) -> None:
    header = f"{'fault':<9} {'success':<8} {'termination':<18} {'diagnostics':>11} {'bits':>7}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['fault_id']:<9} "
            f"{str(row['overall_task_success']):<8} "
            f"{row['termination_reason']:<18} "
            f"{row['diagnostic_observations']:>11} "
            f"{row['uncertainty_removed_bits']:>7.3f}"
        )

    information = suite["diagnostic_information"]
    bits_per_observation = information["bits_per_diagnostic_observation"]
    excess = information["excess_observations"]
    print()
    print(f"successful runs:               {suite['successful_runs']} / {suite['run_count']}")
    print(f"total diagnostic observations: {suite['resources']['diagnostic_observations']}")
    print(f"total bits removed:            {information['total_uncertainty_removed_bits']:.3f}")
    print(
        "bits per observation:          "
        + (f"{bits_per_observation:.4f}" if bits_per_observation is not None else "not applicable")
    )
    print(
        "excess observations:           "
        + (
            str(excess)
            if excess is not None
            else "not applicable (needs one successful run per hidden state)"
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a policy across all hidden faults and aggregate the reports."
    )
    parser.add_argument(
        "policy",
        nargs="?",
        default="balanced",
        help="reference policy name (balanced, sequential, seeded-random) "
        "or module:ClassName for your own",
    )
    parser.add_argument(
        "--run-parent",
        type=Path,
        default=None,
        help="parent directory for the run artifacts "
        "(default: runs/suite-<timestamp>)",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_ACTION_BUDGET,
        help=f"action budget for each run (default: {DEFAULT_ACTION_BUDGET})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print one JSON document instead of the human-readable tables",
    )
    args = parser.parse_args(argv)

    parent = args.run_parent
    if parent is None:
        parent = Path("runs") / ("suite-" + time.strftime("%Y%m%d-%H%M%S"))
    if parent.exists() and not parent.is_dir():
        print(f"run parent {parent} exists and is not a directory", file=sys.stderr)
        return 2
    if parent.is_dir() and any(parent.iterdir()):
        print(
            f"run parent {parent} is not empty; each run owns a fresh directory,"
            " so pass a new --run-parent or remove the old one deliberately",
            file=sys.stderr,
        )
        return 2

    try:
        policy_factory = load_policy_factory(args.policy)
    except Exception as error:  # importing user code can raise anything
        print(f"could not load policy {args.policy!r}: {error}", file=sys.stderr)
        return 2

    try:
        results = run_suite(policy_factory, parent, args.budget)
    except (RunnerError, PolicyError) as error:
        # These mean the policy could not be constructed or its descriptor,
        # world, or configuration was rejected before or between runs.  A
        # crash inside next_action() does not raise; it terminates that run
        # and appears in its report as harness_crash.
        print(f"suite rejected: {error}", file=sys.stderr)
        return 1

    fault_ids = HiddenFaultSpec.default().fault_ids
    rows = [
        per_run_row(fault_id, result)
        for fault_id, result in zip(fault_ids, results, strict=True)
    ]
    suite = aggregate_reports([result.report for result in results])

    if args.as_json:
        document = {
            # The descriptor as validated and recorded for the first run; all
            # runs share it because they come from the same factory.
            "policy": dict(results[0].manifest["policy"]),
            "run_parent": str(parent),
            "per_run": rows,
            "suite": suite,
        }
        print(json.dumps(document, indent=2, sort_keys=True))
    else:
        print(f"run artifacts: {parent}")
        print()
        print_human(rows, suite)

    return 0 if suite["successful_runs"] == suite["run_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
