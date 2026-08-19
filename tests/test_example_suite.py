"""The committed suite driver must keep working exactly as documented.

``examples/run_suite.py`` is the entry path an external harness author copies
first, so these checks pin the two behaviors that author depends on: the
reference numbers the guide quotes, and loading a policy from a
``module:Class`` argument found in the current working directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DRIVER = PROJECT_ROOT / "examples" / "run_suite.py"

ARTIFACT_NAMES = ("manifest.json", "events.jsonl", "reference.json", "report.json")


def _driver_environment() -> dict[str, str]:
    environment = os.environ.copy()
    source_path = str(PROJECT_ROOT / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (source_path, environment.get("PYTHONPATH", "")) if value
    )
    # Make accidental client use fail quickly even though the driver imports
    # nothing that talks to a network.
    environment.update(
        {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
            "NO_PROXY": "",
        }
    )
    return environment


def _run_driver(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DRIVER), *arguments],
        cwd=cwd,
        env=_driver_environment(),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def test_example_suite_driver_reports_reference_numbers(tmp_path):
    parent = tmp_path / "suite"
    completed = _run_driver(
        ["balanced", "--run-parent", str(parent), "--json"], cwd=tmp_path
    )
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
    )

    document = json.loads(completed.stdout)
    suite = document["suite"]
    assert suite["run_count"] == 8
    assert suite["successful_runs"] == 8
    assert suite["resources"]["diagnostic_observations"] == 24
    information = suite["diagnostic_information"]
    assert information["total_uncertainty_removed_bits"] == 24.0
    assert information["excess_observations"] == 0

    assert len(document["per_run"]) == 8
    for row in document["per_run"]:
        assert row["overall_task_success"] is True
        run_dir = Path(row["run_dir"])
        for name in ARTIFACT_NAMES:
            assert (run_dir / name).is_file()


def test_example_suite_driver_loads_module_colon_class_policies(tmp_path):
    (tmp_path / "probe_policy.py").write_text(
        textwrap.dedent(
            """
            from metering import Diagnose, Finish, Repair, Verify
            from metering.events import RepairObservation, VerificationObservation
            from metering.policies import remaining_candidates


            class ProbePolicy:
                name = "probe"
                version = "1"

                def descriptor(self):
                    return {
                        "name": self.name,
                        "version": self.version,
                        "configuration": {},
                        "seed_policy": {"kind": "none"},
                    }

                def next_action(self, instance, observations):
                    last_repair = max(
                        (
                            index
                            for index, item in enumerate(observations)
                            if isinstance(item, RepairObservation)
                        ),
                        default=-1,
                    )
                    if last_repair >= 0:
                        verified = any(
                            index > last_repair
                            and isinstance(item, VerificationObservation)
                            for index, item in enumerate(observations)
                        )
                        return Finish() if verified else Verify()
                    candidates = remaining_candidates(instance, observations)
                    if len(candidates) == 1:
                        return Repair(candidates[0])
                    for test in instance.diagnostic_tests:
                        positive = set(candidates) & set(test.positive_fault_ids)
                        if 0 < len(positive) < len(candidates):
                            return Diagnose(test.test_id)
                    return Repair(candidates[0])
            """
        ),
        encoding="utf-8",
    )

    parent = tmp_path / "suite"
    completed = _run_driver(
        ["probe_policy:ProbePolicy", "--run-parent", str(parent), "--json"],
        cwd=tmp_path,
    )
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
    )

    document = json.loads(completed.stdout)
    assert document["policy"]["name"] == "probe"
    suite = document["suite"]
    assert suite["successful_runs"] == 8
    assert suite["diagnostic_information"]["excess_observations"] is not None
