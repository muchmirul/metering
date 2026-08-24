from __future__ import annotations

import json
import math
import runpy
import selectors
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OBSERVER = ROOT / "apps" / "observer" / "observer.py"


def run_observer(active: str, history: Path | None = None):
    arguments = [sys.executable, str(OBSERVER), "--active", active]
    if history is not None:
        arguments.extend(["--history", str(history)])
    return subprocess.run(
        arguments,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def run_observer_jsonl(
    active: str, payload: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(OBSERVER), "--jsonl", "--active", active],
        cwd=ROOT,
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )


def isolated_observer_app(
    tmp_path: Path, metadata: list[object]
) -> Path:
    app = tmp_path / "observer"
    (app / "fixtures").mkdir(parents=True)
    shutil.copy2(OBSERVER, app / "observer.py")
    (app / "versions.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    return app


def run_isolated_observer(
    app: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(app / "observer.py"), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_events(output: str) -> list[dict[str, object]]:
    lines = output.splitlines()
    events = [json.loads(line) for line in lines]
    assert lines == [
        json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        for event in events
    ]
    return events


@pytest.mark.parametrize("active", ["v1", "v2", "v3", "v4"])
def test_observer_identifies_every_fixture_version(active):
    result = run_observer(active)

    assert result.returncode == 0
    assert result.stderr == ""
    events = parse_events(result.stdout)
    assert [event["event"] for event in events] == [
        "start",
        "observation",
        "observation",
        "identified",
    ]
    assert events[-1]["snapshot"]["name"] == active
    assert events[-1]["steps"] == 2

    observations = events[1:-1]
    assert [
        event["candidate_entropy_before"]["response"]["value"]
        for event in observations
    ] == [2.0, 1.0]
    assert [
        event["candidate_entropy_after"]["response"]["value"]
        for event in observations
    ] == [1.0, 0.0]

    total_surprisal = 0.0
    for event in observations:
        entropy_before = event["candidate_entropy_before"]["response"]["value"]
        entropy_after = event["candidate_entropy_after"]["response"]["value"]
        surprisal = event["observed_surprisal"]["response"]["value"]
        scores = event["probe_scores"]
        selected_score = next(
            score for score in scores if score["probe"] == event["selected_probe"]
        )

        assert event["selected_probe"]["operation"] == "read"
        assert selected_score["measurement"]["response"]["value"] == max(
            score["measurement"]["response"]["value"] for score in scores
        )
        assert event["observed_probability"] == pytest.approx(0.5)
        assert entropy_before - entropy_after == pytest.approx(surprisal)
        assert surprisal == pytest.approx(1.0)
        total_surprisal += surprisal

        for score in scores:
            expected_posterior_entropy = sum(
                outcome["probability"] * math.log2(len(outcome["versions"]))
                for outcome in score["outcomes"]
            )
            assert (
                entropy_before - expected_posterior_entropy
                == pytest.approx(score["measurement"]["response"]["value"])
            )

    assert total_surprisal == pytest.approx(2.0)


def test_observer_jsonl_runs_an_external_agent_session():
    snapshot_id = (
        "244c1de679962b61c1e69e03bc1c9b32"
        "84b088b2883a50f9f88a70eb6ae15fcc"
    )
    requests = [
        {"action": "state"},
        {
            "action": "observe",
            "probe": {"operation": "read", "path": "config/mode.txt"},
        },
        {"action": "state"},
        {
            "action": "observe",
            "probe": {"operation": "read", "path": "service/port.txt"},
        },
        {"action": "finish", "snapshot_id": snapshot_id},
        {"action": "state"},
    ]
    result = run_observer_jsonl(
        "v3", "\n".join(json.dumps(request) for request in requests) + "\n"
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    responses = parse_events(result.stdout)
    assert len(responses) == 6
    catalogue_ids = {response["catalogue_id"] for response in responses}
    assert len(catalogue_ids) == 1

    initial, first, state, second, finish, after_finish = responses
    assert initial == {
        "available_probes": [
            {
                "probe": {"operation": "list"},
                "result_entropy": {
                    "base": 2.0,
                    "infinite": False,
                    "measure": "entropy",
                    "value": 0.0,
                },
            },
            {
                "probe": {
                    "operation": "read",
                    "path": "config/mode.txt",
                },
                "result_entropy": {
                    "base": 2.0,
                    "infinite": False,
                    "measure": "entropy",
                    "value": 1.0,
                },
            },
            {
                "probe": {
                    "operation": "read",
                    "path": "service/port.txt",
                },
                "result_entropy": {
                    "base": 2.0,
                    "infinite": False,
                    "measure": "entropy",
                    "value": 1.0,
                },
            },
        ],
        "belief": {"v1": 0.25, "v2": 0.25, "v3": 0.25, "v4": 0.25},
        "catalogue_id": initial["catalogue_id"],
        "ok": True,
        "protocol_version": 1,
        "snapshots": [
            {
                "name": "v1",
                "snapshot_id": (
                    "6298657f9ed2c242c2aa39a38b098637"
                    "1a23b7b5f1bd2f8140a704c21a3b725e"
                ),
                "tree_id": (
                    "684c0aefd41e7f63afa3bceff628715f"
                    "cf0988c84fdcca07f8616996c3d6ca02"
                ),
            },
            {
                "name": "v2",
                "snapshot_id": (
                    "7c2f20edfd1fdcecd636df32a5ccc3ea"
                    "d815407853505e528f7c2b146805668c"
                ),
                "tree_id": (
                    "9d49cb4ff3f320821f983c05643e5ce7"
                    "0046e0e0ce9c7fbe4c86cb2509d90e94"
                ),
            },
            {
                "name": "v3",
                "snapshot_id": snapshot_id,
                "tree_id": (
                    "26f0299f8954c040c179bf9f70a63e0"
                    "1c30a98a71c49f7f3851300e248ee8604"
                ),
            },
            {
                "name": "v4",
                "snapshot_id": (
                    "c7f6da72aa99e45f3f6ba3a48af86e"
                    "3d4a970ef61c76d590e01af65cf10aa8b7"
                ),
                "tree_id": (
                    "37e494ec9dc3bc9e1ca0f5b76f720a0f"
                    "eb8db092109ee414c909f4f2a85e8ef6"
                ),
            },
        ],
        "step": 0,
    }
    assert first["belief"] == {
        "v1": 0.0,
        "v2": 0.0,
        "v3": 0.5,
        "v4": 0.5,
    }
    assert first["observed_result"] == {"kind": "text", "text": "fast\n"}
    assert first["observed_probability"] == 0.5
    assert first["observed_surprisal"]["value"] == 1.0
    assert first["done"] is False
    assert first["step"] == 1
    assert state["step"] == 1
    assert [
        item["result_entropy"]["value"] for item in state["available_probes"]
    ] == [0.0, 0.0, 1.0]
    assert second["belief"] == {
        "v1": 0.0,
        "v2": 0.0,
        "v3": 1.0,
        "v4": 0.0,
    }
    assert second["done"] is True
    assert second["step"] == 2
    assert finish["correct"] is True
    assert finish["snapshot"] == {
        "name": "v3",
        "snapshot_id": snapshot_id,
        "tree_id": (
            "26f0299f8954c040c179bf9f70a63e0"
            "1c30a98a71c49f7f3851300e248ee8604"
        ),
    }
    assert after_finish["ok"] is False
    assert after_finish["error"]["code"] == "invalid_request"
    assert after_finish["step"] == 2


def test_observer_jsonl_recovers_from_bad_agent_actions():
    valid_finish_id = "0" * 64
    payload = "\n".join(
        [
            "{",
            '{"action":"state","action":"state"}',
            '{"action":"observe","probe":{"operation":"read",'
            '"path":"not-in-catalogue.txt"}}',
            json.dumps({"action": "finish", "snapshot_id": valid_finish_id}),
            json.dumps({"action": "state"}),
        ]
    ) + "\n"

    result = run_observer_jsonl("v3", payload)

    assert result.returncode == 0
    assert result.stderr == ""
    responses = parse_events(result.stdout)
    assert len(responses) == 5
    for response in responses[:4]:
        assert response["ok"] is False
        assert response["error"]["code"] == "invalid_request"
        assert response["step"] == 0
    assert "catalogue" in responses[2]["error"]["message"]
    assert "one remaining candidate" in responses[3]["error"]["message"]
    assert responses[4]["ok"] is True
    assert responses[4]["step"] == 0


def test_observer_jsonl_replies_before_agent_input_reaches_eof():
    process = subprocess.Popen(
        [sys.executable, str(OBSERVER), "--jsonl", "--active", "v3"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        process.stdin.write('{"action":"state"}\n')
        process.stdin.flush()
        assert selector.select(timeout=10), "Observer did not flush a JSONL response"
        response = json.loads(process.stdout.readline())
        assert response["ok"] is True
        assert response["step"] == 0
        assert process.poll() is None
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        assert process.stderr.read() == ""
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def test_observer_jsonl_reports_startup_errors_as_json():
    result = subprocess.run(
        [
            sys.executable,
            str(OBSERVER),
            "--jsonl",
            "--active",
            "not-a-version",
        ],
        cwd=ROOT,
        input="",
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"]["code"] == "observer_error"
    assert "invalid choice" in error["error"]["message"]
    assert result.stderr == json.dumps(
        error, allow_nan=False, separators=(",", ":"), sort_keys=True
    ) + "\n"


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (OSError("temporary storage unavailable"), "operating system failure"),
        (RuntimeError("unexpected controller bug"), "internal controller failure"),
    ],
)
def test_observer_jsonl_canonicalizes_internal_failures(
    monkeypatch, capsys, failure, message
):
    api = runpy.run_path(str(OBSERVER))

    def fail_to_load_versions():
        raise failure

    monkeypatch.setitem(
        api["main"].__globals__,
        "load_versions",
        fail_to_load_versions,
    )

    status = api["main"](["--jsonl", "--active", "v3"])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["code"] == "observer_error"
    assert message in error["error"]["message"]
    assert captured.err == json.dumps(
        error, allow_nan=False, separators=(",", ":"), sort_keys=True
    ) + "\n"
    assert "Traceback" not in captured.err


def test_observer_jsonl_rejects_invalid_utf8_and_continues():
    result = subprocess.run(
        [sys.executable, str(OBSERVER), "--jsonl", "--active", "v3"],
        cwd=ROOT,
        input=b'\xff\n{"action":"state"}\n',
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == b""
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]["ok"] is False
    assert responses[0]["error"]["code"] == "invalid_request"
    assert "UTF-8" in responses[0]["error"]["message"]
    assert responses[1]["ok"] is True
    assert responses[1]["step"] == 0


def test_observer_exposes_version_lineage_and_exact_probability_models():
    result = run_observer("v3")

    assert result.returncode == 0
    events = parse_events(result.stdout)
    start, first, second, identified = events

    assert start["model"] == {
        "candidate_prior": "uniform",
        "probability_rule": "matching_versions / remaining_versions",
    }
    assert start["versions"] == [
        {
            "name": "v1",
            "parent": None,
            "parent_snapshot_id": None,
            "snapshot_id": (
                "6298657f9ed2c242c2aa39a38b098637"
                "1a23b7b5f1bd2f8140a704c21a3b725e"
            ),
            "tree_id": (
                "684c0aefd41e7f63afa3bceff628715f"
                "cf0988c84fdcca07f8616996c3d6ca02"
            ),
        },
        {
            "name": "v2",
            "parent": "v1",
            "parent_snapshot_id": (
                "6298657f9ed2c242c2aa39a38b098637"
                "1a23b7b5f1bd2f8140a704c21a3b725e"
            ),
            "snapshot_id": (
                "7c2f20edfd1fdcecd636df32a5ccc3ea"
                "d815407853505e528f7c2b146805668c"
            ),
            "tree_id": (
                "9d49cb4ff3f320821f983c05643e5ce7"
                "0046e0e0ce9c7fbe4c86cb2509d90e94"
            ),
        },
        {
            "name": "v3",
            "parent": "v2",
            "parent_snapshot_id": (
                "7c2f20edfd1fdcecd636df32a5ccc3ea"
                "d815407853505e528f7c2b146805668c"
            ),
            "snapshot_id": (
                "244c1de679962b61c1e69e03bc1c9b32"
                "84b088b2883a50f9f88a70eb6ae15fcc"
            ),
            "tree_id": (
                "26f0299f8954c040c179bf9f70a63e0"
                "1c30a98a71c49f7f3851300e248ee8604"
            ),
        },
        {
            "name": "v4",
            "parent": "v3",
            "parent_snapshot_id": (
                "244c1de679962b61c1e69e03bc1c9b32"
                "84b088b2883a50f9f88a70eb6ae15fcc"
            ),
            "snapshot_id": (
                "c7f6da72aa99e45f3f6ba3a48af86e"
                "3d4a970ef61c76d590e01af65cf10aa8b7"
            ),
            "tree_id": (
                "37e494ec9dc3bc9e1ca0f5b76f720a0f"
                "eb8db092109ee414c909f4f2a85e8ef6"
            ),
        },
    ]

    assert first["candidates_before"] == ["v1", "v2", "v3", "v4"]
    assert first["selected_probe"] == {
        "operation": "read",
        "path": "config/mode.txt",
    }
    assert first["observed_result"] == {"kind": "text", "text": "fast\n"}
    assert first["observed_probability"] == 0.5
    assert first["candidates_after"] == ["v3", "v4"]
    assert first["candidate_entropy_before"] == {
        "request": {
            "measure": "entropy",
            "probabilities": [0.25, 0.25, 0.25, 0.25],
        },
        "response": {
            "base": 2.0,
            "infinite": False,
            "measure": "entropy",
            "value": 2.0,
        },
    }
    assert first["observed_surprisal"] == {
        "request": {"measure": "self_information", "probability": 0.5},
        "response": {
            "base": 2.0,
            "infinite": False,
            "measure": "self_information",
            "value": 1.0,
        },
    }

    assert second["candidates_before"] == ["v3", "v4"]
    assert second["selected_probe"] == {
        "operation": "read",
        "path": "service/port.txt",
    }
    assert second["observed_result"] == {"kind": "text", "text": "8000\n"}
    assert second["candidates_after"] == ["v3"]
    assert second["candidate_entropy_after"]["response"]["value"] == 0.0
    assert identified["snapshot"] == start["versions"][2]


def test_observer_rejects_an_unknown_fixture_version():
    result = run_observer("unknown")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid choice" in result.stderr


@pytest.mark.parametrize(
    ("metadata", "error"),
    [
        ([{"name": "..", "parent": None}], "version name"),
        ([{"name": "bad\x00name", "parent": None}], "version name"),
        ([{"name": "v1", "parent": []}], "version parent"),
    ],
)
def test_observer_rejects_malformed_version_metadata(
    tmp_path, metadata, error
):
    app = isolated_observer_app(tmp_path, metadata)

    result = run_isolated_observer(app)

    assert result.returncode == 2
    assert result.stdout == ""
    assert error in result.stderr
    assert "Traceback" not in result.stderr


def test_observer_rejects_a_symlink_fixture_root(tmp_path):
    app = isolated_observer_app(
        tmp_path,
        [{"name": "v1", "parent": None}],
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "state.txt").write_text("outside\n", encoding="utf-8")
    (app / "fixtures" / "v1").symlink_to(
        outside,
        target_is_directory=True,
    )

    result = run_isolated_observer(app, "--active", "v1")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "symlink" in result.stderr
    assert "Traceback" not in result.stderr


def test_observer_preserves_utf8_line_endings_when_distinguishing_versions(
    tmp_path,
):
    app = isolated_observer_app(
        tmp_path,
        [
            {"name": "v1", "parent": None},
            {"name": "v2", "parent": "v1"},
        ],
    )
    v1 = app / "fixtures" / "v1"
    v2 = app / "fixtures" / "v2"
    v1.mkdir()
    v2.mkdir()
    (v1 / "state.txt").write_bytes(b"value\n")
    (v2 / "state.txt").write_bytes(b"value\r\n")

    result = run_isolated_observer(app, "--active", "v2")

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    events = parse_events(result.stdout)
    assert events[1]["observed_result"] == {
        "kind": "text",
        "text": "value\r\n",
    }
    assert events[-1]["snapshot"]["name"] == "v2"


def test_observe_rejects_escaping_and_symlink_paths(tmp_path):
    api = runpy.run_path(str(OBSERVER))
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (sandbox / "outside-link.txt").symlink_to(outside)

    for unsafe_path in (
        "../outside.txt",
        str(outside),
        "outside-link.txt",
        "\x00",
    ):
        with pytest.raises(api["ObserverError"], match="path|symlink"):
            api["observe"](
                sandbox,
                api["Probe"]("read", unsafe_path),
            )

    with pytest.raises(api["ObserverError"], match="symlink"):
        api["observe"](sandbox, api["Probe"]("list"))

    with pytest.raises(api["ObserverError"], match="list probe"):
        api["observe"](sandbox, api["Probe"]("list", "state.txt"))

    sandbox_link = tmp_path / "sandbox-link"
    sandbox_link.symlink_to(sandbox, target_is_directory=True)
    with pytest.raises(api["ObserverError"], match="sandbox root"):
        api["observe"](sandbox_link, api["Probe"]("list"))


def test_run_rejects_unmodelled_sandbox_content(tmp_path, capsys):
    api = runpy.run_path(str(OBSERVER))
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "state.txt").write_text("known\n", encoding="utf-8")
    manifest = api["fixture_manifest"](fixture)
    tree_id = api["digest"](manifest)
    snapshot_id = api["digest"](
        {"parent_snapshot_id": None, "tree_id": tree_id}
    )
    version = api["Version"](
        name="v1",
        parent=None,
        parent_snapshot_id=None,
        root=fixture,
        paths=("state.txt",),
        tree_id=tree_id,
        snapshot_id=snapshot_id,
    )
    sandbox = tmp_path / "sandbox"
    shutil.copytree(fixture, sandbox)
    (sandbox / "unmodelled.txt").write_text("extra\n", encoding="utf-8")

    with pytest.raises(
        api["ObserverError"],
        match="sandbox tree does not match identified snapshot",
    ):
        api["run"]((version,), sandbox)

    output = capsys.readouterr().out
    assert '"event":"start"' in output
    assert '"event":"identified"' not in output


def test_run_rejects_a_symlink_sandbox_root(tmp_path, capsys):
    api = runpy.run_path(str(OBSERVER))
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "state.txt").write_text("known\n", encoding="utf-8")
    manifest = api["fixture_manifest"](fixture)
    tree_id = api["digest"](manifest)
    version = api["Version"](
        name="v1",
        parent=None,
        parent_snapshot_id=None,
        root=fixture,
        paths=("state.txt",),
        tree_id=tree_id,
        snapshot_id=api["digest"](
            {"parent_snapshot_id": None, "tree_id": tree_id}
        ),
    )
    sandbox = tmp_path / "sandbox-link"
    sandbox.symlink_to(fixture, target_is_directory=True)

    with pytest.raises(api["ObserverError"], match="sandbox root"):
        api["run"]((version,), sandbox)

    assert capsys.readouterr().out == ""


def test_observer_can_append_every_measurement_to_history(tmp_path):
    history = tmp_path / "history"

    result = run_observer("v3", history)

    assert result.returncode == 0
    events = parse_events(result.stdout)
    first_measurement = events[1]["candidate_entropy_before"]
    assert set(first_measurement["history"]) == {
        "pair_id",
        "parent_record_id",
        "record_id",
    }

    log_result = subprocess.run(
        [sys.executable, "-m", "metering.history", "log", str(history)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert log_result.returncode == 0
    assert log_result.stderr == ""
    log = json.loads(log_result.stdout)
    assert len(log["records"]) == 12
    assert log["records"][0]["record_id"] == log["head"]
