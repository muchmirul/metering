"""Typed harness, isolation, recursion, recurrence, and final-sealing tests."""

from __future__ import annotations

import hashlib
import json
import os
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
import apps.harness.experiment_config as harness_config  # noqa: E402
from apps.harness.experiment import (  # noqa: E402
    ExperimentError,
    continue_experiment,
    harness_process_status,
    run_experiment,
    verify_experiment,
)
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
from apps.harness.resources import _io_writes  # noqa: E402
from apps.harness.runtime_manifest import load_runtime_manifest  # noqa: E402
from apps.harness.workspace import (  # noqa: E402
    WorkspaceError,
    decode_files,
    snapshot_directory,
)
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


def test_empty_cgroup_io_stat_is_observed_zero_physical_writes(
    tmp_path: Path,
) -> None:
    (tmp_path / "io.stat").write_text("", encoding="ascii")
    assert _io_writes(tmp_path) == 0
    (tmp_path / "io.stat").write_text(
        "8:0 rbytes=12 wbytes=7 rios=1 wios=1\n", encoding="ascii"
    )
    assert _io_writes(tmp_path) == 7


def test_kernel_workspace_routes_edits_and_commands_through_isolation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "solver.py").write_text("print('old')\n", encoding="utf-8")
    files = snapshot_directory(source)
    policy = {
        "allowed_write_paths": ["solver.py"],
        "command_timeout_ms": 5_000,
        "max_bytes": 65_536,
        "max_files": 8,
        "max_output_characters": 4_096,
    }
    runtime = load_runtime_manifest(FIXTURE_RUNTIME)
    snapshot_policy = load_candidate(REFERENCE).policy("snapshot_policy")
    with KernelSession(
        runtime, "x = 1\n", snapshot_policy, allow_fixture=True
    ) as session:
        initialized = session.initialize_workspace(files, policy)
        assert initialized["file_count"] == 1
        execution = session.execute(
            "write_file('solver.py', \"print('new')\\n\")",
            timeout_ms=5_000,
        )
        assert execution.status == "ok"
        result = session.run_workspace_command(
            [sys.executable, "solver.py"], timeout_ms=5_000
        )
        assert result == {
            "returncode": 0,
            "stderr": "",
            "stdout": "new\n",
            "timed_out": False,
        }
        exported = session.export_workspace()
        assert exported["changed_paths"] == ["solver.py"]
        rejected = session.execute(
            "write_file('forbidden.py', 'bad')", timeout_ms=5_000
        )
        assert rejected.status == "error"
        assert "not writable" in str(rejected.error)
        timed_out = session.run_workspace_command(
            [sys.executable, "-c", "import time; time.sleep(1)"], timeout_ms=10
        )
        assert timed_out["timed_out"] is True
        bypass = session.execute(
            "from pathlib import Path; "
            "Path(workspace_root, 'forbidden.py').write_text('bad')",
            timeout_ms=5_000,
        )
        assert bypass.status == "ok"
        with pytest.raises(KernelContractError, match="changed disallowed path"):
            session.export_workspace()


def test_workspace_archive_rejects_traversal_links_and_non_regular_entries(
    tmp_path: Path,
) -> None:
    with pytest.raises(WorkspaceError, match="normalized relative POSIX"):
        decode_files(
            [
                {
                    "content_base64": "eA==",
                    "executable": False,
                    "path": "../escape.py",
                }
            ]
        )
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.py").write_text("pass\n", encoding="utf-8")
    (source / "link.py").symlink_to("file.py")
    with pytest.raises(WorkspaceError, match="symlink"):
        snapshot_directory(source)
    (source / "link.py").unlink()
    os.mkfifo(source / "pipe")
    with pytest.raises(WorkspaceError, match="non-regular"):
        snapshot_directory(source)


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
    assert runtime.max_output_bytes == 4_194_304
    containerfile = (OCI_RUNTIME.parent / "Containerfile").read_text(encoding="utf-8")
    assert "COPY --chmod" not in containerfile
    assert "RUN chmod 0555 /opt/metering/kernel_server.py" in containerfile
    command = _docker_command(runtime, "test-container")
    assert runtime.image is not None and "@sha256:" in runtime.image
    assert command[1:6] == [
        "run",
        "--pull",
        "never",
        "--name",
        "test-container",
    ]
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
    assert "--memory-swap" in command
    assert command[command.index("--memory-swap") + 1] == str(
        runtime.limits.memory_bytes
    )
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
    with pytest.raises(ProposerError, match="exactly one locus"):
        _apply_response(
            checkout,
            canonical_json(
                {
                    "edits": [
                        {"content": replacement, "path": path},
                        {
                            "content": candidate.text("context_policy"),
                            "path": candidate.paths["context_policy"],
                        },
                    ],
                    "reason": "too broad",
                }
            ),
        )
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


def test_harness_resume_does_not_repeat_model_call_and_reserved_retry_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counter = tmp_path / "calls.txt"
    wrapper = tmp_path / "fail-once.py"
    original = harness_config.FIXTURE_PROPOSER
    wrapper.write_text(
        "import os,sys\n"
        "from pathlib import Path\n"
        "counter=Path(os.environ['HARNESS_TEST_CALL_COUNTER'])\n"
        "counter.write_text(counter.read_text()+'x' if counter.exists() else 'x')\n"
        "marker=Path(os.environ['METERING_GIT_REPOSITORY']).parent/'proposal.attempt'\n"
        "if marker.exists():\n"
        " os.execv(sys.executable,[sys.executable,os.environ['HARNESS_TEST_PROPOSER']])\n"
        "marker.write_text('failed-once')\n"
        "sys.stdin.read()\n"
        "raise SystemExit(17)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HARNESS_TEST_CALL_COUNTER", str(counter))
    monkeypatch.setenv("HARNESS_TEST_PROPOSER", str(original))
    monkeypatch.setattr(harness_config, "FIXTURE_PROPOSER", wrapper)
    root = tmp_path / "interrupted"
    with pytest.raises(ExperimentError, match="explicit pending intent"):
        run_experiment("fixture", root, None, assay="coding-agent-v1")
    assert counter.read_text() == "x"
    assert not (root / "assay.json").exists()
    assert harness_process_status(root)["display"] == "[2/6] Evolving harness"
    with pytest.raises(ExperimentError, match="explicit pending intent"):
        continue_experiment(root)
    assert counter.read_text() == "x"
    report = continue_experiment(root, retry_reason="reviewed fixture failure")
    assert counter.read_text() == "xxx"
    retry_receipts = list((root / "state" / "retry-effects").glob("*.json"))
    assert len(retry_receipts) == 1
    retry_document = json.loads(retry_receipts[0].read_text(encoding="ascii"))
    assert (
        retry_document["retry_effects_schema"]
        == "evolutionary-harness-retry-effects-v2"
    )
    retry_id = hashlib.sha256(retry_receipts[0].read_bytes()).hexdigest()
    driver_round = json.loads(
        (root / "state" / "driver.jsonl").read_text(encoding="ascii").splitlines()[1]
    )
    assert driver_round["attempts"][1]["reason"].endswith(
        f"\nretry-effects-sha256:{retry_id}"
    )
    assert cast(dict[str, object], report["final"])["passed_count"] == 3
    assert verify_experiment(root)["status"] == "verified"
    assert continue_experiment(root) == report
    retry_document["retry_effects_schema"] = "evolutionary-harness-retry-effects-v1"
    retry_receipts[0].write_text(
        canonical_json(retry_document) + "\n", encoding="ascii", newline=""
    )
    with pytest.raises(ExperimentError, match="schema was downgraded"):
        verify_experiment(root)


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
