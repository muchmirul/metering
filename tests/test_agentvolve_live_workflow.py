"""Opt-in deployed-Pi acceptance under one explicitly pinned worker runtime."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Fail on inspection dependency errors before launching any live work.
from apps._support.wire import canonical_json  # noqa: E402
from apps.coding_agent.protocol import load_task_profile  # noqa: E402
from apps.coding_agent.candidate_view import report_view, tree_view  # noqa: E402
from apps.coding_agent.file_view import path_key  # noqa: E402
from apps.coding_agent.trace_view import TraceSnapshot  # noqa: E402
from apps.coding_agent.pi_execution import bounded_file  # noqa: E402
from connectors.fixed.pi.live_gate import preflight, require_live_approval  # noqa: E402

EXTENSION = ROOT / ".pi" / "extensions" / "population-evolution.ts"
SOLUTION = ROOT / "apps" / "coding_agent" / "solution_experiment.py"
DEFAULT_RUNTIME = (
    Path.home() / ".config" / "metering" / "harness" / "runtime.pi.local.json"
)


def required_path(name: str, fallback: Path | None = None) -> Path:
    raw = os.environ.get(name)
    path = Path(raw).expanduser().absolute() if raw else fallback
    assert path is not None and path.is_file(), f"{name} must name an existing file"
    return path


def require_approved_contract(directory: Path, expected: dict) -> None:
    matching = []
    for path in directory.glob("*.task.json"):
        task = load_task_profile(path)
        del task["task_id"]
        if task["goal"] == expected["goal"]:
            matching.append(canonical_json(task))
    assert matching == [canonical_json(expected)], "Prepared contract differs from the operator-approved profile"


def rpc_request(
    process: subprocess.Popen[str],
    request: dict[str, Any],
    *,
    timeout: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assert process.stdin is not None
    assert process.stdout is not None
    request_id = str(request["id"])
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    deadline = time.monotonic() + timeout
    events: list[dict[str, Any]] = []
    buffer = getattr(process, "_agentvolve_rpc_buffer", b"")
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"Pi RPC exited with {process.returncode}: {stderr}")
        if b"\n" not in buffer:
            ready, _, _ = select.select(
                [process.stdout], [], [], max(0.0, min(1.0, deadline - time.monotonic()))
            )
            if not ready:
                continue
            buffer += os.read(process.stdout.fileno(), 65536)
            if b"\n" not in buffer:
                continue
        line, buffer = buffer.split(b"\n", 1)
        event = json.loads(line)
        events.append(event)
        if event.get("type") == "extension_ui_request" and event.get("method") == "confirm":
            # This opt-in test is authorized only for the exact operator-approved profile.
            expected_execution = getattr(process, "_agentvolve_reviewed_execution")
            marker = "Delegated worker execution (not the interactive model):\n"
            assert marker in event["message"]
            actual_execution, _ = json.JSONDecoder().raw_decode(event["message"].split(marker, 1)[1])
            assert canonical_json(actual_execution) == canonical_json(expected_execution), "Worker execution differs from the approved live setup"
            if event["title"] == "Save Agentvolve worker configuration for this session?":
                process.stdin.write(json.dumps({"type": "extension_ui_response", "id": event["id"], "confirmed": True}) + "\n")
                process.stdin.flush()
                continue
            assert event["title"] == "Run this reviewed Agentvolve task?", event
            expected_goal = getattr(process, "_agentvolve_reviewed_goal")
            expected_rounds = getattr(process, "_agentvolve_reviewed_rounds")
            assert json.dumps(expected_goal, ensure_ascii=False) in event["message"]
            assert f"{expected_rounds} generations" in event["message"]
            # Goal/round labels alone do not authorize different checks, paths,
            # budgets or a moved base. Match the entire freshly derived contract
            # to the preapproved source before returning any positive approval.
            require_approved_contract(getattr(process, "_agentvolve_prepared_directory"), getattr(process, "_agentvolve_reviewed_contract"))
            process.stdin.write(json.dumps({"type": "extension_ui_response", "id": event["id"], "confirmed": True}) + "\n")
            process.stdin.flush()
        elif event.get("type") == "extension_ui_request" and event.get("method") == "input" and event.get("title", "").startswith("Enter the exact"):
            process.stdin.write(json.dumps({"type": "extension_ui_response", "id": event["id"], "value": str(getattr(process, "_agentvolve_reviewed_rounds"))}) + "\n")
            process.stdin.flush()
        elif event.get("type") == "extension_ui_request" and event.get("method") == "select" and event.get("title") in {"Choose Agentvolve worker setup (no job starts)", "Agentvolve setup needs preparation"}:
            approved = getattr(process, "_agentvolve_reviewed_execution")
            paths = getattr(process, "_agentvolve_execution_paths")
            fragment = f"{approved['model']['provider']}/{approved['model']['model']} · Pi {approved['implementation_version']} · harness {approved['harness_candidate_id'][:12]}"
            matches = [option for option in event['options'] if fragment in option]
            conventional = paths['manifest'] == str(DEFAULT_RUNTIME) and paths['configuration'] == str(Path.home() / '.config/metering/agentvolve-worker')
            selected = matches[0] if len(matches) == 1 and conventional else 'Enter existing paths (advanced)'
            assert selected in event['options']
            process.stdin.write(json.dumps({'type': 'extension_ui_response', 'id': event['id'], 'value': selected}) + '\n')
            process.stdin.flush()
        elif event.get("type") == "extension_ui_request" and event.get("method") == "input" and event.get("title", "").startswith("Agentvolve"):
            title = event['title']
            key = ('manifest' if title.startswith('Agentvolve worker runtime') else
                   'harness' if title.startswith('Agentvolve compatible sealed') else
                   'configuration' if title.startswith('Agentvolve separate worker Pi configuration') else 'runs')
            assert title.startswith(('Agentvolve worker runtime', 'Agentvolve compatible sealed', 'Agentvolve separate worker Pi configuration'))
            process.stdin.write(json.dumps({'type': 'extension_ui_response', 'id': event['id'], 'value': getattr(process, '_agentvolve_execution_paths')[key]}) + '\n')
            process.stdin.flush()
        elif event.get("type") == "extension_ui_request" and event.get("method") in {"input", "select", "editor"}:
            raise AssertionError(f"unexpected task ambiguity in approved live fixture: {event}")
        if event.get("type") == "response" and event.get("id") == request_id:
            setattr(process, "_agentvolve_rpc_buffer", buffer)
            return event, events
    raise AssertionError(f"timed out waiting for Pi RPC response {request_id!r}")


def rpc_prompt(
    process: subprocess.Popen[str],
    request_id: str,
    text: str,
    *,
    timeout: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return rpc_request(
        process,
        {"type": "prompt", "id": request_id, "message": text},
        timeout=timeout,
    )


def check_ordinary_shell(process: subprocess.Popen[str], request_id: str) -> None:
    # RPC prompt accepts !text as a model prompt; only the bash command is a
    # no-inference shell action. Acceptance must inspect output, not acceptance.
    response, events = rpc_request(process, {'type': 'bash', 'id': request_id,
                                           'command': 'printf agentvolve-ordinary-tools-ok'}, timeout=120)
    assert response.get('success') is True, response
    assert response['data']['exitCode'] == 0
    assert response['data']['output'] == 'agentvolve-ordinary-tools-ok'
    assert not any(event.get('type') in {'agent_start', 'extension_error'} for event in events)


def close_rpc(process: subprocess.Popen[str]) -> None:
    if process.stdin is not None:
        process.stdin.close()
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def workflow_error(events: list[dict[str, Any]]) -> str:
    messages = [
        str(event.get("message", ""))
        for event in events
        if event.get("type") == "extension_ui_request"
        and event.get("method") == "notify"
        and event.get("notifyType") == "error"
    ]
    return "\n".join(messages)


@pytest.mark.live_agents
@pytest.mark.skipif(
    os.environ.get("METERING_RUN_AGENTVOLVE_E2E") != "1" and os.environ.get("METERING_REQUIRE_AGENTVOLVE_E2E") != "1",
    reason="set METERING_RUN_AGENTVOLVE_E2E=1 for approved multi-task real inference",
)
def test_deployed_agentvolve_solves_and_verifies_approved_tasks(
    tmp_path: Path,
) -> None:
    require_live_approval()
    profiles = [
        Path(value).expanduser().absolute()
        for value in os.environ.get("METERING_EVOLUTION_LIVE_TASK_PROFILES", "").split(
            os.pathsep
        )
        if value
    ]
    assert len(profiles) >= 3, (
        "METERING_EVOLUTION_LIVE_TASK_PROFILES must contain at least three "
        f"operator-approved profiles separated by {os.pathsep!r}"
    )
    assert all(path.is_file() for path in profiles)
    runtime = required_path("METERING_EVOLUTION_RUNTIME_MANIFEST", DEFAULT_RUNTIME)
    harness = required_path("METERING_EVOLUTION_LIVE_HARNESS")
    runtime_document = json.loads(runtime.read_text(encoding="ascii"))
    assert runtime_document["model"]["connector"] == "pi-v1"
    expected_provider = os.environ.get("METERING_EVOLUTION_LIVE_PROVIDER", "llamacpp")
    assert runtime_document["model"]["provider"] == expected_provider
    configuration = Path(os.environ.get('METERING_PI_CONFIG_DIR', str(Path.home() / '.config/metering/agentvolve-worker'))).expanduser().absolute()
    shared_runs = os.environ.get('METERING_EVOLUTION_LIVE_RUNS_DIR')
    assert shared_runs, '[registry-selection-missing] Explicitly select a persistent acceptance registry; never rerun interrupted work in a new temporary directory.'
    runs_directory = Path(shared_runs).expanduser().absolute()
    # Check ALL contracts and runtime prerequisites before the first live task.
    approved_tasks = [load_task_profile(path) for path in profiles]
    gate = preflight(profiles, runtime, harness, configuration, runs_directory, expected_provider=expected_provider)
    assert gate['task_ids'] == [task['task_id'] for task in approved_tasks], 'Approved profiles changed during preflight'
    operator_configuration = tmp_path / 'operator-config'
    operator_configuration.mkdir(mode=0o700)
    (operator_configuration / 'models.json').write_bytes(bounded_file(configuration / 'models.json'))
    (operator_configuration / 'models.json').chmod(0o600)
    operator_environment = {**os.environ, 'PI_CODING_AGENT_DIR': str(operator_configuration)}
    pi_bin = os.environ.get("METERING_EVOLUTION_OPERATOR_PI_BIN", "pi")
    deployed = subprocess.run(
        [pi_bin, '--offline', '--no-extensions', '-e', str(EXTENSION), "--list-models"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=operator_environment,
    )
    assert deployed.returncode == 0, deployed.stderr
    assert expected_provider in deployed.stdout

    tasks_directory = tmp_path / "tasks"
    tasks_directory.mkdir()
    for index, profile in enumerate(profiles):
        shutil.copy2(profile, tasks_directory / f"task-{index}.task.json")
    runs_directory.mkdir(parents=True, exist_ok=True)
    # Use the same explicitly selected registry for multi-runtime batches. A
    # pending run still blocks the next task; never create a new registry to bypass it.

    for index, source_profile in enumerate(profiles):
        profile = dict(approved_tasks[index])
        assert load_task_profile(source_profile)['task_id'] == profile.pop('task_id'), 'Approved profile changed before dispatch'
        repository = Path(profile["repository"]["path"])
        goal = str(profile["goal"])
        rounds = int(profile["limits"]["max_rounds"])
        before = set(runs_directory.glob("workflow-pi-*"))
        environment = {
            **{key: value for key, value in operator_environment.items() if key not in {'METERING_PI_CONFIG_DIR', 'METERING_EVOLUTION_HARNESS_DESCRIPTOR', 'METERING_EVOLUTION_RUNTIME_MANIFEST'}},
            "METERING_EVOLUTION_RUNS_DIR": str(runs_directory),
            "METERING_EVOLUTION_TASKS_DIR": str(tasks_directory),
            "METERING_EVOLUTION_TASK_PROFILE": str(source_profile),
        }
        process = subprocess.Popen(
            [pi_bin, '--offline', "--mode", "rpc", "--no-session", '--no-extensions', '--no-skills', '--no-context-files', '--no-prompt-templates', '-e', str(EXTENSION)],
            cwd=repository,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=environment,
        )
        setattr(process, '_agentvolve_reviewed_execution', gate['review'])
        setattr(process, '_agentvolve_execution_paths', {'manifest': str(runtime), 'harness': str(harness), 'configuration': str(configuration), 'runs': str(runs_directory)})
        setattr(process, "_agentvolve_reviewed_goal", goal)
        setattr(process, "_agentvolve_reviewed_rounds", rounds)
        setattr(process, "_agentvolve_reviewed_contract", profile)
        setattr(process, "_agentvolve_prepared_directory", tasks_directory / "generated")
        try:
            limit_response, limit_events = rpc_prompt(
                process,
                f"limit-{index}",
                f"/limit {rounds} generations",
                timeout=120,
            )
            assert limit_response.get("success") is True, limit_response
            assert not workflow_error(limit_events), workflow_error(limit_events)
            run_response, run_events = rpc_prompt(
                process, f"run-{index}", f"/goal {goal}", timeout=600
            )
            assert run_response.get("success") is True, run_response
            assert not workflow_error(run_events), workflow_error(run_events)
            assert any(event.get("method") == "confirm" for event in run_events)

            created = set(runs_directory.glob("workflow-pi-*")) - before
            assert len(created) == 1, workflow_error(run_events)
            workflow_root = created.pop()
            request = json.loads((workflow_root / "workflow.json").read_text())
            assert request['workflow_schema'] == 'agentvolve-worker-request-v2'
            assert request['pi_execution']['models_sha256'] == gate['review']['worker_models_sha256']
            assert Path(request['pi_execution']['configuration_directory']).parent == workflow_root
            # A user shell action remains available while the detached job runs.
            check_ordinary_shell(process, f'ordinary-{index}')
            run_root = Path(request["solution_run_root"])
            deadline = time.monotonic() + 2 * 60 * 60
            while True:
                status = json.loads((workflow_root / "worker-status.json").read_text())
                if status["state"] in {"completed", "verified"}:
                    break
                assert time.monotonic() < deadline, status
                assert status['state'] != 'waiting-retry', f'[reviewed-recovery-required] Preserve {workflow_root}; inspect this exact job and obtain direct recovery approval. No automatic retry. {status}'
                assert status["state"] in {"queued", "running"}, status
                time.sleep(2)

            report = json.loads(
                (run_root / "experiment-report.json").read_text(encoding="ascii")
            )
            assert report["final"]["passed_count"] == report["final"]["task_count"]
            entries_response, _ = rpc_request(
                process,
                {"type": "get_entries", "id": f"entries-{index}"},
                timeout=120,
            )
            owned = [entry['data'] for entry in entries_response['data']['entries'] if entry.get('customType') == 'agentvolve-submission'][-1]
            assert owned['state'] == 'launched' and owned['workflow']['workflow_id'] == request['workflow_id']
            assert owned['workflow']['workflow_root'] == str(workflow_root)
            setups = [entry['data'] for entry in entries_response['data']['entries'] if entry.get('customType') == 'agentvolve-execution-configuration']
            assert setups and setups[-1]['configuration'] == str(configuration)
            configurations = [
                entry["data"]
                for entry in entries_response["data"]["entries"]
                if entry.get("type") == "custom"
                and entry.get("customType")
                == "agentvolve-workflow-configuration"
            ]
            assert configurations[-1] == {"maxRounds": rounds, "repository": str(repository)}
            assert (run_root / "selected-solution.json").is_file()
            assert (run_root / "selected.patch").is_file()

            verified = subprocess.run(
                [sys.executable, str(SOLUTION), "verify", str(run_root)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
                env=environment,
            )
            assert verified.returncode == 0, verified.stderr
            assert json.loads(verified.stdout)["status"] == "verified"

            # Inspect actual model descendants, not a synthetic projection fixture.
            nodes = []
            offset = 0
            while True:
                page = tree_view(runs_directory, workflow_root.name, offset)
                nodes.extend(page["items"])
                if page["next_offset"] is None:
                    break
                offset = page["next_offset"]
            assert any(node["label"].startswith("S") and node["parent_label"] for node in nodes)
            assert any(node["label"].startswith("H") and node["reused"] for node in nodes)
            for node in nodes:
                event_offset = 0
                diff_offset = 0
                while True:
                    candidate = report_view(runs_directory, workflow_root.name, node["label"], event_offset, diff_offset)
                    assert candidate["node"]["candidate_id"] == node["candidate_id"]
                    if node["status"] != "selected":
                        assert candidate["evidence"]["final"] is None
                    if node["parent_label"]:
                        assert candidate["diff"]["available"], candidate["diff"]
                    if candidate["next_offset"] is not None:
                        event_offset = candidate["next_offset"]
                    elif candidate["diff"]["next_offset"] is not None:
                        diff_offset = candidate["diff"]["next_offset"]
                    else:
                        break
            selected = next(node for node in nodes if node["kind"] == "solution" and node["status"] == "selected")
            assert selected["candidate_id"] == report["selected_solution"]["candidate_id"]

            # The graphical trace must resolve the actual model commits and files.
            trace = TraceSnapshot(runs_directory, workflow_root.name)
            assert {node["candidate_id"] for node in trace.graph()["nodes"]} == {node["candidate_id"] for node in nodes}
            for node in nodes:
                files = trace.files[node["kind"]]
                inventory = files.inventory(node["candidate_id"])
                assert inventory
                entrypoint = path_key(node["entrypoint"].encode("utf-8"))
                assert entrypoint in inventory
                assert isinstance(files.blob(node["candidate_id"], entrypoint), bytes)
                history = trace.file_history(node["kind"], entrypoint)
                assert any(item["candidate_id"] == node["candidate_id"] and item["file"] for item in history["items"])
        finally:
            close_rpc(process)
