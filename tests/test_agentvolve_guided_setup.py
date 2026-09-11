"""Deployed conversational configuration discovery without modal approvals."""

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from test_agentvolve_jobs import deployed, ordinary, result, talk
from test_agentvolve_jobs import boundary as boundary
from test_agentvolve_session_configuration import records, selections, without_defaults

pytestmark = pytest.mark.skipif(shutil.which("pi") is None, reason="Pi is not installed")


def catalogue(tmp_path, boundary, *, issues=None, count=1):
    paths = selections(boundary)
    options = [
        {
            **paths,
            "runtime_id": "b" * 64,
            "harness_candidate_id": "c" * 64,
            "worker_models_sha256": hashlib.sha256(
                (Path(paths["configuration"]) / "models.json").read_bytes()
            ).hexdigest(),
            "provider": "worker-provider",
            "model": "pinned-worker",
            "model_label": f"Reviewed local Qwen {index}",
            "implementation_version": "0.84.4",
            "recorded_final_passed": 3,
            "recorded_final_total": 3,
        }
        for index in range(count)
    ]
    value = {
        "setup_schema": "agentvolve-setup-discovery-v1",
        "authority": "diagnostic-only",
        "options": options,
        "issues": issues or [],
        "truncated": False,
    }
    (tmp_path / "setup-catalogue.json").write_text(json.dumps(value))
    return value


def _blocking(events):
    return [
        event
        for event in events
        if event.get("method") in {"input", "select", "confirm", "editor"}
    ]


def test_single_discovered_setup_is_validated_and_saved_without_dialogs(tmp_path, boundary):
    catalogue(tmp_path, boundary)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        before = rpc.request({"id": "before", "type": "get_state"})[-1]["data"]
        events = talk(rpc, "Configure worker")
        configured = result(events)
        assert configured["details"]["status"] == "configured"
        assert not _blocking(events)
        assert len(records(rpc)) == 1
        assert not (tmp_path / "dispatched").exists()
        assert "prepare-registry" in (tmp_path / "execs").read_text()
        after = rpc.request({"id": "after", "type": "get_state"})[-1]["data"]
        assert before["sessionId"] == after["sessionId"]
        ordinary(rpc, tmp_path)


def test_multiple_setups_are_returned_for_conversational_selection(tmp_path, boundary):
    expected = catalogue(tmp_path, boundary, count=2)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        events = talk(rpc, "Configure worker")
        needed = result(events)
        assert needed["details"]["status"] == "needs-configuration"
        assert needed["details"]["missing"] == ["harness", "configuration"]
        assert needed["details"]["options"] == expected["options"]
        assert not _blocking(events)
        assert records(rpc) == [] and not (tmp_path / "dispatched").exists()
        assert not any(
            "review-configured" in line
            for line in (tmp_path / "execs").read_text().splitlines()
        )


def test_missing_setup_returns_fields_and_repair_diagnosis(tmp_path, boundary):
    message = "Prepare separate worker models.json."
    catalogue(
        tmp_path,
        boundary,
        count=0,
        issues=[{"code": "worker_configuration_unavailable", "message": message}],
    )
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        events = talk(rpc, "Configure worker")
        needed = result(events)
        assert needed["details"]["status"] == "needs-configuration"
        assert needed["details"]["issues"] == [message]
        assert message in needed["content"][0]["text"]
        assert not _blocking(events)
        assert records(rpc) == [] and not (tmp_path / "dispatched").exists()
        ordinary(rpc, tmp_path)


def test_private_registry_failure_stops_configuration_before_review(tmp_path, boundary):
    catalogue(tmp_path, boundary)
    (tmp_path / "registry-failure").touch()
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        events = talk(rpc, "Configure worker", error=True)
        assert "cannot enforce private permissions" in json.dumps(events)
        calls = (tmp_path / "execs").read_text()
        assert "prepare-registry" in calls and "review-configured" not in calls
        assert records(rpc) == [] and not (tmp_path / "dispatched").exists()


def test_changed_discovered_identity_refuses_configuration(tmp_path, boundary):
    value = catalogue(tmp_path, boundary)
    value["options"][0]["runtime_id"] = "d" * 64
    (tmp_path / "setup-catalogue.json").write_text(json.dumps(value))
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        events = talk(rpc, "Configure worker", error=True)
        assert "changed during discovery" in json.dumps(events)
        assert not _blocking(events)
        assert records(rpc) == [] and not (tmp_path / "dispatched").exists()
