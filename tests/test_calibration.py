from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path

import pytest
from contract import (
    RunArtifacts,
    ScriptedHarness,
    canonical_events,
    get_path,
    information_value,
    resource_count,
    verification_fact,
)


def _run_policy(api, tmp_path, policy_name, fault_index, *, seed=None, suffix=""):
    return api.run(
        harness=api.policy(policy_name, seed=seed),
        fault_id=api.fault_ids[fault_index],
        parent_dir=tmp_path / policy_name,
        budget=64,
        run_id=f"{policy_name}-{fault_index}{suffix}",
    )


def test_balanced_search_succeeds_for_all_states_at_exact_known_cost(api, tmp_path):
    reports = []
    for index in range(8):
        artifacts = _run_policy(api, tmp_path, "balanced", index)
        reports.append(artifacts.report)

    for report in reports:
        assert verification_fact(report, "success") is True
        assert verification_fact(report, "repair_matches") is True
        assert verification_fact(report, "verified_after_final_repair") is True
        assert verification_fact(report, "terminated_normally") is True
        assert verification_fact(report, "budget_respected") is True
        assert resource_count(report, "diagnostic") == 3
        assert resource_count(report, "repair") == 1
        assert resource_count(report, "verification") == 1
        # Three diagnostics, one repair, one verification, and one finish.
        assert resource_count(report, "total") == 6
        assert resource_count(report, "budget_exhausted") is False


def test_balanced_search_exposes_one_bit_per_observation(api, tmp_path):
    for index in range(8):
        report = _run_policy(api, tmp_path, "balanced", index).report
        assert information_value(report, "initial") == pytest.approx(3.0)
        assert information_value(report, "remaining") == pytest.approx([2.0, 1.0, 0.0])
        assert information_value(report, "removed") == pytest.approx(3.0)
        assert information_value(report, "per_observation") == pytest.approx(1.0)


def test_sequential_search_exact_cost_vector_and_aggregate(api, tmp_path):
    """The last state is inferred after seven negatives, so no eighth check."""
    reports = [
        _run_policy(api, tmp_path, "sequential", index).report for index in range(8)
    ]
    diagnostic_counts = [
        int(resource_count(report, "diagnostic")) for report in reports
    ]

    assert diagnostic_counts == [1, 2, 3, 4, 5, 6, 7, 7]
    assert sum(diagnostic_counts) == 35
    assert sum(diagnostic_counts) > 24  # balanced uses 8 * 3

    for report, count in zip(reports, diagnostic_counts):
        assert verification_fact(report, "success") is True
        assert resource_count(report, "repair") == 1
        assert resource_count(report, "verification") == 1
        assert resource_count(report, "total") == count + 3
        assert information_value(report, "initial") == pytest.approx(3.0)
        remaining = information_value(report, "remaining")
        assert len(remaining) == count
        assert remaining[-1] == pytest.approx(0.0)
        assert all(left >= right for left, right in pairwise(remaining))
        assert information_value(report, "removed") == pytest.approx(3.0)
        assert information_value(report, "per_observation") == pytest.approx(
            3.0 / count
        )


def test_calibration_information_aggregation_is_ratio_of_sums(api, tmp_path):
    """Unequal run lengths must be weighted by delivered observations."""
    reports = [
        _run_policy(api, tmp_path, "sequential", index).report for index in range(8)
    ]
    total_removed = sum(
        float(information_value(report, "removed")) for report in reports
    )
    total_observations = sum(
        int(resource_count(report, "diagnostic")) for report in reports
    )
    ratio_of_sums = total_removed / total_observations
    unweighted_mean = sum(
        float(information_value(report, "per_observation")) for report in reports
    ) / len(reports)

    assert total_removed == pytest.approx(24.0)
    assert total_observations == 35
    assert ratio_of_sums == pytest.approx(24.0 / 35.0)
    assert ratio_of_sums != pytest.approx(unweighted_mean)
    assert ratio_of_sums < 1.0  # balanced aggregate is exactly one bit per observation

    summary = api.report_module.aggregate_reports(reports)
    measured = get_path(summary, "diagnostic_information.bits_per_diagnostic_observation")
    excess = get_path(summary, "diagnostic_information.excess_observations")
    assert measured == pytest.approx(ratio_of_sums)
    assert excess == 11
    assert all(
        "excess_observations" not in get_path(report, "diagnostic_information")
        for report in reports
    )


def test_suite_bound_is_null_for_arbitrary_report_collections(api, tmp_path):
    report = _run_policy(
        api, tmp_path, "balanced", 0, suffix="-incomplete-suite"
    ).report

    for report_count in (0, 7, 9):
        aggregate = api.report_module.aggregate_reports([report] * report_count)
        assert aggregate["run_count"] == report_count
        assert aggregate["diagnostic_information"]["excess_observations"] is None


def test_failed_suite_reports_no_excess_observation_value(api, tmp_path):
    reports = [
        api.run(
            harness=ScriptedHarness([api.action("finish")]),
            fault_id=fault_id,
            parent_dir=tmp_path,
            budget=4,
            run_id=f"failed-{index}",
        ).report
        for index, fault_id in enumerate(api.fault_ids)
    ]

    aggregate = api.report_module.aggregate_reports(reports)

    assert aggregate["run_count"] == 8
    assert aggregate["successful_runs"] == 0
    assert aggregate["diagnostic_information"]["excess_observations"] is None


def test_suite_aggregation_requires_exact_success_flags(api, tmp_path):
    report = api.run(
        harness=ScriptedHarness([api.action("finish")]),
        fault_id=api.fault_ids[0],
        parent_dir=tmp_path,
        budget=4,
        run_id="malformed-success",
    ).report
    malformed = {
        **report,
        "correctness": {
            **report["correctness"],
            "overall_task_success": 1,
        },
    }

    with pytest.raises(
        api.report_module.ReportError,
        match=r"report 0 overall_task_success must be an exact bool$",
    ):
        api.report_module.aggregate_reports([malformed] * 8)


def test_zero_diagnostics_reports_null_efficiency_not_zero(api, tmp_path):
    artifacts = api.run(
        harness=ScriptedHarness([api.action("finish")]),
        fault_id=api.fault_ids[0],
        parent_dir=tmp_path,
        budget=4,
        run_id="zero-diagnostics",
    )
    assert resource_count(artifacts.report, "diagnostic") == 0
    assert information_value(artifacts.report, "initial") == pytest.approx(3.0)
    assert information_value(artifacts.report, "remaining") == []
    assert information_value(artifacts.report, "removed") == pytest.approx(0.0)
    assert information_value(artifacts.report, "per_observation") is None


def test_seeded_random_policy_replays_identically_for_same_seed(api, tmp_path):
    seed = 8675309
    first = api.run(
        harness=api.policy("seeded_random", seed=seed),
        fault_id=api.fault_ids[5],
        parent_dir=tmp_path / "first",
        budget=64,
        run_id="seeded-one",
    )
    second = api.run(
        harness=api.policy("seeded_random", seed=seed),
        fault_id=api.fault_ids[5],
        parent_dir=tmp_path / "second",
        budget=64,
        run_id="seeded-two",
    )

    assert canonical_events(first.events) == canonical_events(second.events)
    assert verification_fact(first.report, "success") is True
    assert verification_fact(second.report, "success") is True
    recorded_seeds = []
    for manifest in (first.manifest, second.manifest):
        recorded_seeds.extend(
            value
            for path in (
                "seed",
                "policy.seed",
                "policy.seed_policy.seed",
                "configuration.seed",
                "seed_policy.seed",
            )
            for value in [_optional_path(manifest, path)]
            if value is not None
        )
    assert recorded_seeds and all(int(value) == seed for value in recorded_seeds)


def _optional_path(mapping, path):
    value = mapping
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _reference_fault(reference):
    return get_path(
        reference,
        "hidden_fault",
        "fault_id",
        "hidden_state",
        "generated_instance.hidden_fault_id",
        "reference.hidden_fault",
    )


def _policy_name(manifest):
    value = get_path(
        manifest,
        "policy.name",
        "policy.policy_id",
        "policy_name",
        "configuration.policy.name",
        "configuration.policy",
    )
    return str(value).lower().replace("-", "_")


def test_required_calibrate_command_covers_every_state_and_reference_policy(
    api, tmp_path
):
    """This invokes the exact command promised by PLAN.md."""
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    source_path = str(project_root / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (source_path, environment.get("PYTHONPATH", "")) if value
    )
    # Make accidental client use fail quickly even though Metering should import none.
    environment.update(
        {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
            "NO_PROXY": "",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-m", "metering", "calibrate"],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
    )

    run_dirs = sorted(
        path.parent
        for path in tmp_path.rglob("manifest.json")
        if all(
            (path.parent / name).is_file()
            for name in ("events.jsonl", "reference.json", "report.json")
        )
    )
    assert len(run_dirs) >= 24
    artifacts = [RunArtifacts.load(path) for path in run_dirs]

    groups = {"balanced": [], "sequential": [], "seeded": []}
    for run in artifacts:
        name = _policy_name(run.manifest)
        group = next((key for key in groups if key in name), None)
        if group:
            groups[group].append(run)

    expected_faults = set(api.fault_ids)
    for name, runs in groups.items():
        assert runs, f"calibrate produced no {name} runs"
        assert {_reference_fault(run.reference) for run in runs} == expected_faults

    assert all(
        verification_fact(run.report, "success")
        and resource_count(run.report, "diagnostic") == 3
        for run in groups["balanced"]
    )
    balanced_total = sum(
        int(resource_count(run.report, "diagnostic")) for run in groups["balanced"]
    )
    sequential_total = sum(
        int(resource_count(run.report, "diagnostic")) for run in groups["sequential"]
    )
    assert balanced_total == 24
    assert sequential_total == 35

    summaries = list(tmp_path.rglob("calibration.json"))
    assert len(summaries) == 1
    assert summaries[0] == tmp_path / "runs" / "calibration" / "calibration.json"
    summary = json.loads(summaries[0].read_text())
    assert summary["status"] == "passed"
    assert summary["world"]["hidden_states"] == list(api.fault_ids)
    assert summary["aggregates"]["balanced"]["diagnostic_observations_total"] == 24
    assert summary["aggregates"]["seeded_random"]["diagnostic_observations_total"] == 28
    assert summary["aggregates"]["sequential"]["diagnostic_observations_total"] == 35
    assert summary["aggregates"]["balanced"][
        "information_per_observation_bits"
    ] == pytest.approx(1.0)
    assert summary["aggregates"]["sequential"][
        "information_per_observation_bits"
    ] == pytest.approx(24.0 / 35.0)
    assert {
        key: summary["aggregates"][key]["excess_observations"]
        for key in ("balanced", "seeded_random", "sequential")
    } == {"balanced": 0, "seeded_random": 4, "sequential": 11}
    assert summary["checks"]["aggregate_efficiency_uses_ratio_of_sums"] is True
    assert all(
        summary["checks"][f"{key}_reference_depth_vector_satisfies_kraft_equality"]
        for key in ("balanced", "seeded_random", "sequential")
    )
    assert all(summary["checks"].values())


def test_cli_reports_tag_derived_package_version(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "metering", "--version"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == f"python -m metering {version('metering')}"
