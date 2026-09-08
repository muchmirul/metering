"""Trace projections use actual Git objects; fixtures are not assay replay claims."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import subprocess
import threading
import zlib
from contextlib import contextmanager
from pathlib import Path

import pytest

from test_agentvolve_candidate_view import fixture_run, save_records
from apps._support.journal import content_record
from apps.coding_agent.file_view import MAX_BLOB, path_key
from apps.coding_agent.operator_view import OperatorViewError
from apps.coding_agent.trace_labels import branch_labels
from apps.coding_agent.trace_server import TraceServer
from apps.coding_agent.trace_view import TraceSnapshot

ROOT = Path(__file__).resolve().parents[1]


def append_candidate(root: Path, parent: str, mutate) -> str:
    snapshot = TraceSnapshot(root.parent, root.name)
    source = snapshot.source("solution")
    repository = root.parent / "source-solution"

    def git(*args):
        return subprocess.check_output(
            ["git", *args], cwd=repository, text=True
        ).strip()

    git("checkout", "-q", "--detach", source.node(parent)["commit"])
    mutate(repository)
    git("add", "-A")
    git("commit", "-qm", "trace file fixture")
    commit = git("rev-parse", "HEAD")
    git(
        "push",
        "-q",
        str(root / "candidate.git"),
        f"{commit}:refs/trace-fixture/{commit}",
    )
    identity = hashlib.sha256(commit.encode()).hexdigest()
    path = root / "state/population/population.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records.append(
        content_record(
            {
                "kind": "candidate",
                "sequence": len(records),
                "parent_record_id": records[-1]["record_id"],
                "body": {
                    "candidate": {
                        "candidate_id": identity,
                        "artifact": {
                            "commit": commit,
                            "git_tree": git("rev-parse", "HEAD^{tree}"),
                            "entrypoint": "policy.py",
                        },
                    },
                    "parents": [parent],
                    "variation": {"type": "mutation-v1"},
                },
            },
            ValueError,
        )
    )
    save_records(path, records)
    return identity


def files_fixture(tmp_path: Path):
    root, ids = fixture_run(tmp_path, "solution", final=False)
    secret = tmp_path / "host-secret"
    secret.write_text("DO_NOT_READ_HOST_CONTENT")

    def first(repo: Path):
        (repo / "src").mkdir()
        (repo / "src/merge.py").write_bytes(b"line one\r\nline two")
        (repo / "bytes.bin").write_bytes(b"\x00\xff\r\n")
        (repo / "host-link").symlink_to(secret)
        (repo / ":(glob)*.py").write_text("literal pathspec")
        (repo / "evil.html").write_text(
            "<script>window.CANDIDATE_EXECUTED=true</script>"
        )
        (repo / "unicode-\u96ea.txt").write_text("\u96ea\n")
        name = os.fsencode(repo) + b"/nonutf8-\xff.txt"
        descriptor = os.open(name, os.O_CREAT | os.O_WRONLY, 0o600)
        os.write(descriptor, b"opaque path")
        os.close(descriptor)

    a = append_candidate(root, ids[3], first)

    def second(repo: Path):
        (repo / "src/merge.py").rename(repo / "src/renamed.py")
        (repo / "bytes.bin").write_bytes(b"\x00\x01\x02")
        (repo / "policy.py").chmod(0o755)
        (repo / "large.bin").write_bytes(b"x" * (MAX_BLOB + 1))

    b = append_candidate(root, a, second)
    return root, ids, a, b


def test_branch_labels_are_stable_depth_not_round_or_rank():
    parents = {"0": None, "1": "0", "2": "0", "3": "1", "4": "1", "5": "3", "6": "2"}
    before = branch_labels("S", parents)
    assert [row["display_label"] for row in before.values()] == [
        "S0",
        "S1a",
        "S1b",
        "S2a",
        "S2c",
        "S3a",
        "S2b",
    ]
    parents.update({str(index): "0" for index in range(7, 37)})
    after = branch_labels("S", parents)
    assert all(after[key] == value for key, value in before.items())
    assert any(row["branch"] == "aa" for row in after.values())
    assert len({row["display_label"] for row in after.values()}) == len(after)


def test_git_inventory_exact_source_changes_modes_binary_and_renames(tmp_path: Path):
    root, _ids, a, b = files_fixture(tmp_path)
    snapshot = TraceSnapshot(tmp_path, root.name)
    files = snapshot.files["solution"]
    content = files.content(a, path_key(b"src/merge.py"))
    assert content["text"] == "line one\r\nline two"
    assert content["crlf_count"] == 1 and not content["has_final_newline"]
    assert files.blob(a, path_key(b"bytes.bin")) == b"\x00\xff\r\n"
    assert files.content(a, path_key(b"bytes.bin"))["text"] is None
    link = files.content(a, path_key(b"host-link"))
    assert (
        "never followed" in link["warning"]
        and "DO_NOT_READ_HOST_CONTENT" not in link["text"]
    )
    assert files.content(a, path_key(b"nonutf8-\xff.txt"))["text"] == "opaque path"
    assert (
        files.content(a, path_key(":(glob)*.py".encode()))["text"] == "literal pathspec"
    )
    assert files.content(a, path_key(b"evil.html"))["text"].startswith("<script>")
    changes = {row["path"]: row for row in files.changes(b)}
    assert changes["src/merge.py"]["change"] == "deleted"
    assert changes["src/renamed.py"]["change"] == "added"
    assert changes["policy.py"]["change"] == "modified"
    assert (
        changes["policy.py"]["before"]["blob"] == changes["policy.py"]["after"]["blob"]
    )
    assert "old mode 100644" in files.diff(b, path_key(b"policy.py"), None)["text"]
    assert "GIT binary patch" in files.diff(b, path_key(b"bytes.bin"), None)["text"]
    assert files.content(b, path_key(b"large.bin"))["text"] is None
    with pytest.raises(OperatorViewError, match="1 MiB"):
        files.blob(b, path_key(b"large.bin"))
    renames = files.renames(b)
    assert renames[0]["before"]["path"] == "src/merge.py"
    assert renames[0]["after"]["path"] == "src/renamed.py"
    assert renames[0]["authority"] == "inferred-only"


def test_history_and_comparisons_do_not_guess_rename_or_absent_blobs(tmp_path: Path):
    root, ids, a, b = files_fixture(tmp_path)
    snapshot = TraceSnapshot(tmp_path, root.name)
    history = snapshot.file_history("solution", path_key(b"src/merge.py"))
    rows = {row["candidate_id"]: row for row in history["items"]}
    assert rows[ids[0]]["file"] is None and rows[ids[0]]["change"] == "absent"
    assert rows[a]["change"] == "added"
    assert rows[b]["change"] == "deleted" and rows[b]["file"] is None
    assert (
        snapshot.files["solution"].change(b, path_key(b"src/merge.py"))[
            "base_candidate_id"
        ]
        == a
    )
    assert (
        snapshot.files["solution"].diff(a, path_key(b"policy.py"), ids[2])[
            "base_candidate_id"
        ]
        == ids[2]
    )
    with pytest.raises(OperatorViewError):
        snapshot.file_history("solution", path_key(b"../../host-secret"))


def test_trace_snapshot_exports_preserve_ids_and_read_only_evidence(tmp_path: Path):
    root, ids = fixture_run(tmp_path, "solution")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    snapshot = TraceSnapshot(tmp_path, root.name)
    graph = snapshot.graph()
    assert [node["display_label"] for node in graph["nodes"]] == [
        "S0",
        "S1a",
        "S1b",
        "S2a",
    ]
    assert graph["authority"] == "projection-only"
    assert "Not offline-verified" in graph["verification"]
    for identity in ids:
        assert snapshot.report("solution", identity)["node"]["candidate_id"] == identity
        assert (
            snapshot.node("solution", identity)["evidence"]["final"] is not None
        ) == (identity == ids[3])
    snapshot.file_history("solution", path_key(b"policy.py"))
    assert snapshot.snapshot_id.encode() in snapshot.csv()
    assert b"S2a" in snapshot.csv()
    assert {
        path: path.read_bytes() for path in root.rglob("*") if path.is_file()
    } == before


def test_git_environment_cannot_redirect_the_file_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root, ids = fixture_run(tmp_path, "solution")
    snapshot = TraceSnapshot(tmp_path, root.name)
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(tmp_path / "missing"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "diff.external")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    assert (
        snapshot.files["solution"]
        .content(ids[1], path_key(b"policy.py"))["text"]
        .startswith("# candidate 1")
    )
    with pytest.raises(OperatorViewError):
        snapshot.files["solution"].content(ids[1], "not-a-registered-path")


@contextmanager
def served(root: Path):
    server = TraceServer(root.parent, root.name)
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def request(
    server: TraceServer, path: str, *, headers=None, method="GET", authorized=True
):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=30)
    supplied = {"Authorization": "Bearer " + server.token} if authorized else {}
    supplied.update(headers or {})
    connection.request(method, path, headers=supplied)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def test_http_is_capability_scoped_read_only_and_not_a_filesystem_server(
    tmp_path: Path,
):
    root, ids = fixture_run(tmp_path, "solution")
    with served(root) as server:
        status, headers, body = request(server, "/api/graph")
        assert status == 200
        graph = json.loads(body)
        assert headers["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert "Access-Control-Allow-Origin" not in headers
        assert request(server, "/api/graph", authorized=False)[0] == 403
        assert (
            request(server, "/api/graph", headers={"Origin": "https://evil.invalid"})[0]
            == 403
        )
        assert request(server, "/api/graph", headers={"Host": "evil.invalid"})[0] == 403
        assert (
            request(server, "/api/graph", headers={"Sec-Fetch-Site": "cross-site"})[0]
            == 403
        )
        assert request(server, "/api/graph", method="POST")[0] == 405
        assert request(server, "/api/graph?refresh=yes")[0] == 400
        assert request(server, "/api/graph?refresh=0&refresh=1")[0] == 400
        assert request(server, "/api/graph?command=touch")[0] == 400
        assert request(server, "/../../etc/passwd")[0] == 404
        assert request(server, "/api/graph?snapshot=unknown")[0] == 400
        key = path_key(b"policy.py")
        query = f"snapshot={graph['snapshot_id']}&kind=solution&candidate={ids[1]}&path={key}"
        status, headers, body = request(server, "/api/blob?" + query)
        assert status == 200 and body.startswith(b"# candidate 1")
        assert headers["Content-Type"] == "application/octet-stream"
        assert headers["Content-Disposition"].startswith("attachment;")
        assert request(server, "/api/content?" + query + "&offset=-1")[0] == 400
        assert (
            request(server, "/api/content?kind=solution&candidate=bad&path=" + key)[0]
            == 400
        )
        assert request(server, "/api/export?format=csv")[0] == 200
        assert request(server, "/api/export?format=json")[0] == 200


def test_refresh_keeps_old_snapshot_bound_and_branch_names_stable(tmp_path: Path):
    root, ids = fixture_run(tmp_path, "solution", final=False)
    with served(root) as server:
        old = json.loads(request(server, "/api/graph")[2])
        child = append_candidate(
            root, ids[1], lambda repo: (repo / "extra.py").write_text("new child")
        )
        new = json.loads(request(server, "/api/graph?refresh=1")[2])
        assert new["snapshot_id"] != old["snapshot_id"]
        assert (
            next(node for node in new["nodes"] if node["candidate_id"] == child)[
                "display_label"
            ]
            == "S2c"
        )
        assert (
            json.loads(request(server, f"/api/graph?snapshot={old['snapshot_id']}")[2])
            == old
        )
        assert len(new["nodes"]) == len(old["nodes"]) + 1


def test_snapshot_freezes_public_receipt_availability_and_binds_it(tmp_path: Path):
    root, _ids = fixture_run(tmp_path, "solution")
    old = TraceSnapshot(tmp_path, root.name)
    before = old.loop("solution", "SR1")
    receipt = old.source("solution").rounds[0]["controller_receipt"]
    path = root / "state/receipts" / receipt["name"]
    data = path.read_bytes()
    path.unlink()
    assert old.loop("solution", "SR1") == before
    refreshed = TraceSnapshot(tmp_path, root.name)
    assert refreshed.snapshot_id != old.snapshot_id
    assert any(
        event["step"] == "Controller details unavailable"
        for event in refreshed.loop("solution", "SR1")["events"]
    )
    path.write_bytes(data)
    assert TraceSnapshot(tmp_path, root.name).snapshot_id == old.snapshot_id


def test_viewer_lifetime_closes_its_socket_without_worker_effects(tmp_path: Path):
    root, _ids = fixture_run(tmp_path, "solution")
    server = TraceServer(tmp_path, root.name)
    server.run_until_idle(idle=0.01, lifetime=0.01)
    assert server.socket.fileno() == -1
    assert not (root / "worker-status.json").exists()


def test_corrupt_git_tree_and_blob_bytes_cannot_be_presented_as_bound_files(
    tmp_path: Path,
):
    root, ids = fixture_run(tmp_path, "solution")
    snapshot = TraceSnapshot(tmp_path, root.name)
    tree = snapshot.node("solution", ids[0])["git_tree"]
    path = root / "candidate.git/objects" / tree[:2] / tree[2:]
    original = path.read_bytes()
    raw = zlib.decompress(original).replace(b"policy.py", b"evilxx.py")
    path.unlink()  # Break the test clone's read-only hardlink before deliberate corruption.
    path.write_bytes(zlib.compress(raw))
    with pytest.raises(OperatorViewError, match="tree bytes"):
        snapshot.files["solution"].inventory(ids[0])
    path.write_bytes(original)
    files = snapshot.files["solution"]
    entry = files.entry(ids[0], path_key(b"policy.py"))
    blob_path = root / "candidate.git/objects" / entry["blob"][:2] / entry["blob"][2:]
    blob = blob_path.read_bytes()
    blob_path.unlink()
    blob_path.write_bytes(
        zlib.compress(zlib.decompress(blob).replace(b"candidate 0", b"candidate X"))
    )
    with pytest.raises(OperatorViewError, match="object identity"):
        files.blob(ids[0], path_key(b"policy.py"))


def test_missing_objects_are_not_lazily_fetched_or_written(tmp_path: Path):
    root, ids = fixture_run(tmp_path, "solution")
    files = TraceSnapshot(tmp_path, root.name).files["solution"]
    oid = files.inventory(ids[0])[path_key(b"policy.py")]["blob"]
    missing = root / "candidate.git/objects" / oid[:2] / oid[2:]
    missing.unlink()
    for key, value in (
        ("extensions.partialClone", "origin"),
        ("remote.origin.promisor", "true"),
    ):
        subprocess.run(
            ["git", "--git-dir", str(root / "candidate.git"), "config", key, value],
            check=True,
        )
    with pytest.raises(OperatorViewError, match="objects are absent"):
        TraceSnapshot(tmp_path, root.name).files["solution"].inventory(ids[0])
    assert not missing.exists()
    assert not (root / "candidate.git/FETCH_HEAD").exists()


def test_full_source_pages_preserve_long_unicode_content(tmp_path: Path):
    root, ids = fixture_run(tmp_path, "solution", final=False)
    text = "\u96ea" * 300000
    child = append_candidate(
        root, ids[1], lambda repo: (repo / "long.txt").write_text(text)
    )
    files = TraceSnapshot(tmp_path, root.name).files["solution"]
    first = files.content(child, path_key(b"long.txt"))
    assert first["next_offset"] == 200
    second = files.content(child, path_key(b"long.txt"), 200)
    assert second["next_offset"] is None
    assert first["text"] + second["text"] == text
    assert files.blob(child, path_key(b"long.txt")) == text.encode()


def test_submodule_metadata_never_opens_an_external_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root, ids = fixture_run(tmp_path, "solution")
    files = TraceSnapshot(tmp_path, root.name).files["solution"]
    entry = {
        "path_id": "external",
        "path": "external",
        "mode": "160000",
        "blob": "0" * 40,
        "object_type": "commit",
        "size": None,
    }
    monkeypatch.setattr(files, "inventory", lambda _identity: {"external": entry})
    assert (
        "submodule references are metadata only"
        in files.content(ids[0], "external")["warning"]
    )
