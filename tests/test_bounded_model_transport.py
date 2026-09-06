"""Streaming caps and cancellation for owned model subprocesses, without inference."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.bounded_process import communicate_bounded  # noqa: E402
from apps.harness.model_contract import (  # noqa: E402
    ModelContractError,
    SubprocessModelTransport,
    model_request,
)
from connectors.fixed.harness_model_runtime import (  # noqa: E402
    HarnessModelAdapterError,
    invoke_model,
)


@pytest.mark.parametrize("stream", [1, 2])
def test_model_output_limit_is_enforced_while_process_is_running(stream):
    transport = SubprocessModelTransport(
        [
            sys.executable,
            "-c",
            f"import os,time; os.write({stream}, b'x'*131072); time.sleep(30)",
        ],
        timeout_seconds=1,
        max_response_bytes=1024,
    )
    with pytest.raises(ModelContractError, match="response byte limit"):
        transport.call("system", "prompt")


def test_model_transport_drains_output_while_writing_large_input():
    response = {
        "action": {"type": "submit", "submission": {"answer": 3}},
        "protocol_version": 1,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    script = (
        "import sys\n"
        "sys.stdout.write(' '*70000); sys.stdout.flush()\n"
        "sys.stdin.read()\n"
        f"sys.stdout.write({json.dumps(response)!r})\n"
    )
    transport = SubprocessModelTransport(
        [sys.executable, "-c", script],
        timeout_seconds=5,
        max_response_bytes=131072,
    )
    reply = transport.call("system", "p" * 100000)
    assert reply.action == response["action"]


def test_timeout_kills_descendants_that_hold_output_open(tmp_path):
    pid_path = tmp_path / "pid"
    child = f"import os,time; open({str(pid_path)!r},'w').write(str(os.getpid())); time.sleep(30)"
    parent = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}])"
    transport = SubprocessModelTransport(
        [sys.executable, "-c", parent],
        timeout_seconds=1,
        max_response_bytes=1024,
    )
    with pytest.raises(ModelContractError, match="timeout"):
        transport.call("system", "prompt")
    pid = int(pid_path.read_text())
    for _ in range(100):
        proc = Path(f"/proc/{pid}/stat")
        if not proc.exists() or proc.read_text().split()[2] == "Z":
            break
        time.sleep(0.01)
    else:
        pytest.fail("model transport left a running descendant after timeout")


@pytest.mark.parametrize("stream", [1, 2])
def test_nested_provider_output_is_bounded_before_timeout(monkeypatch, stream):
    monkeypatch.setenv("METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES", "1024")
    monkeypatch.setenv("METERING_HARNESS_MODEL_TIMEOUT", "1")
    command = [
        sys.executable,
        "-c",
        f"import os,time; os.write({stream},b'x'*131072); time.sleep(30)",
    ]
    with pytest.raises(HarnessModelAdapterError, match="output byte limit"):
        invoke_model(
            json.dumps(model_request("system", "prompt")),
            agent_name="fixture",
            command_builder=lambda request: command,
        )


def test_cancellation_reaps_owned_child_and_closes_pipes(monkeypatch):
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    def cancelled(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("selectors.DefaultSelector.select", cancelled)
    with pytest.raises(KeyboardInterrupt):
        communicate_bounded(process, b"input", timeout_seconds=1, max_output_bytes=1024)
    assert process.poll() is not None
    assert all(
        stream.closed for stream in (process.stdin, process.stdout, process.stderr)
    )


def test_invalid_utf8_is_a_typed_model_transport_failure():
    transport = SubprocessModelTransport(
        [sys.executable, "-c", "import os; os.write(1,b'\\xff')"],
        timeout_seconds=1,
        max_response_bytes=1024,
    )
    with pytest.raises(ModelContractError, match="UTF-8"):
        transport.call("system", "prompt")


def test_model_exit_diagnostic_retains_status_and_redacts_credentials():
    transport = SubprocessModelTransport(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('password=private-credential'); sys.exit(19)",
        ],
        timeout_seconds=1,
        max_response_bytes=1024,
    )
    with pytest.raises(ModelContractError, match="19") as error:
        transport.call("system", "prompt")
    assert "private-credential" not in str(error.value)


def test_observer_start_failure_does_not_leave_model_process_running(monkeypatch):
    original = subprocess.Popen
    owned = []

    def tracked(*args, **kwargs):
        process = original(*args, **kwargs)
        owned.append(process)
        return process

    def unavailable(*args, **kwargs):
        raise RuntimeError("observer unavailable")

    monkeypatch.setattr("apps.harness.model_contract.subprocess.Popen", tracked)
    monkeypatch.setattr("apps.harness.model_contract.ResourceObserver", unavailable)
    transport = SubprocessModelTransport(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_seconds=1,
        max_response_bytes=1024,
    )
    with pytest.raises(RuntimeError, match="observer unavailable"):
        transport.call("system", "prompt")
    assert len(owned) == 1 and owned[0].poll() is not None
    assert all(
        stream.closed for stream in (owned[0].stdin, owned[0].stdout, owned[0].stderr)
    )
