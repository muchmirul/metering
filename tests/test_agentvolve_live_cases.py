"""Validate the ten-task live catalog and preparation without model execution."""

import json
from pathlib import Path

import pytest

from agentvolve_live_cases import prepare_cases
from test_agentvolve_live_workflow import require_approved_contract
from apps.coding_agent.protocol import load_final_profile, load_task_profile
from apps.coding_agent.task_profile_tool import preflight_task


def test_ten_distinct_live_contracts_have_empty_seeds_and_separate_final_inputs(tmp_path: Path):
    manifest = prepare_cases(tmp_path / "batch", 2)
    assert manifest["authority"] == "operator-review-required"
    assert len(manifest["tasks"]) == 10
    assert len({task["goal"] for task in manifest["tasks"]}) == 10
    for task in manifest["tasks"]:
        profile = load_task_profile(Path(task["profile"]))
        assert profile["task_id"] == task["task_id"]
        assert profile["limits"]["max_rounds"] == 2
        assert profile["limits"]["max_proposal_calls"] == 2, "No retry reservations are invented"
        assert (Path(profile["repository"]["path"]) / "solver.py").read_bytes() == b""
        assert profile["allowed_paths"] == ["solver.py"]
        _, final = load_final_profile(profile)
        public = profile["development_checks"]
        assert final[0]["check_schema"] == public[0]["check_schema"] == "stdout-json-v1"
        assert final[0]["argv"] != public[0]["argv"]
        assert final[0]["expected_stdout"] != public[0]["expected_stdout"]
        assert not preflight_task(profile)["warnings"]
        approved = {key: value for key, value in profile.items() if key != "task_id"}
        require_approved_contract(tmp_path / "batch", approved)
        for key, value in {"allowed_paths": ["TASK.md"], "goal": "unreviewed task", "final_assay": {"path": "/unreviewed/final.json", "sha256": "0" * 64}}.items():
            with pytest.raises(AssertionError, match="operator-approved"):
                require_approved_contract(tmp_path / "batch", {**approved, key: value})
    assert json.loads((tmp_path / "batch/review-manifest.json").read_text()) == manifest
    with pytest.raises(ValueError, match="existing evidence"):
        prepare_cases(tmp_path / "batch", 2)


@pytest.mark.parametrize("cap", [5, 256])
def test_live_catalog_accepts_normal_agentvolve_caps_without_launching(tmp_path: Path, cap):
    manifest = prepare_cases(tmp_path / 'batch', cap)
    assert manifest['authority'] == 'operator-review-required'
    for task in manifest['tasks']:
        profile = load_task_profile(Path(task['profile']))
        assert profile['limits']['max_rounds'] == profile['limits']['max_proposal_calls'] == cap
        assert preflight_task(profile)['development_reservation']['funded_rounds_without_retries'] == cap
        assert (Path(profile['repository']['path']) / 'solver.py').read_bytes() == b''


@pytest.mark.parametrize("cap", [0, 257, True, 1.5])
def test_live_catalog_requires_explicit_bounded_cap_before_effects(tmp_path: Path, cap):
    with pytest.raises(ValueError, match="explicitly chosen"):
        prepare_cases(tmp_path / "batch", cap)
    assert not (tmp_path / "batch").exists()
