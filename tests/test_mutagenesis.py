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


def run_mutagenesis_bytes(
    request: bytes, *arguments: str
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        input=request,
        capture_output=True,
        check=False,
    )


def candidate_request(
    observations: list[object],
    *,
    candidate: object = "mutation-17",
    evaluation: object = "weather-station-a/holdout-v1",
) -> str:
    return json.dumps(
        {
            "candidate": candidate,
            "evaluation": evaluation,
            "observations": observations,
        }
    )


def assert_invalid_request(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"]["code"] == "invalid_request"
    assert result.stderr == json.dumps(
        error, allow_nan=False, separators=(",", ":"), sort_keys=True
    ) + "\n"
    return error["error"]["message"]


def test_mutagenesis_measures_one_agent_supplied_candidate():
    result = run_mutagenesis(
        candidate_request(
            [
                {
                    "observation": "day-001",
                    "target": "rain",
                    "target_probability": 0.5,
                },
                {
                    "observation": "day-002",
                    "target": "rain",
                    "target_probability": 0.25,
                },
                {
                    "observation": "day-003",
                    "target": "dry",
                    "target_probability": 1.0,
                },
            ]
        )
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    expected = {
        "candidate": "mutation-17",
        "evaluation": "weather-station-a/holdout-v1",
        "measurement": {
            "aggregate": {
                "infinite": False,
                "mean_target_surprisal_bits": 1.0,
                "sample_count": 3,
            },
            "base": 2.0,
            "metering_measure": "self_information",
            "outcomes": [
                {
                    "infinite": False,
                    "observation": "day-001",
                    "target": "rain",
                    "target_probability": 0.5,
                    "value_bits": 1.0,
                },
                {
                    "infinite": False,
                    "observation": "day-002",
                    "target": "rain",
                    "target_probability": 0.25,
                    "value_bits": 2.0,
                },
                {
                    "infinite": False,
                    "observation": "day-003",
                    "target": "dry",
                    "target_probability": 1.0,
                    "value_bits": 0.0,
                },
            ],
        },
    }
    assert json.loads(result.stdout) == expected
    assert result.stdout == json.dumps(
        expected, allow_nan=False, separators=(",", ":"), sort_keys=True
    ) + "\n"


def test_mutagenesis_encodes_infinite_target_surprisal_as_valid_json():
    result = run_mutagenesis(
        candidate_request(
            [
                {
                    "observation": "case-1",
                    "target": "yes",
                    "target_probability": 0,
                },
                {
                    "observation": "case-2",
                    "target": "no",
                    "target_probability": 0.5,
                },
            ],
            candidate="impossible-target",
        )
    )

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["measurement"]["aggregate"] == {
        "infinite": True,
        "mean_target_surprisal_bits": None,
        "sample_count": 2,
    }
    assert response["measurement"]["outcomes"][0] == {
        "infinite": True,
        "observation": "case-1",
        "target": "yes",
        "target_probability": 0.0,
        "value_bits": None,
    }


def test_mutagenesis_canonicalizes_negative_zero_in_the_response():
    result = run_mutagenesis(
        candidate_request(
            [
                {
                    "observation": "case",
                    "target": "yes",
                    "target_probability": -0.0,
                }
            ]
        )
    )

    assert result.returncode == 0, result.stderr
    assert '"target_probability":0.0' in result.stdout
    assert '"target_probability":-0.0' not in result.stdout
    assert json.loads(result.stdout)["measurement"]["aggregate"]["infinite"]


def test_mutagenesis_rejects_duplicate_keys_and_bad_probabilities():
    duplicate = run_mutagenesis(
        '{"candidate":"first","candidate":"second","evaluation":"eval",'
        '"observations":[{"observation":"case","target":"yes",'
        '"target_probability":1}]}'
    )
    invalid_probability = run_mutagenesis(
        candidate_request(
            [
                {
                    "observation": "case",
                    "target": "yes",
                    "target_probability": True,
                }
            ],
            candidate="bad",
        )
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
    assert "observations[0].target_probability" in error["message"]


def test_mutagenesis_rejects_numbers_that_change_zero_or_one_on_conversion():
    requests = [
        '{"candidate":"underflow","evaluation":"eval","observations":['
        '{"observation":"case","target":"yes","target_probability":1e-999}]}',
        '{"candidate":"rounds-to-one","evaluation":"eval","observations":['
        '{"observation":"case","target":"yes","target_probability":'
        "0.999999999999999999999999999999}]}",
    ]

    for request in requests:
        message = assert_invalid_request(run_mutagenesis(request))
        assert "zero or one" in message


def test_mutagenesis_rejects_duplicate_observation_identifiers():
    result = run_mutagenesis(
        candidate_request(
            [
                {
                    "observation": "same-case",
                    "target": "yes",
                    "target_probability": 0.5,
                },
                {
                    "observation": "same-case",
                    "target": "no",
                    "target_probability": 0.5,
                },
            ]
        )
    )

    assert "same-case" in assert_invalid_request(result)


def test_mutagenesis_rejects_bad_observation_envelopes():
    missing = run_mutagenesis(
        candidate_request(
            [{"observation": "case", "target_probability": 0.5}]
        )
    )
    extra = run_mutagenesis(
        candidate_request(
            [
                {
                    "observation": "case",
                    "target": "yes",
                    "target_probability": 0.5,
                    "weight": 1,
                }
            ]
        )
    )
    not_an_object = run_mutagenesis(candidate_request(["case"]))

    assert "target" in assert_invalid_request(missing)
    assert "weight" in assert_invalid_request(extra)
    assert "JSON object" in assert_invalid_request(not_an_object)


def test_mutagenesis_rejects_bad_request_envelopes_and_nonfinite_tokens():
    requests = [
        '{"candidate":"bad","observations":[]}',
        '{"candidate":"bad","evaluation":"eval","observations":[],"extra":1}',
        '{"candidate":"bad","evaluation":"eval","observations":['
        '{"observation":"case","target":"yes","target_probability":NaN}]}',
        '{"candidate":"bad","evaluation":"eval","observations":['
        '{"observation":"case","target":"yes","target_probability":Infinity}]}',
        '{"candidate":"bad","evaluation":"eval","observations":['
        '{"observation":"case","target":"yes","target_probability":-Infinity}]}',
    ]

    for request in requests:
        assert_invalid_request(run_mutagenesis(request))


def test_mutagenesis_requires_nonempty_identities_and_observations():
    observation = {
        "observation": "case",
        "target": "yes",
        "target_probability": 0.5,
    }
    requests = [
        candidate_request([observation], candidate=""),
        candidate_request([observation], candidate=17),
        candidate_request([observation], evaluation=""),
        candidate_request([observation], evaluation=17),
        candidate_request([{**observation, "observation": ""}]),
        candidate_request([{**observation, "observation": 17}]),
        candidate_request([{**observation, "target": ""}]),
        candidate_request([{**observation, "target": None}]),
        candidate_request([]),
    ]

    for request in requests:
        assert_invalid_request(run_mutagenesis(request))


def test_mutagenesis_escapes_a_lone_surrogate_as_canonical_json():
    result = run_mutagenesis_bytes(
        b'{"candidate":"\\ud800","evaluation":"eval","observations":['
        b'{"observation":"case","target":"yes","target_probability":1}]}'
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    text = result.stdout.decode("ascii")
    response = json.loads(text)
    assert response["candidate"] == chr(0xD800)
    assert b"\\ud800" in result.stdout
    assert text == json.dumps(
        response, allow_nan=False, separators=(",", ":"), sort_keys=True
    ) + "\n"


def test_mutagenesis_returns_an_error_envelope_for_json_parser_failures():
    malformed = run_mutagenesis("{")
    huge_number = run_mutagenesis(
        '{"candidate":"huge","evaluation":"eval","observations":['
        '{"observation":"case","target":"yes","target_probability":'
        + "9" * 5000
        + "}]}"
    )
    deeply_nested = run_mutagenesis(
        '{"candidate":"deep","evaluation":"eval","observations":'
        + "[" * 2000
        + "0"
        + "]" * 2000
        + "}"
    )

    assert_invalid_request(malformed)
    assert_invalid_request(huge_number)
    assert_invalid_request(deeply_nested)


def test_mutagenesis_rejects_invalid_utf8_without_a_traceback():
    result = run_mutagenesis_bytes(b"\xff")

    assert result.returncode == 2
    assert result.stdout == b""
    assert json.loads(result.stderr) == {
        "error": {
            "code": "invalid_request",
            "message": "standard input must be valid UTF-8 JSON",
        }
    }
    assert b"Traceback" not in result.stderr


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
