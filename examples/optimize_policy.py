"""Iterate over tunable policy configurations using Metering as the feedback loop.

This is a minimal measurement-in-the-loop optimizer.  Where
``run_suite.py`` measures one fixed policy, this script treats Metering's
suite readings as the fitness signal for a hill-climbing search over a small
parameterized policy family:

    propose a configuration
        -> run the full eight-state suite through run_hidden_fault
        -> read correctness, excess_observations, and total_actions
        -> keep the champion, mutate one knob, repeat
        -> stop at a local optimum

The policy under search is ``TunablePolicy`` with three knobs:

- ``strategy``: ``balanced`` (most even split), ``first`` (first informative
  catalogue test), or ``singleton`` (check one candidate at a time).
- ``redundant_repeats``: how many extra times each diagnostic test is
  re-asked after its outcome is already known.  Re-asking a used test is a
  valid action, so this is pure waste that the information meter should
  expose as excess observations, not a protocol failure.
- ``extra_verifications``: extra ``Verify()`` calls before finishing.  These
  do not touch ``excess_observations`` at all; only the raw resource column
  (``total_actions``) should move.  The two knobs exist to show that the
  feedback loop reads the meters separately, the way the reports do.

The fitness ordering is lexicographic, not an invented weighted score:

1. all eight runs must succeed (the correctness gate),
2. fewer ``excess_observations`` wins,
3. fewer ``total_actions`` breaks ties.

The search starts from the deliberately worst configuration, so a successful
run demonstrates the loop recovering the known optimum: balanced search with
no redundancy, i.e. ``excess_observations == 0``.

The default action budget is raised to 48 so that wasteful configurations
still finish.  That keeps the feedback in the meters, where it belongs: a
tight budget would mask the information readings with budget exhaustion
instead of letting the loop see the waste it is supposed to optimize away.

Usage, from the repository root:

    uv run python examples/optimize_policy.py
    uv run python examples/optimize_policy.py --run-parent runs/my-search

Every evaluation's run artifacts are kept under the run parent, so any
measurement the loop acted on can be re-verified offline afterwards:

    uv run python -m metering report runs/optimize-*/eval-00/fault-3

The script exits 0 only when the champion solves all eight states with zero
excess observations, i.e. when the feedback loop recovered the known
optimum for this world.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from metering import (
    Diagnose,
    DiagnosticObservation,
    Finish,
    HiddenFaultSpec,
    Observation,
    PolicyError,
    PublicInstance,
    Repair,
    RepairObservation,
    VerificationObservation,
    Verify,
    aggregate_reports,
    remaining_candidates,
    run_hidden_fault,
)

# The discrete search space.  Every value is JSON, because the configuration
# is declared verbatim in the policy descriptor and recorded in each manifest.
KNOBS: dict[str, tuple[Any, ...]] = {
    "strategy": ("balanced", "first", "singleton"),
    "redundant_repeats": (0, 1, 2),
    "extra_verifications": (0, 1),
}

# Deliberately worst starting point: the loop has to climb out of it.
START = {"strategy": "singleton", "redundant_repeats": 2, "extra_verifications": 1}

DEFAULT_SEARCH_BUDGET = 48
MAX_ROUNDS = 10


class TunablePolicy:
    """A harness-boundary policy whose diagnostic habits are config knobs."""

    name = "tunable-split"
    version = "1"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "configuration": self.config,
            "seed_policy": {"kind": "none"},
        }

    def next_action(
        self, instance: PublicInstance, observations: Sequence[Observation]
    ) -> Diagnose | Repair | Verify | Finish:
        # After a repair: verify once, plus any configured extra verifications,
        # then finish.  Verification feedback is content-free, so extra calls
        # buy nothing; only the resource meter sees them.
        last_repair = -1
        verifications_after = 0
        for index, observation in enumerate(observations):
            if isinstance(observation, RepairObservation):
                last_repair = index
                verifications_after = 0
            elif isinstance(observation, VerificationObservation) and index > last_repair:
                verifications_after += 1
        if last_repair >= 0:
            if verifications_after >= 1 + self.config["extra_verifications"]:
                return Finish()
            return Verify()

        candidates = remaining_candidates(instance, observations)
        if len(candidates) == 1:
            return Repair(candidates[0])

        candidate_set = set(candidates)
        used = [
            observation.test_id
            for observation in observations
            if isinstance(observation, DiagnosticObservation)
        ]
        informative: list[tuple[int, str, tuple[str, ...], int]] = []
        for catalogue_index, test in enumerate(instance.diagnostic_tests):
            if test.test_id in used:
                continue
            positive_count = len(candidate_set.intersection(test.positive_fault_ids))
            if 0 < positive_count < len(candidate_set):
                informative.append(
                    (catalogue_index, test.test_id, test.positive_fault_ids, positive_count)
                )
        if not informative:
            raise PolicyError("no unused catalogue test can separate the candidates")

        # Redundant repeats: re-ask the most recently used test a configured
        # number of times.  The outcome is already known, so each repeat costs
        # one diagnostic observation and removes zero bits.
        repeats = self.config["redundant_repeats"]
        if repeats and used:
            trailing = 0
            for test_id in reversed(used):
                if test_id != used[-1]:
                    break
                trailing += 1
            if trailing <= repeats:
                return Diagnose(used[-1])

        strategy = self.config["strategy"]
        if strategy == "first":
            return Diagnose(informative[0][1])
        if strategy == "singleton":
            # Check the earliest remaining candidate directly, in the spirit of
            # the sequential reference policy; fall back to a balanced split
            # when no singleton test is available.
            for candidate in candidates:
                for _, test_id, positive_fault_ids, positive_count in informative:
                    if positive_count == 1 and candidate in positive_fault_ids:
                        return Diagnose(test_id)
        # "balanced" and the singleton fallback: most even remaining split,
        # first catalogue entry wins ties.
        _, test_id, _, _ = max(
            informative,
            key=lambda item: (
                min(item[3], len(candidates) - item[3]),
                -item[0],
            ),
        )
        return Diagnose(test_id)


def fitness(evaluation: dict[str, Any]) -> tuple[bool, float, int]:
    """Lexicographic fitness: correctness gate, then waste, then total cost.

    This is an ordering for the search loop, not a combined score; the three
    readings stay in their separate columns inside every report.
    """

    excess = evaluation["excess_observations"]
    return (
        evaluation["successful_runs"] == evaluation["run_count"],
        -(excess if excess is not None else float("inf")),
        -evaluation["total_actions"],
    )


def neighbors(config: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every configuration that differs from ``config`` in one knob."""

    for knob, values in KNOBS.items():
        for value in values:
            if value != config[knob]:
                yield {**config, knob: value}


def evaluate(
    config: dict[str, Any], eval_index: int, parent: Path, action_budget: int
) -> dict[str, Any]:
    """Run one configuration across all eight hidden states and aggregate."""

    run_parent = parent / f"eval-{eval_index:02d}"
    results = [
        run_hidden_fault(
            TunablePolicy(config),
            hidden_fault_id=fault_id,
            run_dir=run_parent / fault_id,
            action_budget=action_budget,
        )
        for fault_id in HiddenFaultSpec.default().fault_ids
    ]
    suite = aggregate_reports([result.report for result in results])
    information = suite["diagnostic_information"]
    return {
        "eval_index": eval_index,
        "config": dict(config),
        "run_parent": str(run_parent),
        "successful_runs": suite["successful_runs"],
        "run_count": suite["run_count"],
        "excess_observations": information["excess_observations"],
        "bits_per_diagnostic_observation": information[
            "bits_per_diagnostic_observation"
        ],
        "total_actions": suite["resources"]["total_actions"],
    }


def format_evaluation(evaluation: dict[str, Any]) -> str:
    excess = evaluation["excess_observations"]
    bits = evaluation["bits_per_diagnostic_observation"]
    config = " ".join(f"{key}={value}" for key, value in evaluation["config"].items())
    return (
        f"eval {evaluation['eval_index']:02d}  {config:<62} "
        f"success={evaluation['successful_runs']}/{evaluation['run_count']}  "
        f"excess={excess if excess is not None else 'n/a':>4}  "
        f"bits/obs={bits if bits is not None else float('nan'):.3f}  "
        f"total_actions={evaluation['total_actions']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hill-climb a tunable policy with Metering readings as feedback."
    )
    parser.add_argument(
        "--run-parent",
        type=Path,
        default=None,
        help="parent directory for all evaluation artifacts "
        "(default: runs/optimize-<timestamp>)",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_SEARCH_BUDGET,
        help=f"action budget per run (default: {DEFAULT_SEARCH_BUDGET}; "
        "headroom lets waste show up as excess observations "
        "instead of budget exhaustion)",
    )
    args = parser.parse_args(argv)

    parent = args.run_parent
    if parent is None:
        parent = Path("runs") / ("optimize-" + time.strftime("%Y%m%d-%H%M%S"))
    if parent.exists() and any(parent.iterdir()):
        print(
            f"run parent {parent} is not empty; pass a fresh directory",
            file=sys.stderr,
        )
        return 2

    history: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any]] = {}

    def measured(config: dict[str, Any]) -> dict[str, Any]:
        key = json.dumps(config, sort_keys=True)
        if key not in cache:
            evaluation = evaluate(config, len(history), parent, args.budget)
            cache[key] = evaluation
            history.append(evaluation)
            print(format_evaluation(evaluation))
        return cache[key]

    champion = measured(START)
    for _ in range(MAX_ROUNDS):
        challenger = max(
            (measured(config) for config in neighbors(champion["config"])),
            key=lambda evaluation: fitness(evaluation),
            default=None,
        )
        if challenger is None or fitness(challenger) <= fitness(champion):
            break
        champion = challenger
        print(f"new champion: {json.dumps(champion['config'], sort_keys=True)}")

    log_path = parent / "optimization_log.json"
    log_path.write_text(
        json.dumps({"evaluations": history, "champion": champion}, indent=2, sort_keys=True)
        + "\n"
    )

    print()
    print(f"evaluations: {len(history)} (artifacts kept under {parent})")
    print(f"champion:    {json.dumps(champion['config'], sort_keys=True)}")
    print(f"             success={champion['successful_runs']}/{champion['run_count']} "
          f"excess={champion['excess_observations']} "
          f"total_actions={champion['total_actions']}")
    print(f"log:         {log_path}")

    solved = champion["successful_runs"] == champion["run_count"]
    optimal = solved and champion["excess_observations"] == 0
    return 0 if optimal else 1


if __name__ == "__main__":
    raise SystemExit(main())
