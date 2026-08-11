from __future__ import annotations

import json

import pytest

from metering.calibration import CalibrationFailure, run_calibration


def test_calibration_force_refuses_nonempty_unmarked_directory(tmp_path):
    output = tmp_path / "valuable-unrelated-directory"
    output.mkdir()
    sentinel = output / "do-not-delete.txt"
    sentinel.write_bytes(b"irreplaceable caller data\n")
    before = {path.name: path.read_bytes() for path in output.iterdir()}

    with pytest.raises(CalibrationFailure, match="mark|own|calibrat|refus|unsafe"):
        run_calibration(output, force=True)

    assert output.is_dir()
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
    assert sentinel.read_bytes() == b"irreplaceable caller data\n"


def test_calibration_force_safely_replaces_its_own_marked_directory(tmp_path):
    output = tmp_path / "owned-calibration"
    first = run_calibration(output)
    assert first.summary["status"] == "passed"
    assert (output / "calibration.json").is_file()

    stale = output / "stale-from-prior-run.txt"
    stale.write_text("must disappear only after ownership is established")
    nested_stale = output / "stale" / "nested.txt"
    nested_stale.parent.mkdir()
    nested_stale.write_text("old")

    second = run_calibration(output, force=True)
    assert second.output_dir == output
    assert second.summary["status"] == "passed"
    assert not stale.exists()
    assert not nested_stale.exists()
    summary = json.loads((output / "calibration.json").read_text())
    assert summary == second.summary
    assert all(summary["checks"].values())
