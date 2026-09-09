"""Source grounding is bounded, inert, content-bound, and fails closed."""

from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from test_task_profile_tool import ROOT, draft_document, git, repository, write_draft

from apps.coding_agent import task_sources as sources
from apps.coding_agent.experiment_config import solution_driver_request
from apps.coding_agent.protocol import CodingTaskError, load_task_profile
from apps.coding_agent.task_context import MAX_SOURCE_BYTES, normalize_task_context
from apps.coding_agent.task_profile_tool import TaskRegistrationError, create_profile, derive_profile


def context(snapshots: list[dict] | None = None) -> dict:
    return {"context_schema": "agentvolve-task-context-v1", "requirements": ["Use actual input data."],
            "assumptions": [], "read_only_paths": ["check.py"], "sources": snapshots or []}


def test_git_reads_exact_commit_not_worktree_and_never_executes(tmp_path: Path):
    root, commit = repository(tmp_path)
    original = (root / "check.py").read_bytes()
    (root / "check.py").write_text("raise RuntimeError('MUST NOT RUN')\n")
    result = sources.git_snapshot(root, commit, "check.py")
    assert result["content"].encode() == original
    assert result["sha256"] == hashlib.sha256(original).hexdigest()
    assert commit in result["uri"] and "check.py" in result["uri"]
    assert result["representation"] == "utf-8"
    assert "MUST NOT RUN" in (root / "check.py").read_text()
    with pytest.raises(sources.TaskSourceError, match="immutable"):
        sources.git_snapshot(root, "HEAD", "check.py")
    for path in ("../answer.txt", ".git/config", "/etc/passwd"):
        with pytest.raises(ValueError):
            sources.git_snapshot(root, commit, path)
    with pytest.raises(sources.TaskSourceError, match="absent"):
        sources.git_snapshot(root, commit, "missing.py")


@pytest.mark.parametrize("kind", ["symlink", "directory", "binary", "large"])
def test_git_rejects_unsafe_or_unsupported_input(tmp_path: Path, kind: str):
    root, _ = repository(tmp_path)
    target = root / "input.dat"
    if kind == "symlink":
        target.symlink_to(tmp_path / "secret")
    elif kind == "directory":
        target.mkdir()
        (target / "a").write_text("a")
    else:
        target.write_bytes(b"\0binary" if kind == "binary" else b"x" * (MAX_SOURCE_BYTES + 1))
    git(root, "add", ".")
    git(root, "commit", "-m", "Input fixture")
    with pytest.raises(sources.TaskSourceError):
        sources.git_snapshot(root, git(root, "rev-parse", "HEAD"), "input.dat")


def test_explicit_local_snapshots_preserve_bytes_and_reject_links(tmp_path: Path):
    source = tmp_path / "data.csv"
    source.write_bytes(b"a,b\r\n1,2\r\n")
    result = sources.local_snapshot(source)
    assert result["content"] == "a,b\r\n1,2\r\n"
    assert result["uri"] == source.as_uri()
    link = tmp_path / "link.csv"
    link.symlink_to(source)
    with pytest.raises(sources.TaskSourceError, match="symlink"):
        sources.local_snapshot(link)
    with pytest.raises(sources.TaskSourceError, match="regular"):
        sources.local_snapshot(tmp_path)
    with pytest.raises(sources.TaskSourceError, match="UTF-8"):
        source.write_bytes(b"\xff")
        sources.local_snapshot(source)


def test_local_parent_swap_cannot_redirect_input_to_another_file(tmp_path: Path, monkeypatch):
    public, private = tmp_path / "public", tmp_path / "private"
    public.mkdir()
    private.mkdir()
    path = public / "input.txt"
    path.write_text("public input")
    (private / "input.txt").write_text("PRIVATE_MUST_NOT_BE_READ")
    original_resolve = Path.resolve

    def swap_after_resolution(self, *args, **kwargs):
        resolved = original_resolve(self, *args, **kwargs)
        if self == path:
            public.rename(tmp_path / "original-public")
            public.symlink_to(private, target_is_directory=True)
        return resolved

    monkeypatch.setattr(Path, "resolve", swap_after_resolution)
    with pytest.raises(OSError):
        sources.local_snapshot(path)


def test_local_change_during_read_requires_fresh_review(tmp_path: Path, monkeypatch):
    path = tmp_path / "input.txt"
    path.write_text("initial input")
    original = os.fstat
    calls = 0

    def changed(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_text("changed input, different size")
        return original(descriptor)

    monkeypatch.setattr(os, "fstat", changed)
    with pytest.raises(sources.TaskSourceError, match="changed while"):
        sources.local_snapshot(path)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/file", "https://user:password@example.com",
    "http://127.0.0.1/x", "http://[::1]/x", "http://169.254.169.254/", "https://example.com:444/",
    "http://[::ffff:127.0.0.1]/", "https://example.com/\r\nx", "https://example.com\\@localhost/",
])
def test_url_rejects_private_addresses_credentials_schemes_and_controls(url: str):
    with pytest.raises((sources.TaskSourceError, OSError)):
        sources._public_endpoint(url)


def public_dns(host, port, **_kwargs):
    ip = "127.0.0.1" if host == "private.invalid" else "93.184.216.34"
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


class Response(io.BytesIO):
    def __init__(self, body: bytes, status=200, **headers):
        super().__init__(body)
        self.status, self.headers = status, {"Content-Type": "text/plain", **headers}

    def getheader(self, key, default=None):
        return self.headers.get(key, default)


class Connection:
    def __init__(self, response):
        self.response, self.closed = response, False

    def request(self, *args, **kwargs):
        assert args[0] == "GET" and "Authorization" not in kwargs["headers"]

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def test_url_snapshots_are_inert_and_redirects_revalidate(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", public_dns)
    body = b"<html><h1>Actual rules</h1><script>var grid=[0,1]; NEVER_EXECUTE()</script></html>"
    connection = Connection(Response(body, **{"Content-Type": "text/html"}))
    monkeypatch.setattr(sources, "_connection", lambda *args: connection)
    result = sources.url_snapshot("https://example.com/rules")
    assert result["representation"] == "html-text"
    assert "Actual rules" in result["content"] and "grid=[0,1]" in result["content"]
    assert result["sha256"] == hashlib.sha256(result["content"].encode()).hexdigest()
    assert connection.closed
    connection = Connection(Response(b"", 302, Location="https://private.invalid/secret"))
    with pytest.raises(sources.TaskSourceError, match="Private"):
        sources.url_snapshot("https://example.com/redirect")
    assert connection.closed


def test_url_connection_pins_validated_ip_without_second_dns(monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "create_connection", lambda address, timeout, source: calls.append(address))
    connection = sources._connection("https", "example.com", 443, "93.184.216.34", 2)
    connection._create_connection(("example.com", 443), 2)
    assert calls == [("93.184.216.34", 443)]
    assert connection.host == "example.com", "TLS must keep the source hostname"


@pytest.mark.parametrize("response", [
    Response(b"", 404), Response(b"x", **{"Content-Encoding": "gzip"}),
    Response(b"x", **{"Content-Type": "application/octet-stream"}),
    Response(b"x" * (sources.MAX_DOWNLOAD_BYTES + 1)), Response(b"\xff"),
])
def test_url_failures_never_become_silent_empty_or_truncated_context(monkeypatch, response):
    monkeypatch.setattr(socket, "getaddrinfo", public_dns)
    connection = Connection(response)
    monkeypatch.setattr(sources, "_connection", lambda *args: connection)
    with pytest.raises(ValueError):
        sources.url_snapshot("https://example.com/input")
    assert connection.closed


def test_context_is_immutable_task_input_and_reaches_proposer(tmp_path: Path):
    root, commit = repository(tmp_path)
    snapshot = sources.git_snapshot(root, commit, "check.py")
    document = draft_document(root)
    document["context"] = context([snapshot])
    draft = tmp_path / "draft.json"
    write_draft(draft, document)
    registration = create_profile(draft, tmp_path / "tasks")
    profile_path = Path(registration["profile"])
    profile = load_task_profile(profile_path)
    assert profile["context"] == document["context"]
    request = solution_driver_request(profile, {}, proposer=Path("proposer.py"), coding_runtime_id="fixture")
    assert request["proposal"]["context"]["task_context"] == document["context"]
    assert "untrusted reference data" in request["proposal"]["context"]["source_notice"]
    assert "sources" not in request["generation"]["tasks"][0]["input"], "References are not evaluation authority"
    goal = tmp_path / "goal.txt"
    goal.write_text("Recheck the same contract")
    derived = derive_profile(profile_path, goal, 2, tmp_path / "derived")
    assert load_task_profile(Path(derived["profile"]))["context"] == document["context"]
    (root / "answer.txt").write_text("new base")
    git(root, "add", ".")
    git(root, "commit", "-m", "Move HEAD")
    with pytest.raises(TaskRegistrationError, match="HEAD changed"):
        derive_profile(profile_path, goal, 2, tmp_path / "changed")
    raw = json.loads(profile_path.read_text())
    raw["context"]["sources"][0]["content"] = "Tampered input"
    from apps._support.wire import canonical_json
    profile_path.write_text(canonical_json(raw) + "\n")
    with pytest.raises(CodingTaskError, match="digest"):
        load_task_profile(profile_path)


def test_context_rejects_write_overlap_duplicates_and_size(tmp_path: Path):
    root, _ = repository(tmp_path)
    document = draft_document(root)
    document["context"] = context()
    document["allowed_paths"] = ["check.py"]
    draft = tmp_path / "draft.json"
    write_draft(draft, document)
    with pytest.raises(TaskRegistrationError, match="read-only"):
        create_profile(draft, tmp_path / "tasks")
    assert not (tmp_path / "tasks").exists()
    snapshot = sources.local_snapshot(root / "answer.txt")
    with pytest.raises(ValueError, match="unique"):
        normalize_task_context(context([snapshot, snapshot]))
    snapshot["content"] = "x" * (MAX_SOURCE_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds"):
        normalize_task_context(context([snapshot]))


def test_source_cli_is_read_only_and_rejects_duplicate_request_keys(tmp_path: Path):
    root, commit = repository(tmp_path)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"repository": str(root), "commit": commit, "paths": ["check.py"], "local_paths": [], "urls": []}))
    result = subprocess.run([sys.executable, "-m", "apps.coding_agent.task_sources", str(request)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout)["sources"][0]["content"] == (root / "check.py").read_text()
    request.write_text('{"paths":[],"paths":[]}')
    result = subprocess.run([sys.executable, "-m", "apps.coding_agent.task_sources", str(request)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2 and "duplicate" in result.stderr and "Traceback" not in result.stderr
    assert git(root, "status", "--porcelain") == ""
