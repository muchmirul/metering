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

from apps._support.bounded_process import (  # noqa: E402
    OutputLimitError,
    communicate_bounded,
)
from apps._support.wire import canonical_json  # noqa: E402
from apps.harness.model_contract import (  # noqa: E402
    ModelContractError,
    SubprocessModelTransport,
    model_request,
)
from connectors.fixed.harness_model_runtime import (  # noqa: E402
    HarnessModelAdapterError,
    invoke_model,
)
from connectors.fixed.pi import harness_model as pi_harness_model  # noqa: E402


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


def test_line_filter_bounds_exact_records_and_retained_aggregate():
    exact = subprocess.Popen(
        [sys.executable, "-c", "import os; os.write(1,b'x'*1023+b'\\n')"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    stdout, stderr = communicate_bounded(
        exact,
        None,
        timeout_seconds=1,
        max_output_bytes=1024,
        stdout_line_filter=lambda _line: None,
    )
    assert stdout == stderr == ""

    oversized = subprocess.Popen(
        [sys.executable, "-c", "import os; os.write(1,b'x'*1024+b'\\n')"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    with pytest.raises(OutputLimitError, match="stdout"):
        communicate_bounded(
            oversized,
            None,
            timeout_seconds=1,
            max_output_bytes=1024,
            stdout_line_filter=lambda _line: None,
        )

    aggregate = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os; os.write(1,(b'x'*599+b'\\n')*2)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    with pytest.raises(OutputLimitError, match="stdout"):
        communicate_bounded(
            aggregate,
            None,
            timeout_seconds=1,
            max_output_bytes=1024,
            stdout_line_filter=lambda line: line,
        )


def test_line_filter_exception_reaps_process_and_closes_pipes():
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,time; os.write(1,b'event\\n'); time.sleep(30)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    def reject(_line):
        raise HarnessModelAdapterError("invalid event")

    with pytest.raises(HarnessModelAdapterError, match="invalid event"):
        communicate_bounded(
            process,
            None,
            timeout_seconds=1,
            max_output_bytes=1024,
            stdout_line_filter=reject,
        )
    assert process.poll() is not None
    assert all(
        stream.closed for stream in (process.stdin, process.stdout, process.stderr)
    )


def test_nested_provider_discards_bounded_json_update_framing(monkeypatch):
    monkeypatch.setenv("METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES", "1024")
    monkeypatch.setenv("METERING_HARNESS_MODEL_TIMEOUT", "5")
    action = {"type": "finish", "result": {"answer": 3}}
    message = {
        "role": "assistant",
        "content": [{"type": "text", "text": json.dumps(action)}],
        "usage": {"input": 7, "output": 5},
    }
    script = (
        "import json\n"
        "update={'type':'message_update','usage':{'input':7,'output':0},"
        "'assistantMessageEvent':{'type':'thinking_delta','contentIndex':0,'delta':'x'*64}}\n"
        "for _ in range(64): print(json.dumps(update,separators=(',',':')))\n"
        f"print(json.dumps({{'type':'message_end','message':{message!r}}},separators=(',',':')))\n"
    )
    request = json.dumps(model_request("system", "prompt"))

    def command_builder(_request):
        return [sys.executable, "-c", script]

    with pytest.raises(HarnessModelAdapterError, match="output byte limit"):
        invoke_model(
            request,
            agent_name="fixture",
            command_builder=command_builder,
        )
    response = invoke_model(
        request,
        agent_name="fixture",
        command_builder=command_builder,
        incremental_json_events=True,
    )
    assert response == {
        "action": action,
        "protocol_version": 1,
        "usage": {"input_tokens": 7, "output_tokens": 5},
    }


def test_incremental_provider_retains_only_last_assistant_end(monkeypatch):
    monkeypatch.setenv("METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES", "1024")
    first = {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "x" * 800}],
            "usage": {"input": 1, "output": 1},
        },
    }
    action = {"type": "finish", "result": {"answer": 7}}
    second = {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": json.dumps(action)}],
            "usage": {"input": 9, "output": 4},
        },
    }
    first_line = json.dumps(first, separators=(",", ":")).encode() + b"\r\n"
    second_line = json.dumps(second, separators=(",", ":")).encode()
    assert len(first_line) <= 1024 and len(second_line) <= 1024
    assert len(first_line) + len(second_line) > 1024
    script = (
        "import os\n"
        f"first={first_line!r}; second={second_line!r}\n"
        "os.write(1,first); os.write(1,second[:17]); os.write(1,second[17:])\n"
    )
    response = invoke_model(
        json.dumps(model_request("system", "prompt")),
        agent_name="fixture",
        command_builder=lambda request: [sys.executable, "-c", script],
        incremental_json_events=True,
    )
    assert response["action"] == action
    assert response["usage"] == {"input_tokens": 9, "output_tokens": 4}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"[]\n", "must be an object"),
        (b"\xff\n", "JSON event 1 is invalid"),
        (b'{"usage":NaN}\n', "JSON event 1 is invalid"),
    ],
)
def test_incremental_provider_rejects_nonobject_or_non_utf8_event(
    monkeypatch, payload, message
):
    monkeypatch.setenv("METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES", "1024")
    script = f"import os; os.write(1,{payload!r})"
    with pytest.raises(HarnessModelAdapterError, match=message):
        invoke_model(
            json.dumps(model_request("system", "prompt")),
            agent_name="fixture",
            command_builder=lambda request: [sys.executable, "-c", script],
            incremental_json_events=True,
        )


def test_nested_provider_rejects_malformed_discarded_json_event(monkeypatch):
    monkeypatch.setenv("METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES", "1024")
    command = [sys.executable, "-c", "print('not-json')"]
    with pytest.raises(HarnessModelAdapterError, match="JSON event 1 is invalid"):
        invoke_model(
            json.dumps(model_request("system", "prompt")),
            agent_name="fixture",
            command_builder=lambda request: command,
            incremental_json_events=True,
        )


@pytest.mark.parametrize(
    "event_type", ["message_update", "message_end", "unterminated_update"]
)
def test_incremental_provider_rejects_one_oversized_json_event(monkeypatch, event_type):
    monkeypatch.setenv("METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES", "1024")
    if event_type in {"message_update", "unterminated_update"}:
        event = {
            "type": "message_update",
            "usage": {"input": 1, "output": 1},
            "assistantMessageEvent": {
                "type": "thinking_delta",
                "contentIndex": 0,
                "delta": "x" * 2048,
            },
        }
    else:
        event = {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "x" * 2048}],
                "usage": {"input": 1, "output": 1},
            },
        }
    script = (
        f"import json,os; payload=json.dumps({event!r},separators=(',',':')).encode(); "
        + (
            "os.write(1,payload)"
            if event_type == "unterminated_update"
            else "print(payload.decode())"
        )
    )
    with pytest.raises(HarnessModelAdapterError, match="output byte limit"):
        invoke_model(
            json.dumps(model_request("system", "prompt")),
            agent_name="fixture",
            command_builder=lambda request: [sys.executable, "-c", script],
            incremental_json_events=True,
        )


@pytest.mark.parametrize(
    ("connector", "incremental"),
    [(None, False), ("pi-v1", False), ("pi-v2", True)],
)
def test_pi_connector_version_selects_json_event_transport(
    tmp_path, monkeypatch, connector, incremental
):
    monkeypatch.delenv("METERING_HARNESS_RUNTIME_MANIFEST", raising=False)
    if connector is not None:
        runtime = json.loads(
            (ROOT / "apps/harness/profiles/runtime-fixture.json").read_text()
        )
        runtime["model"]["connector"] = connector
        manifest = tmp_path / "runtime.json"
        manifest.write_text(canonical_json(runtime) + "\n")
        monkeypatch.setenv("METERING_HARNESS_RUNTIME_MANIFEST", str(manifest))
    calls = []
    monkeypatch.setattr(
        pi_harness_model,
        "run_main",
        lambda **kwargs: calls.append(kwargs) or 0,
    )
    assert pi_harness_model.main() == 0
    assert calls[0]["incremental_json_events"] is incremental


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
