from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "apps" / "mutagenesis" / "mutagenesis.py"


def run_mutagenesis(
    request: str, *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        input=request,
        capture_output=True,
        check=False,
        text=True,
    )


def test_mutagenesis_measures_one_agent_supplied_candidate():
    result = run_mutagenesis(
        '{"candidate":"mutation-17","target_probabilities":[0.5,0.25,1.0]}'
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "candidate": "mutation-17",
        "measurement": {
            "aggregate": {
                "infinite": False,
                "mean_target_surprisal_bits": 1.0,
            },
            "base": 2.0,
            "metering_measure": "self_information",
            "outcomes": [
                {
                    "infinite": False,
                    "target_probability": 0.5,
                    "value_bits": 1.0,
                },
                {
                    "infinite": False,
                    "target_probability": 0.25,
                    "value_bits": 2.0,
                },
                {
                    "infinite": False,
                    "target_probability": 1.0,
                    "value_bits": 0.0,
                },
            ],
        },
    }


def test_mutagenesis_encodes_infinite_target_surprisal_as_valid_json():
    result = run_mutagenesis(
        '{"candidate":"impossible-target","target_probabilities":[0,0.5]}'
    )

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["measurement"]["aggregate"] == {
        "infinite": True,
        "mean_target_surprisal_bits": None,
    }
    assert response["measurement"]["outcomes"][0] == {
        "infinite": True,
        "target_probability": 0.0,
        "value_bits": None,
    }


def test_mutagenesis_rejects_duplicate_keys_and_bad_probabilities():
    duplicate = run_mutagenesis(
        '{"candidate":"first","candidate":"second","target_probabilities":[1]}'
    )
    invalid_probability = run_mutagenesis(
        '{"candidate":"bad","target_probabilities":[true]}'
    )

    assert duplicate.returncode == 2
    assert duplicate.stdout == ""
    assert json.loads(duplicate.stderr) == {
        "error": {
            "code": "invalid_request",
            "message": "duplicate key: candidate",
        }
    }
    assert invalid_probability.returncode == 2
    assert invalid_probability.stdout == ""
    error = json.loads(invalid_probability.stderr)["error"]
    assert error["code"] == "invalid_probability"
    assert "target_probabilities[0]" in error["message"]


def test_mutagenesis_rejects_command_line_arguments():
    result = run_mutagenesis("{}", "--loop")

    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "error": {
            "code": "invalid_request",
            "message": "command-line arguments are not supported",
        }
    }
