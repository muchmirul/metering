"""Complete deterministic v0 calibration suite."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

from .events import Action, Diagnose, Finish, Observation
from .hidden_fault import HiddenFaultSpec, PublicInstance
from .policies import (
    BalancedSearchPolicy,
    SeededRandomSearchPolicy,
    SequentialSearchPolicy,
)
from .report import (
    EVENT_INTERACTION,
    EVENT_PROTOCOL_ERROR,
    EVENT_TERMINATION,
    ReportError,
    TERMINATION_BUDGET_EXHAUSTED,
    TERMINATION_HARNESS_CRASH,
    TERMINATION_INVALID_ACTION,
    TERMINATION_NORMAL,
    aggregate_reports,
    build_report,
    regenerate_report,
)
from .runner import DEFAULT_ACTION_BUDGET, RunResult, run_hidden_fault
from .trace import interaction_signature, write_json_atomic

CALIBRATION_SCHEMA_VERSION = 1
DEFAULT_CALIBRATION_SEED = 20260722
CALIBRATION_MARKER_NAME = ".metering-calibration-v0"
CALIBRATION_MARKER_BYTES = (
    b'{"format":"metering-calibration-output","schema_version":1}\n'
)


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
    if type(force) is not bool:
        raise CalibrationFailure("force must be an exact bool")
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise CalibrationFailure(
                f"calibration output must be a real directory: {path}"
            )
        entries = list(path.iterdir())
        if entries:
            if not force:
                raise CalibrationFailure(
                    f"calibration output is not empty: {path}; use force=True to replace it"
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
            resolved = path.resolve()
            if resolved in {Path("/").resolve(), Path.cwd().resolve()}:
                raise CalibrationFailure(f"refusing to remove unsafe output path: {path}")
            shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    marker = path / CALIBRATION_MARKER_NAME
    marker.write_bytes(CALIBRATION_MARKER_BYTES)


def _termination_reason(result: RunResult) -> str:
    value = result.report.get("termination_reason")
    return value if isinstance(value, str) else ""


def run_calibration(
    output_dir: str | Path = "runs/calibration-v0",
    *,
    seed: int = DEFAULT_CALIBRATION_SEED,
    action_budget: int = DEFAULT_ACTION_BUDGET,
    force: bool = False,
) -> CalibrationResult:
    """Run all states and policies, regenerate reports, and enforce v0 checks."""

    if type(seed) is not int:
        raise CalibrationFailure("seed must be an integer")
    if type(action_budget) is not int or action_budget < 10:
        raise CalibrationFailure(
            "calibration action_budget must be at least 10 for all reference policies"
        )

    output = Path(output_dir)
    _prepare_output(output, force)
    spec = HiddenFaultSpec.v0()
    failures: list[dict[str, str]] = []
    checks: dict[str, bool] = {}
    regenerated_run_count = 0

    def check(name: str, condition: bool, detail: str) -> None:
        checks[name] = bool(condition)
        if not condition:
            failures.append({"check": name, "detail": detail})

    def run_and_regenerate(
        relative: str,
        policy: Any,
        fault_id: str,
        *,
        run_id: str,
        budget: int = action_budget,
    ) -> RunResult:
        nonlocal regenerated_run_count
        result = run_hidden_fault(
            policy,
            fault_id,
            output / relative,
            spec=spec,
            run_id=run_id,
            action_budget=budget,
        )
        original_report = dict(result.report)
        trace_before = result.paths.events.read_bytes()
        result.paths.report.unlink()
        regenerated = regenerate_report(result.paths.run_dir)
        trace_after = result.paths.events.read_bytes()
        regenerated_run_count += 1
        check(
            f"report_regeneration:{relative}",
            regenerated == original_report,
            "regenerated report differs from the original",
        )
        check(
            f"trace_unchanged_by_meter:{relative}",
            trace_after == trace_before,
            "offline report regeneration changed events.jsonl",
        )
        return result

    primary: dict[str, list[RunResult]] = {
        "balanced": [],
        "sequential": [],
        "seeded_random": [],
    }
    public_descriptions: list[dict[str, Any]] = []

    factories = {
        "balanced": BalancedSearchPolicy,
        "sequential": SequentialSearchPolicy,
        "seeded_random": lambda: SeededRandomSearchPolicy(seed),
    }
    for policy_key, factory in factories.items():
        for index, fault_id in enumerate(spec.fault_ids):
            policy = factory()
            relative = f"reference/{policy_key}/{index:02d}"
            result = run_and_regenerate(
                relative,
                policy,
                fault_id,
                run_id=f"calibration-v0-{policy_key}-{index:02d}",
            )
            primary[policy_key].append(result)
            public_descriptions.append(dict(result.manifest["instance"]))
            generated = result.reference.get("generated_instance")
            check(
                f"materialized_instance:{policy_key}:{index:02d}",
                isinstance(generated, Mapping)
                and generated.get("hidden_fault_id") == fault_id,
                "reference.json does not materialize the selected hidden state",
            )

    check(
        "public_boundary_independent_of_hidden_state",
        all(item == public_descriptions[0] for item in public_descriptions),
        "public instance changes with the selected hidden fault",
    )
    check(
        "all_eight_hidden_states_covered",
        len(spec.fault_ids) == 8
        and all(len(results) == 8 for results in primary.values()),
        "reference policy coverage is incomplete",
    )

    def diagnostics(results: Sequence[RunResult]) -> list[int]:
        return [int(result.report["resources"]["diagnostic_observations"]) for result in results]

    def information_removed(results: Sequence[RunResult]) -> list[float]:
        return [
            float(
                result.report["diagnostic_information"][
                    "total_uncertainty_removed_bits"
                ]
            )
            for result in results
        ]

    balanced_diagnostics = diagnostics(primary["balanced"])
    sequential_diagnostics = diagnostics(primary["sequential"])
    random_diagnostics = diagnostics(primary["seeded_random"])
    balanced_information = information_removed(primary["balanced"])
    sequential_information = information_removed(primary["sequential"])
    random_information = information_removed(primary["seeded_random"])

    check(
        "balanced_all_successful",
        all(result.succeeded for result in primary["balanced"]),
        "at least one balanced run did not satisfy every verifier condition",
    )
    check(
        "balanced_exact_diagnostic_cost",
        balanced_diagnostics == [3] * 8,
        f"got {balanced_diagnostics!r}; expected three per hidden state",
    )
    check(
        "sequential_all_successful",
        all(result.succeeded for result in primary["sequential"]),
        "at least one sequential run did not satisfy every verifier condition",
    )
    expected_sequential = [1, 2, 3, 4, 5, 6, 7, 7]
    check(
        "sequential_exact_diagnostic_cost",
        sequential_diagnostics == expected_sequential,
        f"got {sequential_diagnostics!r}; expected {expected_sequential!r}",
    )
    check(
        "sequential_aggregate_cost_larger",
        sum(sequential_diagnostics) == 35
        and sum(sequential_diagnostics) > sum(balanced_diagnostics),
        "sequential aggregate must be 35 versus balanced aggregate 24",
    )
    check(
        "seeded_random_all_successful",
        all(result.succeeded for result in primary["seeded_random"]),
        "at least one seeded random run failed",
    )
    check(
        "all_successful_runs_remove_three_bits",
        all(value == 3.0 for value in balanced_information)
        and all(value == 3.0 for value in sequential_information)
        and all(value == 3.0 for value in random_information),
        "a completed diagnosis did not remove the full three-bit uncertainty",
    )

    balanced_aggregate = aggregate_reports(
        [result.report for result in primary["balanced"]]
    )
    sequential_aggregate = aggregate_reports(
        [result.report for result in primary["sequential"]]
    )
    random_aggregate = aggregate_reports(
        [result.report for result in primary["seeded_random"]]
    )
    balanced_efficiency = float(
        balanced_aggregate["diagnostic_information"][
            "bits_per_diagnostic_observation"
        ]
    )
    sequential_efficiency = float(
        sequential_aggregate["diagnostic_information"][
            "bits_per_diagnostic_observation"
        ]
    )
    random_efficiency = float(
        random_aggregate["diagnostic_information"][
            "bits_per_diagnostic_observation"
        ]
    )
    check(
        "aggregate_efficiency_uses_ratio_of_sums",
        balanced_efficiency == 1.0
        and sequential_efficiency == 24 / 35
        and balanced_efficiency > sequential_efficiency,
        "suite efficiency must be total exposed bits divided by total diagnostics",
    )

    replay_results: list[RunResult] = []
    for index, fault_id in enumerate(spec.fault_ids):
        replay = run_and_regenerate(
            f"replay/seeded_random/{index:02d}",
            SeededRandomSearchPolicy(seed),
            fault_id,
            run_id=f"calibration-v0-seeded-random-replay-{index:02d}",
        )
        replay_results.append(replay)
        check(
            f"seeded_replay:{index:02d}",
            interaction_signature(replay.events)
            == interaction_signature(primary["seeded_random"][index].events),
            "same declared seed produced a different interaction trace",
        )

    invalid_result = run_and_regenerate(
        "controller_checks/invalid_action",
        _InvalidActionPolicy(),
        spec.fault_ids[0],
        run_id="calibration-v0-invalid-action",
    )
    check(
        "invalid_action_is_explicit",
        _termination_reason(invalid_result) == TERMINATION_INVALID_ACTION
        and [event.event_type for event in invalid_result.events][-2:]
        == [EVENT_PROTOCOL_ERROR, EVENT_TERMINATION],
        "invalid action did not produce protocol_error then termination",
    )

    never_finish = _NeverFinishPolicy()
    budget_result = run_and_regenerate(
        "controller_checks/budget_exhaustion",
        never_finish,
        spec.fault_ids[0],
        run_id="calibration-v0-budget-exhaustion",
    )
    check(
        "budget_stops_without_extra_request",
        _termination_reason(budget_result) == TERMINATION_BUDGET_EXHAUSTED
        and never_finish.calls == action_budget
        and budget_result.report["resources"]["total_actions"] == action_budget,
        "never-finishing harness was not stopped at exactly the fixed budget",
    )

    crash_result = run_and_regenerate(
        "controller_checks/harness_crash",
        _CrashPolicy(),
        spec.fault_ids[0],
        run_id="calibration-v0-harness-crash",
    )
    check(
        "harness_crash_is_explicit",
        _termination_reason(crash_result) == TERMINATION_HARNESS_CRASH
        and crash_result.events[-1].event_type == EVENT_TERMINATION,
        "harness exception did not produce an explicit termination record",
    )

    boundary_budget = 4
    boundary_policy = _FinishAtBoundaryPolicy(boundary_budget)
    boundary_result = run_and_regenerate(
        "controller_checks/finish_at_budget_boundary",
        boundary_policy,
        spec.fault_ids[0],
        run_id="calibration-v0-finish-at-boundary",
        budget=boundary_budget,
    )
    check(
        "finish_at_budget_boundary_is_normal",
        _termination_reason(boundary_result) == TERMINATION_NORMAL
        and boundary_policy.calls == boundary_budget
        and boundary_result.report["resources"]["total_actions"] == boundary_budget,
        "a valid finish as action B was misclassified as budget exhaustion",
    )

    # Prove that offline replay rejects a contradictory delivered outcome.
    corruption_detected = False
    sample = primary["balanced"][0]
    corrupted_events = list(sample.events)
    for index, event in enumerate(corrupted_events):
        if event.event_type == EVENT_INTERACTION and event.payload["action"]["type"] == "diagnose":
            payload = dict(event.payload)
            observation = dict(payload["observation"])
            observation["positive"] = not observation["positive"]
            payload["observation"] = observation
            corrupted_events[index] = replace(event, payload=payload)
            break
    try:
        build_report(sample.manifest, corrupted_events, sample.reference)
    except ReportError:
        corruption_detected = True
    check(
        "offline_replay_rejects_trace_corruption",
        corruption_detected,
        "a contradictory diagnostic outcome was accepted",
    )

    summary: dict[str, Any] = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "status": "passed" if not failures else "failed",
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
        "aggregates": {
            "balanced": {
                "diagnostic_observations_by_state": balanced_diagnostics,
                "diagnostic_observations_total": sum(balanced_diagnostics),
                "information_exposed_bits_total": sum(balanced_information),
                "information_per_observation_bits": balanced_efficiency,
            },
            "sequential": {
                "diagnostic_observations_by_state": sequential_diagnostics,
                "diagnostic_observations_total": sum(sequential_diagnostics),
                "information_exposed_bits_total": sum(sequential_information),
                "information_per_observation_bits": sequential_efficiency,
            },
            "seeded_random": {
                "diagnostic_observations_by_state": random_diagnostics,
                "diagnostic_observations_total": sum(random_diagnostics),
                "information_exposed_bits_total": sum(random_information),
                "information_per_observation_bits": random_efficiency,
            },
        },
        "artifact_counts": {
            "primary_runs": sum(len(value) for value in primary.values()),
            "seeded_replay_runs": len(replay_results),
            "controller_check_runs": 4,
            "reports_deleted_and_regenerated": regenerated_run_count,
        },
        "checks": checks,
        "failures": failures,
    }
    write_json_atomic(output / "calibration.json", summary)
    if failures:
        raise CalibrationFailure(
            f"{len(failures)} calibration check(s) failed; see {output / 'calibration.json'}",
            summary,
        )
    return CalibrationResult(output, summary)
