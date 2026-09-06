"""Diagnostic persistence is bounded and is never retry or accounting authority."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.process import JsonProcessError, run_json_process  # noqa: E402
from apps.population_driver.diagnostics import record_controller_failure  # noqa: E402


def test_failure_diagnostic_is_private_bounded_redacted_and_content_addressed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("METERING_TEST_API_KEY", "environment-credential")
    stderr = (
        "\x1b[31mBearer bearer-credential\npassword=password-credential\nenvironment-credential\u202e\x00\n"
        + "x" * 10000
    )
    error = JsonProcessError("exit", returncode=137, stderr=stderr)
    digest = record_controller_failure(
        tmp_path,
        attempt_id="a" * 64,
        intent_id="b" * 64,
        command=["python", "controller.py"],
        elapsed_milliseconds=321,
        error=error,
    )
    path = tmp_path / "diagnostics" / f"{digest}.json"
    source = path.read_bytes()
    assert hashlib.sha256(source).hexdigest() == digest
    assert path.stat().st_mode & 0o777 == 0o600
    assert len(source) < 10000
    document = json.loads(source)
    assert document["authority"] == "diagnostic-only"
    assert "137" in document["error"]["summary"]
    assert document["error"]["stderr_truncated"] is True
    excerpt = document["error"]["stderr_excerpt"]
    assert len(excerpt) <= 4096
    assert all(
        value not in excerpt
        for value in (
            "bearer-credential",
            "password-credential",
            "environment-credential",
            "\x1b",
            "\x00",
            "\u202e",
        )
    )
    assert "cost" not in document and "retry" not in document


def test_timeout_retains_available_stderr_without_authorizing_another_call(tmp_path):
    with pytest.raises(JsonProcessError) as failure:
        run_json_process(
            [
                sys.executable,
                "-c",
                "import sys,time; sys.stderr.write('bounded context'); sys.stderr.flush(); time.sleep(30)",
            ],
            {},
            cwd=tmp_path,
            timeout_seconds=1,
        )
    assert failure.value.kind == "timeout"
    assert failure.value.stderr == "bounded context"
    assert "1 seconds" in failure.value.detail
    assert failure.value.returncode is not None
    assert str(failure.value) == "timeout"  # existing transport API remains stable
