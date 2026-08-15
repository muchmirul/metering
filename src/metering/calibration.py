"""Complete deterministic Metering calibration suite.

Calibration is how the instrument checks itself before anyone trusts a reading.
It runs every declared hidden state against every reference policy, rebuilds
each report from the saved files, and then asserts the readings it already
knows the correct answers to.

The headline check is the contrast between the two careful and wasteful search
policies.  Balanced search must spend 24 diagnostic observations across the
eight states and sequential search must spend 35, and both must be measured as
correct.  If the meters cannot separate those two policies in the expected
direction, the meters are not ready for a policy whose behavior nobody knows in
advance.

The suite also exercises the four ways a run can end, because a measurement
path that only works when everything goes well is not a measurement path.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import shutil
from typing import Any, Callable, Mapping, Sequence

from .events import Action, Diagnose, Finish, Observation
from .hidden_fault import HiddenFaultSpec, PublicInstance
from .policies import (
    BalancedSearchPolicy,
    HarnessPolicy,
    SeededRandomSearchPolicy,
    SequentialSearchPolicy,
)
from .report import ReportError, aggregate_reports, build_report, regenerate_report
from .runner import DEFAULT_ACTION_BUDGET, RunResult, run_hidden_fault
from .schema import (
    CALIBRATION_SCHEMA_VERSION,
    EVENT_INTERACTION,
    EVENT_PROTOCOL_ERROR,
    EVENT_TERMINATION,
    TERMINATION_BUDGET_EXHAUSTED,
    TERMINATION_HARNESS_CRASH,
    TERMINATION_INVALID_ACTION,
    TERMINATION_NORMAL,
)
from .trace import interaction_signature, write_json_atomic

DEFAULT_CALIBRATION_SEED = 20260722
CALIBRATION_MARKER_NAME = ".metering-calibration"
CALIBRATION_MARKER_BYTES = (
    b'{"format":"metering-calibration-output","schema_version":1}\n'
)

# The expected readings.  Balanced search answers one bit per observation, so
# three observations identify any of the eight states.  Sequential search checks
# singletons in order and infers the eighth state after seven negatives.
EXPECTED_BALANCED_DIAGNOSTICS = [3] * 8
EXPECTED_DEFAULT_SEEDED_RANDOM_DIAGNOSTICS = [4, 4, 4, 1, 4, 4, 4, 3]
EXPECTED_SEQUENTIAL_DIAGNOSTICS = [1, 2, 3, 4, 5, 6, 7, 7]
EXPECTED_EXCESS_OBSERVATIONS = {
    "balanced": 0,
    "seeded_random": 4,
    "sequential": 11,
}
INITIAL_UNCERTAINTY_BITS = 3.0

# A reference policy needs at most seven diagnostics plus a repair, a
# verification, and a finish, so ten actions is the lowest honest budget.
MINIMUM_CALIBRATION_BUDGET = 10


class CalibrationFailure(RuntimeError):
    """Raised after one or more declared calibration checks fail."""

    def __init__(self, message: str, summary: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.summary = summary


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    output_dir: Path
    summary: Mapping[str, Any]


class _InvalidActionPolicy:
    """Ask for a test that is not in the public catalogue."""

    name = "calibration-invalid-action"
    version = "1"

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {},
            "seed_policy": {"kind": "none"},
        }

    def next_action(
        self, instance: PublicInstance, observations: Sequence[Observation]
    ) -> Action:
        return Diagnose("not-in-public-catalogue")


class _NeverFinishPolicy:
    """Repeat the first test forever, so only the budget can stop the run."""

    name = "calibration-never-finish"
    version = "1"

    def __init__(self) -> None:
        self.calls = 0

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {"repeats_first_test": True},
            "seed_policy": {"kind": "none"},
        }

    def next_action(
        self, instance: PublicInstance, observations: Sequence[Observation]
    ) -> Action:
        self.calls += 1
        return Diagnose(instance.diagnostic_tests[0].test_id)


class _CrashPolicy:
    """Raise an ordinary exception from the callback."""

    name = "calibration-crash"
    version = "1"

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {"raises_on_first_request": True},
            "seed_policy": {"kind": "none"},
        }

    def next_action(
        self, instance: PublicInstance, observations: Sequence[Observation]
    ) -> Action:
        raise RuntimeError("intentional calibration crash")


class _FinishAtBoundaryPolicy:
    """Finish with the very last budgeted action."""

    name = "calibration-finish-at-boundary"
    version = "1"

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.calls = 0

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "configuration": {"finish_on_action": self.budget},
            "seed_policy": {"kind": "none"},
        }

    def next_action(
        self, instance: PublicInstance, observations: Sequence[Observation]
    ) -> Action:
        self.calls += 1
        if self.calls == self.budget:
            return Finish()
        return Diagnose(instance.diagnostic_tests[0].test_id)


def _prepare_output(path: Path, force: bool) -> None:
    """Create the output directory, replacing only a directory Metering owns.

    A non-empty directory is never overwritten by default.  With ``force``, the
    directory is removed only when it carries Metering's own marker file, so a
    mistyped path cannot turn calibration into a recursive delete.
    """

    if type(force) is not bool:
        raise CalibrationFailure("force must be an exact bool")
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise CalibrationFailure(
                f"calibration output must be a real directory: {path}"
            )
        if any(path.iterdir()):
            if not force:
                raise CalibrationFailure(
                    f"calibration output is not empty: {path}; "
                    "use force=True to replace it"
                )
            marker = path / CALIBRATION_MARKER_NAME
            if (
                marker.is_symlink()
                or not marker.is_file()
                or marker.read_bytes() != CALIBRATION_MARKER_BYTES
            ):
                raise CalibrationFailure(
                    f"refusing to replace unmarked directory: {path}"
                )
            if path.resolve() in {Path("/").resolve(), Path.cwd().resolve()}:
                raise CalibrationFailure(
                    f"refusing to remove unsafe output path: {path}"
                )
            shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    (path / CALIBRATION_MARKER_NAME).write_bytes(CALIBRATION_MARKER_BYTES)


def _termination_reason(result: RunResult) -> str:
    value = result.report.get("termination_reason")
    return value if isinstance(value, str) else ""


def _diagnostics(results: Sequence[RunResult]) -> list[int]:
    return [
        int(result.report["resources"]["diagnostic_observations"])
        for result in results
    ]


def _information_removed(results: Sequence[RunResult]) -> list[float]:
    return [
        float(
            result.report["diagnostic_information"]["total_uncertainty_removed_bits"]
        )
        for result in results
    ]


def _suite_information(results: Sequence[RunResult]) -> Mapping[str, Any]:
    aggregate = aggregate_reports([result.report for result in results])
    return aggregate["diagnostic_information"]


def _kraft_sum(depths: Sequence[int]) -> float:
    """Return the Kraft sum for one complete reference decision tree."""

    return sum(2.0 ** -depth for depth in depths)


class _Suite:
    """Runs calibration runs and records the outcome of each declared check."""

    def __init__(self, output: Path, spec: HiddenFaultSpec, action_budget: int) -> None:
        self.output = output
        self.spec = spec
        self.action_budget = action_budget
        self.checks: dict[str, bool] = {}
        self.failures: list[dict[str, str]] = []
        self.regenerated_run_count = 0

    def check(self, name: str, condition: bool, detail: str) -> None:
        self.checks[name] = bool(condition)
        if not condition:
            self.failures.append({"check": name, "detail": detail})

    def run(
        self,
        relative: str,
        policy: HarnessPolicy,
        fault_id: str,
        *,
        run_id: str,
        budget: int | None = None,
    ) -> RunResult:
        """Execute one run, then delete and rebuild its report from disk.

        Rebuilding every run is the cheapest way to prove the two properties
        calibration cares about most.  The regenerated report must equal the
        original, and all three raw artifacts must remain byte-identical, which
        shows that meters read the record without touching it.
        """

        result = run_hidden_fault(
            policy,
            fault_id,
            self.output / relative,
            spec=self.spec,
            run_id=run_id,
            action_budget=budget or self.action_budget,
        )
        original_report = dict(result.report)
        raw_before = {
            "manifest": result.paths.manifest.read_bytes(),
            "events": result.paths.events.read_bytes(),
            "reference": result.paths.reference.read_bytes(),
        }
        result.paths.report.unlink()
        regenerated = regenerate_report(result.paths.run_dir)
        raw_after = {
            "manifest": result.paths.manifest.read_bytes(),
            "events": result.paths.events.read_bytes(),
            "reference": result.paths.reference.read_bytes(),
        }
        self.regenerated_run_count += 1
        self.check(
            f"report_regeneration:{relative}",
            regenerated == original_report,
            "regenerated report differs from the original",
        )
        self.check(
            f"trace_unchanged_by_meter:{relative}",
            raw_after["events"] == raw_before["events"],
            "offline report regeneration changed events.jsonl",
        )
        self.check(
            f"raw_artifacts_unchanged_by_meter:{relative}",
            raw_after == raw_before,
            "offline report regeneration changed a raw artifact",
        )
        return result


def _run_reference_policies(
    suite: _Suite, seed: int
) -> dict[str, list[RunResult]]:
    """Run every reference policy against every hidden state."""

    factories: dict[str, Callable[[], HarnessPolicy]] = {
        "balanced": BalancedSearchPolicy,
        "sequential": SequentialSearchPolicy,
        "seeded_random": lambda: SeededRandomSearchPolicy(seed),
    }
    results: dict[str, list[RunResult]] = {key: [] for key in factories}
    public_descriptions: list[dict[str, Any]] = []

    for policy_key, factory in factories.items():
        for index, fault_id in enumerate(suite.spec.fault_ids):
            result = suite.run(
                f"reference/{policy_key}/{index:02d}",
                factory(),
                fault_id,
                run_id=f"calibration-{policy_key}-{index:02d}",
            )
            results[policy_key].append(result)
            public_descriptions.append(dict(result.manifest["instance"]))
            generated = result.reference.get("generated_instance")
            suite.check(
                f"materialized_instance:{policy_key}:{index:02d}",
                isinstance(generated, Mapping)
                and generated.get("hidden_fault_id") == fault_id,
                "reference.json does not materialize the selected hidden state",
            )

    # The public instance must be byte-identical across all eight states.  If it
    # were not, the catalogue itself would leak the answer.
    suite.check(
        "public_boundary_independent_of_hidden_state",
        all(item == public_descriptions[0] for item in public_descriptions),
        "public instance changes with the selected hidden fault",
    )
    suite.check(
        "all_eight_hidden_states_covered",
        len(suite.spec.fault_ids) == 8
        and all(len(runs) == 8 for runs in results.values()),
        "reference policy coverage is incomplete",
    )
    return results


def _check_expected_readings(
    suite: _Suite, primary: dict[str, list[RunResult]], seed: int
) -> dict[str, Any]:
    """Compare the measured contrast against the readings the world implies."""

    diagnostics = {key: _diagnostics(runs) for key, runs in primary.items()}
    information = {key: _information_removed(runs) for key, runs in primary.items()}
    suite_information = {
        key: _suite_information(runs) for key, runs in primary.items()
    }
    efficiency = {
        key: float(values["bits_per_diagnostic_observation"])
        for key, values in suite_information.items()
    }
    excess = {
        key: int(values["excess_observations"])
        for key, values in suite_information.items()
    }

    for key in primary:
        suite.check(
            f"{key}_all_successful",
            all(result.succeeded for result in primary[key]),
            f"at least one {key} run did not satisfy every verifier condition",
        )
    suite.check(
        "balanced_exact_diagnostic_cost",
        diagnostics["balanced"] == EXPECTED_BALANCED_DIAGNOSTICS,
        f"got {diagnostics['balanced']!r}; expected three per hidden state",
    )
    if seed == DEFAULT_CALIBRATION_SEED:
        suite.check(
            "seeded_random_exact_diagnostic_cost",
            diagnostics["seeded_random"]
            == EXPECTED_DEFAULT_SEEDED_RANDOM_DIAGNOSTICS,
            f"got {diagnostics['seeded_random']!r}; "
            f"expected {EXPECTED_DEFAULT_SEEDED_RANDOM_DIAGNOSTICS!r}",
        )
    suite.check(
        "sequential_exact_diagnostic_cost",
        diagnostics["sequential"] == EXPECTED_SEQUENTIAL_DIAGNOSTICS,
        f"got {diagnostics['sequential']!r}; "
        f"expected {EXPECTED_SEQUENTIAL_DIAGNOSTICS!r}",
    )
    for key, depths in diagnostics.items():
        kraft_sum = _kraft_sum(depths)
        suite.check(
            f"{key}_reference_depth_vector_satisfies_kraft_equality",
            kraft_sum == 1.0,
            f"Kraft sum for {key} was {kraft_sum!r}, expected 1.0",
        )
    expected_excess = {
        key: value
        for key, value in EXPECTED_EXCESS_OBSERVATIONS.items()
        if key != "seeded_random" or seed == DEFAULT_CALIBRATION_SEED
    }
    for key, expected in expected_excess.items():
        suite.check(
            f"{key}_exact_excess_observations",
            excess[key] == expected,
            f"got {excess[key]!r}; expected {expected!r}",
        )
    suite.check(
        "sequential_aggregate_cost_larger",
        sum(diagnostics["sequential"]) == 35
        and sum(diagnostics["sequential"]) > sum(diagnostics["balanced"]),
        "sequential aggregate must be 35 versus balanced aggregate 24",
    )
    # Every completed diagnosis removes the same three bits.  The policies
    # differ in what they spend to remove them, which is the whole point of
    # keeping information and resources in separate columns.
    suite.check(
        "all_successful_runs_remove_three_bits",
        all(
            value == INITIAL_UNCERTAINTY_BITS
            for values in information.values()
            for value in values
        ),
        "a completed diagnosis did not remove the full three-bit uncertainty",
    )
    suite.check(
        "aggregate_efficiency_uses_ratio_of_sums",
        efficiency["balanced"] == 1.0
        and efficiency["sequential"] == 24 / 35
        and efficiency["balanced"] > efficiency["sequential"],
        "suite efficiency must be total exposed bits divided by total diagnostics",
    )

    return {
        key: {
            "diagnostic_observations_by_state": diagnostics[key],
            "diagnostic_observations_total": sum(diagnostics[key]),
            "information_exposed_bits_total": sum(information[key]),
            "information_per_observation_bits": efficiency[key],
            "excess_observations": excess[key],
        }
        for key in primary
    }


def _check_seeded_replay(
    suite: _Suite, seed: int, original: Sequence[RunResult]
) -> list[RunResult]:
    """Rerun the seeded policy and compare the interactions it produced.

    Comparison uses a signature that omits controller-owned identifiers, since
    a fresh run legitimately has a new artifact-set identity.  What must match
    is the sequence of actions, observations, and costs.
    """

    replays: list[RunResult] = []
    for index, fault_id in enumerate(suite.spec.fault_ids):
        replay = suite.run(
            f"replay/seeded_random/{index:02d}",
            SeededRandomSearchPolicy(seed),
            fault_id,
            run_id=f"calibration-seeded-random-replay-{index:02d}",
        )
        replays.append(replay)
        suite.check(
            f"seeded_replay:{index:02d}",
            interaction_signature(replay.events)
            == interaction_signature(original[index].events),
            "same declared seed produced a different interaction trace",
        )
    return replays


def _check_termination_paths(suite: _Suite) -> int:
    """Exercise each way a run can end other than an ordinary finish."""

    first_fault = suite.spec.fault_ids[0]

    invalid = suite.run(
        "controller_checks/invalid_action",
        _InvalidActionPolicy(),
        first_fault,
        run_id="calibration-invalid-action",
    )
    suite.check(
        "invalid_action_is_explicit",
        _termination_reason(invalid) == TERMINATION_INVALID_ACTION
        and [event.event_type for event in invalid.events][-2:]
        == [EVENT_PROTOCOL_ERROR, EVENT_TERMINATION],
        "invalid action did not produce protocol_error then termination",
    )

    never_finish = _NeverFinishPolicy()
    exhausted = suite.run(
        "controller_checks/budget_exhaustion",
        never_finish,
        first_fault,
        run_id="calibration-budget-exhaustion",
    )
    suite.check(
        "budget_stops_without_extra_request",
        _termination_reason(exhausted) == TERMINATION_BUDGET_EXHAUSTED
        and never_finish.calls == suite.action_budget
        and exhausted.report["resources"]["total_actions"] == suite.action_budget,
        "never-finishing harness was not stopped at exactly the fixed budget",
    )

    crash = suite.run(
        "controller_checks/harness_crash",
        _CrashPolicy(),
        first_fault,
        run_id="calibration-harness-crash",
    )
    suite.check(
        "harness_crash_is_explicit",
        _termination_reason(crash) == TERMINATION_HARNESS_CRASH
        and crash.events[-1].event_type == EVENT_TERMINATION,
        "harness exception did not produce an explicit termination record",
    )

    boundary_budget = 4
    boundary_policy = _FinishAtBoundaryPolicy(boundary_budget)
    boundary = suite.run(
        "controller_checks/finish_at_budget_boundary",
        boundary_policy,
        first_fault,
        run_id="calibration-finish-at-boundary",
        budget=boundary_budget,
    )
    suite.check(
        "finish_at_budget_boundary_is_normal",
        _termination_reason(boundary) == TERMINATION_NORMAL
        and boundary_policy.calls == boundary_budget
        and boundary.report["resources"]["total_actions"] == boundary_budget,
        "a valid finish as the last budgeted action was misclassified",
    )
    return 4


def _check_corruption_is_detected(suite: _Suite, sample: RunResult) -> None:
    """Flip one recorded diagnostic outcome and require replay to reject it."""

    corrupted = list(sample.events)
    for index, event in enumerate(corrupted):
        if (
            event.event_type == EVENT_INTERACTION
            and event.payload["action"]["type"] == Diagnose.kind
        ):
            payload = dict(event.payload)
            observation = dict(payload["observation"])
            observation["positive"] = not observation["positive"]
            payload["observation"] = observation
            corrupted[index] = replace(event, payload=payload)
            break

    detected = False
    try:
        build_report(sample.manifest, corrupted, sample.reference)
    except ReportError:
        detected = True
    suite.check(
        "offline_replay_rejects_trace_corruption",
        detected,
        "a contradictory diagnostic outcome was accepted",
    )


def run_calibration(
    output_dir: str | Path = "runs/calibration",
    *,
    seed: int = DEFAULT_CALIBRATION_SEED,
    action_budget: int = DEFAULT_ACTION_BUDGET,
    force: bool = False,
) -> CalibrationResult:
    """Run all states and policies, rebuild reports, and enforce the checks.

    Every check is recorded in ``calibration.json`` whether it passed or not.
    A failing suite still writes that file and then raises, so the reason is
    available for inspection instead of only appearing on a terminal.
    """

    if type(seed) is not int:
        raise CalibrationFailure("seed must be an integer")
    if type(action_budget) is not int or action_budget < MINIMUM_CALIBRATION_BUDGET:
        raise CalibrationFailure(
            "calibration action_budget must be at least "
            f"{MINIMUM_CALIBRATION_BUDGET} for all reference policies"
        )

    output = Path(output_dir)
    _prepare_output(output, force)
    spec = HiddenFaultSpec.default()
    suite = _Suite(output, spec, action_budget)

    primary = _run_reference_policies(suite, seed)
    aggregates = _check_expected_readings(suite, primary, seed)
    replays = _check_seeded_replay(suite, seed, primary["seeded_random"])
    controller_check_runs = _check_termination_paths(suite)
    _check_corruption_is_detected(suite, primary["balanced"][0])

    summary: dict[str, Any] = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "status": "passed" if not suite.failures else "failed",
        "world": {
            "world_id": spec.world_id,
            "world_version": spec.world_version,
            "hidden_states": list(spec.fault_ids),
        },
        "configuration": {
            "action_budget": action_budget,
            "seed_policy": {"kind": "fixed", "seed": seed},
            "cooperative_in_process_harness": True,
            "hostile_code_sandbox_enforced": False,
        },
        "aggregates": aggregates,
        "artifact_counts": {
            "primary_runs": sum(len(runs) for runs in primary.values()),
            "seeded_replay_runs": len(replays),
            "controller_check_runs": controller_check_runs,
            "reports_deleted_and_regenerated": suite.regenerated_run_count,
        },
        "checks": suite.checks,
        "failures": suite.failures,
    }
    write_json_atomic(output / "calibration.json", summary)
    if suite.failures:
        raise CalibrationFailure(
            f"{len(suite.failures)} calibration check(s) failed; "
            f"see {output / 'calibration.json'}",
            summary,
        )
    return CalibrationResult(output, summary)
