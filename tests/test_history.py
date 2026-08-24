from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_history(command: str, history: Path, payload: str = ""):
    return subprocess.run(
        [sys.executable, "-m", "metering.history", command, str(history)],
        cwd=ROOT,
        input=payload,
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


def test_history_records_parent_linked_measurement_pairs(tmp_path):
    history = tmp_path / "history"
    payload = '{"measure":"entropy","probabilities":[0.5,0.5]}'

    first_result = run_history("record", history, payload)
    second_result = run_history("record", history, payload)

    assert first_result.returncode == second_result.returncode == 0
    assert first_result.stderr == second_result.stderr == ""
    first = parse_canonical(first_result.stdout)
    second = parse_canonical(second_result.stdout)
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
    assert second["record_id"] != first["record_id"]
    assert (history / "HEAD").read_text() == f'{second["record_id"]}\n'
    assert len(list((history / "objects").glob("*.json"))) == 2

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


def test_history_verify_detects_a_modified_record(tmp_path):
    history = tmp_path / "history"
    result = run_history(
        "record",
        history,
        '{"measure":"self_information","probability":0.5}',
    )
    record = json.loads(result.stdout)
    path = history / "objects" / f'{record["record_id"]}.json'
    payload = json.loads(path.read_text())
    payload["response"]["value"] = 2.0
    path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")

    verify_result = run_history("verify", history)

    assert verify_result.returncode == 2
    assert verify_result.stdout == ""
    error = parse_canonical(verify_result.stderr)["error"]
    assert error["code"] == "invalid_history"
    assert "pair hash" in error["message"]


def test_history_rejects_a_stale_writer_lock(tmp_path):
    history = tmp_path / "history"
    (history / "objects").mkdir(parents=True)
    (history / "LOCK").mkdir()

    result = run_history(
        "record",
        history,
        '{"measure":"self_information","probability":0.5}',
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert parse_canonical(result.stderr)["error"]["code"] == "invalid_history"
    assert list((history / "objects").iterdir()) == []


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
