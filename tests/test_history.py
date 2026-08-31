from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GIT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})").fullmatch


def run_history(command: str, history: Path, payload: str = ""):
    return subprocess.run(
        [sys.executable, "-m", "metering.history", command, str(history)],
        cwd=ROOT,
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )


def run_git(history: Path, *arguments: str):
    return subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=History Test",
            "-c",
            "user.email=history@example.invalid",
            *arguments,
        ],
        cwd=history,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_canonical(output: str) -> dict[str, object]:
    value = json.loads(output)
    assert output == json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"
    return value


def test_history_records_measurement_pairs_as_git_commits(tmp_path):
    history = tmp_path / "history"
    payload = '{"measure":"entropy","probabilities":[0.5,0.5]}'

    first_result = run_history("record", history, payload)
    second_result = run_history("record", history, payload)

    assert first_result.returncode == second_result.returncode == 0
    assert first_result.stderr == second_result.stderr == ""
    first = parse_canonical(first_result.stdout)
    second = parse_canonical(second_result.stdout)
    assert first["schema_version"] == second["schema_version"] == 2
    assert first["request"] == {
        "measure": "entropy",
        "probabilities": [0.5, 0.5],
    }
    assert first["response"] == {
        "base": 2.0,
        "infinite": False,
        "measure": "entropy",
        "value": 1.0,
    }
    assert first["parent_record_id"] is None
    assert second["parent_record_id"] == first["record_id"]
    assert second["pair_id"] == first["pair_id"]
    assert second["tree_id"] == first["tree_id"]
    assert second["record_id"] != first["record_id"]
    for field in ("pair_id", "record_id", "tree_id"):
        assert GIT_ID(str(first[field])) is not None
    assert re.fullmatch(r"[0-9a-f]{64}", str(first["implementation_sha256"]))
    assert type(first["source_dirty"]) is bool

    assert (history / ".git").is_dir()
    assert not (history / "objects").exists()
    assert json.loads(
        (history / "measurement/pair/configuration.json").read_text()
    ) == first["request"]
    assert json.loads((history / "measurement/pair/result.json").read_text()) == first[
        "response"
    ]
    tracked = run_git(history, "ls-tree", "-r", "--name-only", "HEAD")
    assert tracked.returncode == 0
    assert tracked.stdout.splitlines() == [
        "measurement/pair/configuration.json",
        "measurement/pair/result.json",
        "measurement/provenance.json",
    ]
    commits = run_git(history, "rev-list", "HEAD")
    assert commits.returncode == 0
    assert commits.stdout.splitlines() == [second["record_id"], first["record_id"]]

    log_result = run_history("log", history)
    assert log_result.returncode == 0
    log = parse_canonical(log_result.stdout)
    assert log["head"] == second["record_id"]
    assert [record["record_id"] for record in log["records"]] == [
        second["record_id"],
        first["record_id"],
    ]

    verify_result = run_history("verify", history)
    assert verify_result.returncode == 0
    assert parse_canonical(verify_result.stdout) == {
        "head": second["record_id"],
        "records": 2,
        "valid": True,
    }


def test_history_rejected_measurement_does_not_create_storage(tmp_path):
    history = tmp_path / "history"

    result = run_history(
        "record",
        history,
        '{"measure":"entropy","probabilities":[0.2,0.2]}',
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "invalid_probability"
    assert not history.exists()


def test_history_verify_detects_a_dirty_result(tmp_path):
    history = tmp_path / "history"
    result = run_history(
        "record",
        history,
        '{"measure":"self_information","probability":0.5}',
    )
    assert result.returncode == 0
    path = history / "measurement/pair/result.json"
    payload = json.loads(path.read_text())
    payload["value"] = 2.0
    path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")

    verify_result = run_history("verify", history)

    assert verify_result.returncode == 2
    assert verify_result.stdout == ""
    error = parse_canonical(verify_result.stderr)["error"]
    assert error["code"] == "invalid_history"
    assert "working tree is not clean" in error["message"]


def test_history_verify_replays_and_rejects_a_committed_false_result(tmp_path):
    history = tmp_path / "history"
    result = run_history(
        "record",
        history,
        '{"measure":"self_information","probability":0.5}',
    )
    assert result.returncode == 0
    path = history / "measurement/pair/result.json"
    payload = json.loads(path.read_text())
    payload["value"] = 2.0
    path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    commit = run_git(history, "add", "measurement/pair/result.json")
    assert commit.returncode == 0
    commit = run_git(history, "commit", "-m", "Forge result")
    assert commit.returncode == 0

    verify_result = run_history("verify", history)

    assert verify_result.returncode == 2
    error = parse_canonical(verify_result.stderr)["error"]
    assert error["code"] == "invalid_history"
    assert "does not match Metering replay" in error["message"]


def test_history_rejects_a_stale_writer_lock(tmp_path):
    history = tmp_path / "history"
    first = run_history(
        "record",
        history,
        '{"measure":"self_information","probability":0.5}',
    )
    assert first.returncode == 0
    (history / ".git/metering-history.lock").mkdir()

    result = run_history(
        "record",
        history,
        '{"measure":"self_information","probability":0.5}',
    )

    assert result.returncode == 2
    assert result.stdout == ""
    error = parse_canonical(result.stderr)["error"]
    assert error["code"] == "invalid_history"
    assert "history is locked" in error["message"]
    assert run_git(history, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_history_rejects_legacy_object_storage(tmp_path):
    history = tmp_path / "history"
    (history / "objects").mkdir(parents=True)

    result = run_history(
        "record",
        history,
        '{"measure":"self_information","probability":0.5}',
    )

    assert result.returncode == 2
    error = parse_canonical(result.stderr)["error"]
    assert error["code"] == "invalid_history"
    assert "legacy object histories require explicit migration" in error["message"]


def test_history_rejects_bad_command_lines_as_json(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "metering.history", "--bogus", str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert parse_canonical(result.stderr)["error"]["code"] == "invalid_request"
