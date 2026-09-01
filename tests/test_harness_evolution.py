"""Typed harness, isolation, recursion, recurrence, and final-sealing tests."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json  # noqa: E402
from apps.harness.conformance import run_conformance  # noqa: E402
from apps.harness.experiment import run_experiment, verify_experiment  # noqa: E402
from apps.harness.harness_runner import execute  # noqa: E402
from apps.harness.kernel_contract import (  # noqa: E402
    KernelContractError,
    KernelSession,
    _docker_command,
)
from apps.harness.model_contract import model_request  # noqa: E402
from apps.harness.protocol import (  # noqa: E402
    HarnessProtocolError,
    load_candidate,
    refresh_manifest,
)
from apps.harness.receipts import (  # noqa: E402
    HarnessReceiptError,
    completion_result_digest,
    load_receipt,
)
from apps.harness.runtime_manifest import load_runtime_manifest  # noqa: E402
from apps.population.contract import load_state  # noqa: E402
from apps.population_driver.paths import population_root  # noqa: E402
from connectors.fixed.harness_model_runtime import (  # noqa: E402
    invoke_model,
    verify_implementation,
)
from connectors.fixed.harness_proposer_runtime import _apply_response  # noqa: E402
from artifacts.git.git_proposer import ProposerError  # noqa: E402

REFERENCE = ROOT / "apps" / "harness" / "reference"
FIXTURES = ROOT / "apps" / "harness" / "fixtures"
FIXTURE_RUNTIME = ROOT / "apps" / "harness" / "profiles" / "runtime-fixture.json"
OCI_RUNTIME = ROOT / "apps" / "harness" / "isolation" / "runtime.pi.example.json"


def test_typed_harness_manifest_covers_every_file_and_refreshes_digests(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "candidate"
    shutil.copytree(REFERENCE, checkout)
    candidate = load_candidate(checkout)
    assert set(candidate.paths) == {
        "compaction_policy",
        "context_policy",
        "dependency_lock",
        "entrypoint",
        "ipython_bootstrap",
        "snapshot_policy",
        "subagent_policy",
        "system_prompt",
        "tool_policy",
    }
    old_id = candidate.manifest_id
    prompt = checkout / candidate.paths["system_prompt"]
    prompt.write_text(
        prompt.read_text(encoding="utf-8").replace("SUBTRACT", "ADD"),
        encoding="utf-8",
        newline="",
    )
    with pytest.raises(HarnessProtocolError, match="digest does not match"):
        load_candidate(checkout)
    refreshed = refresh_manifest(checkout)
    assert refreshed.manifest_id != old_id
    (checkout / "undeclared.txt").write_text("not a locus\n", encoding="utf-8")
    with pytest.raises(HarnessProtocolError, match="undeclared"):
        load_candidate(checkout)


def test_fixture_kernel_conformance_covers_lifecycle_and_resource_receipts() -> None:
    report = run_conformance(FIXTURE_RUNTIME, REFERENCE, allow_fixture=True)
    assert report["checks"] == [
        "boot",
        "execute",
        "snapshot",
        "restore",
        "interrupt",
        "timeout",
        "cleanup",
        "shutdown",
    ]
    assert report["isolation_enforced"] is False
    resources = cast(list[dict[str, object]], report["resources"])
    assert resources
    assert all(type(item["wall_milliseconds"]) is int for item in resources)


def test_reviewed_oci_profile_has_immutable_image_and_fail_closed_flags() -> None:
    runtime = load_runtime_manifest(OCI_RUNTIME)
    command = _docker_command(runtime, "test-container")
    assert runtime.image is not None and "@sha256:" in runtime.image
    assert command[1:4] == ["run", "--name", "test-container"]
    assert ["--network", "none"] == command[
        command.index("--network") : command.index("--network") + 2
    ]
    assert "--read-only" in command
    assert ["--cap-drop", "ALL"] == command[
        command.index("--cap-drop") : command.index("--cap-drop") + 2
    ]
    assert "no-new-privileges" in command
    assert "--pids-limit" in command
    assert "--memory" in command
    assert "--cpus" in command
    assert "--tmpfs" in command
    assert ["--ipc", "none"] == command[
        command.index("--ipc") : command.index("--ipc") + 2
    ]
    assert command.count("--ulimit") == 2
    assert "--user" in command
    with pytest.raises(KernelContractError, match="placeholder"):
        KernelSession(runtime, "", {}, allow_fixture=False)


def test_fixed_provider_translation_extracts_action_and_usage(
    tmp_path: Path,
) -> None:
    agent = tmp_path / "agent.py"
    agent.write_text(
        "import json,sys\n"
        "if '--version' in sys.argv:\n"
        " print('9.9.9')\n"
        " raise SystemExit(0)\n"
        "action={'action':'execute','code':'2 + 3'}\n"
        "message={'role':'assistant','content':[{'type':'text','text':json.dumps(action,separators=(',',':'),sort_keys=True)}],'usage':{'input':7,'output':5}}\n"
        "print(json.dumps({'type':'message_end','message':message},separators=(',',':'),sort_keys=True))\n",
        encoding="utf-8",
    )
    command = [sys.executable, str(agent)]
    verify_implementation(command, "9.9.9", "fixture agent")
    request = model_request("fixed system", "fixed prompt")
    response = invoke_model(
        canonical_json(request),
        agent_name="fixture agent",
        command_builder=lambda _: command,
    )
    assert response == {
        "action": {"action": "execute", "code": "2 + 3"},
        "protocol_version": 1,
        "usage": {"input_tokens": 7, "output_tokens": 5},
    }


def test_tool_free_proposer_applies_only_declared_locus_edits(tmp_path: Path) -> None:
    checkout = tmp_path / "candidate"
    shutil.copytree(REFERENCE, checkout)
    candidate = load_candidate(checkout)
    path = candidate.paths["system_prompt"]
    replacement = candidate.text("system_prompt").replace("SUBTRACT", "ADD")
    _apply_response(
        checkout,
        canonical_json(
            {
                "edits": [{"content": replacement, "path": path}],
                "reason": "bounded prompt mutation",
            }
        ),
    )
    assert "ARITHMETIC_POLICY=ADD" in load_candidate(checkout).text("system_prompt")
    with pytest.raises(ProposerError, match="declared locus"):
        _apply_response(
            checkout,
            canonical_json(
                {
                    "edits": [{"content": "x", "path": "outside.py"}],
                    "reason": "unsafe",
                }
            ),
        )


def test_real_harness_loop_supports_isolated_recursive_subagent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipts = tmp_path / "receipts"
    monkeypatch.setenv("METERING_HARNESS_RUNTIME_MANIFEST", str(FIXTURE_RUNTIME))
    monkeypatch.setenv("METERING_HARNESS_RECEIPT_DIR", str(receipts))
    monkeypatch.setenv("METERING_HARNESS_ALLOW_UNSAFE_FIXTURE", "1")
    monkeypatch.setenv(
        "METERING_HARNESS_MODEL_COMMAND",
        canonical_json([sys.executable, str(FIXTURES / "fixture_model.py")]),
    )
    source = canonical_json(
        {
            "candidate": {
                "artifact": {"entrypoint": "harness.json"},
                "candidate_id": "1" * 64,
                "checkout_path": str(REFERENCE),
            },
            "protocol_version": 1,
            "task": {
                "case_id": "recursive",
                "input": {
                    "outcomes": ["fail", "pass"],
                    "prompt": (
                        "USE_DELEGATE then compute left plus right for left=2 right=3."
                    ),
                },
            },
        }
    )
    response = execute(source)
    submission = cast(dict[str, object], response["submission"])
    assert submission["answer"] == -1
    metadata = cast(dict[str, object], submission["_metering_harness"])
    reference = cast(dict[str, object], metadata["receipt"])
    receipt = load_receipt(reference, receipts)
    usage = cast(dict[str, int], receipt["model_usage"])
    assert usage["calls"] == 4
    assert len(cast(list[object], receipt["kernel_observations"])) == 2
    completion = cast(dict[str, object], receipt["completion"])
    clean_submission = {
        name: value for name, value in submission.items() if name != "_metering_harness"
    }
    assert completion["result_sha256"] == completion_result_digest(
        response["forecast"], clean_submission
    )


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_one_command_fixture_evolves_harness_recurs_and_seals_final(
    tmp_path: Path,
) -> None:
    root = tmp_path / "experiment"
    report = run_experiment("fixture", root, None)
    development = cast(dict[str, object], report["development"])
    final = cast(dict[str, object], report["final"])
    assert development["status"] == "round_limit"
    assert development["completed_rounds"] == 2
    assert development["candidate_count"] == 3
    assert final["passed_count"] == final["task_count"] == 3
    assert (
        cast(dict[str, object], report["verified"])["final_evaluation_started"] is True
    )

    driver_records = _records(root / "state" / "driver.jsonl")
    assert [
        cast(dict[str, object], record["selection"])["decision"]
        for record in driver_records[1:]
    ] == ["promote_challenger", "retain_incumbent"]

    state = load_state(population_root(root / "state"))
    assert state.final_evaluation_started is True
    latest_archive_id = state.latest_archive_by_experiment[
        str(development["experiment_id"])
    ]
    members = cast(
        list[dict[str, object]],
        cast(dict[str, object], state.record(latest_archive_id)["body"])["members"],
    )
    assert [member["candidate_id"] for member in members] == [final["candidate_id"]]
    selected = state.candidates[str(final["candidate_id"])]
    artifact = cast(dict[str, object], selected["artifact"])
    completed = subprocess.run(
        [
            "git",
            f"--git-dir={root / 'candidate.git'}",
            "show",
            f"{artifact['commit']}:system-prompt.txt",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert "ARITHMETIC_POLICY=ADD" in completed.stdout

    verified = verify_experiment(root)
    assert verified["status"] == "verified"
    assert verified["final_run_count"] == 1
    assert int(verified["harness_receipt_count"]) >= 15

    run_receipt = next(
        path
        for path in (root / "receipts").glob("*.json")
        if '"receipt_schema":"evolutionary-harness-run-receipt-v1"'
        in path.read_text(encoding="ascii")
    )
    run_receipt.unlink()
    with pytest.raises(HarnessReceiptError, match="cannot read harness receipt"):
        verify_experiment(root)
