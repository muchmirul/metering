from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Mapping
import uuid

import pytest

from v0_contract import (
    ScriptedHarness,
    jsonable,
    recursive_keys,
    resource_count,
    verification_fact,
)


def _finish_only_run(api, tmp_path, run_id="private-reference-binding"):
    harness = ScriptedHarness([api.action("finish")])
    run = api.run(
        harness=harness,
        fault_id=api.fault_ids[0],
        parent_dir=tmp_path,
        budget=4,
        run_id=run_id,
    )
    return harness, run


def _paths_matching_key(value: Any, fragment: str, prefix=()):
    paths = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = prefix + (str(key),)
            if fragment in str(key).lower():
                paths.append(path)
            paths.extend(_paths_matching_key(child, fragment, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_paths_matching_key(child, fragment, prefix + (index,)))
    return paths


def _get(value: Any, path):
    for key in path:
        value = value[key]
    return value


def _set(value: Any, path, replacement):
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement


def _different_well_formed_nonce(nonce: str) -> str:
    assert isinstance(nonce, str) and nonce
    if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        nonce,
        re.IGNORECASE,
    ):
        replacement = str(uuid.uuid4())
        assert replacement != nonce
        return replacement
    if re.fullmatch(r"[0-9a-f]+", nonce, re.IGNORECASE):
        first = "1" if nonce[0].lower() != "1" else "2"
        return first + nonce[1:]
    # Preserve length and a conservative token alphabet for other encodings.
    first = "B" if nonce[0] != "B" else "C"
    return first + nonce[1:]


def _write_reference(run, reference):
    (run.run_dir / "reference.json").write_text(
        json.dumps(reference, sort_keys=True, separators=(",", ":")) + "\n"
    )
    (run.run_dir / "report.json").unlink(missing_ok=True)


def test_trace_plausible_hidden_fault_substitution_breaks_private_commitment(
    api, tmp_path
):
    """No-observation traces still bind the exact controller-private state."""
    _, run = _finish_only_run(api, tmp_path, "hidden-substitution")
    assert resource_count(run.report, "diagnostic") == 0
    assert verification_fact(run.report, "terminated_normally") is True
    baseline_bytes = (run.run_dir / "reference.json").read_bytes()
    damaged = deepcopy(run.reference)
    original = damaged["generated_instance"]["hidden_fault_id"]
    replacement = next(fault for fault in api.fault_ids if fault != original)
    damaged["generated_instance"]["hidden_fault_id"] = replacement
    # Either state is compatible with the content-free finish interaction; the
    # rejection therefore cannot be credited to diagnostic outcomes.
    assert replacement in run.manifest["instance"]["fault_ids"]

    _write_reference(run, damaged)
    with pytest.raises(ValueError, match="commit|bind|reference|private"):
        api.rebuild_report(run.run_dir)
    assert not (run.run_dir / "report.json").exists()

    (run.run_dir / "reference.json").write_bytes(baseline_bytes)
    api.rebuild_report(run.run_dir)


def test_private_binding_nonce_substitution_is_rejected(api, tmp_path):
    _, run = _finish_only_run(api, tmp_path, "nonce-substitution")
    nonce_paths = _paths_matching_key(run.reference, "nonce")
    assert len(nonce_paths) == 1, "reference must contain one unambiguous private nonce"
    nonce_path = nonce_paths[0]
    nonce = _get(run.reference, nonce_path)
    replacement = _different_well_formed_nonce(nonce)
    assert replacement != nonce and len(replacement) == len(nonce)

    baseline_bytes = (run.run_dir / "reference.json").read_bytes()
    damaged = deepcopy(run.reference)
    _set(damaged, nonce_path, replacement)
    _write_reference(run, damaged)
    with pytest.raises(ValueError, match="commit|bind|nonce|reference"):
        api.rebuild_report(run.run_dir)
    assert not (run.run_dir / "report.json").exists()

    (run.run_dir / "reference.json").write_bytes(baseline_bytes)
    api.rebuild_report(run.run_dir)


def test_private_nonce_never_crosses_public_or_harness_boundary(api, tmp_path):
    fault = api.fault_ids[3]
    harness = ScriptedHarness(
        [
            api.action("diagnose", api.test_ids[0]),
            api.action("repair", fault),
            api.action("verify"),
            api.action("finish"),
        ]
    )
    run = api.run(
        harness=harness,
        fault_id=fault,
        parent_dir=tmp_path,
        budget=8,
        run_id="nonce-boundary",
    )
    nonce_paths = _paths_matching_key(run.reference, "nonce")
    assert len(nonce_paths) == 1
    nonce = _get(run.reference, nonce_paths[0])
    assert isinstance(nonce, str) and nonce

    commitment_paths = _paths_matching_key(run.manifest, "commit")
    assert len(commitment_paths) == 1, "manifest must carry one opaque commitment"
    commitment_record = _get(run.manifest, commitment_paths[0])
    if isinstance(commitment_record, Mapping):
        assert set(commitment_record) == {"algorithm", "digest"}
        assert commitment_record["algorithm"] == "sha256"
        commitment = commitment_record["digest"]
    else:
        commitment = commitment_record
    assert isinstance(commitment, str) and re.fullmatch(r"[0-9a-f]{64}", commitment)
    assert commitment != nonce
    assert nonce not in json.dumps(run.manifest, sort_keys=True)

    public_instance = run.manifest["instance"]
    assert not _paths_matching_key(public_instance, "nonce")
    assert nonce not in json.dumps(public_instance, sort_keys=True)

    for event in run.events:
        payload = event["payload"]
        assert not _paths_matching_key(payload, "nonce")
        assert nonce not in json.dumps(payload, sort_keys=True)

    assert harness.action_inputs
    for args, kwargs in harness.action_inputs:
        callback_input = jsonable({"args": args, "kwargs": kwargs})
        assert not _paths_matching_key(callback_input, "nonce")
        assert nonce not in json.dumps(callback_input, sort_keys=True)

    # The commitment may be public; neither its key nor its preimage appears in
    # the public instance or callback inputs.
    assert all("nonce" not in key.lower() for key in recursive_keys(run.manifest))
