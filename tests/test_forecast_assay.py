from __future__ import annotations

import json
import selectors
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "apps" / "forecast_assay" / "forecast_assay.py"


def run_forecast_assay(
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


def run_forecast_assay_bytes(
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
    candidate: object = "forecast-17",
    evaluation: object = "weather-station-a/holdout-v1",
) -> str:
    return json.dumps(
        {
            "schema_version": 1,
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


def test_forecast_assay_measures_one_agent_supplied_candidate():
    result = run_forecast_assay(
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
        "candidate": "forecast-17",
        "evaluation": "weather-station-a/holdout-v1",
        "schema_version": 1,
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


def test_forecast_assay_jsonl_measures_multiple_independent_candidates():
    first = candidate_request(
        [
            {
                "observation": "case",
                "target": "yes",
                "target_probability": 0.5,
            }
        ],
        candidate="first",
        evaluation="eval",
    )
    second = candidate_request(
        [
            {
                "observation": "case",
                "target": "yes",
                "target_probability": 1.0,
            }
        ],
        candidate="second",
        evaluation="eval",
    )

    result = run_forecast_assay(first + "\n" + second + "\n", "--jsonl")

    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert len(lines) == 2
    responses = [json.loads(line) for line in lines]
    assert [response["candidate"] for response in responses] == [
        "first",
        "second",
    ]
    assert [
        response["measurement"]["aggregate"]["mean_target_surprisal_bits"]
        for response in responses
    ] == [1.0, 0.0]
    assert lines == [
        json.dumps(response, allow_nan=False, separators=(",", ":"), sort_keys=True)
        for response in responses
    ]


def test_forecast_assay_jsonl_replies_before_input_reaches_eof():
    process = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--jsonl"],
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
        process.stdin.write(
            candidate_request(
                [
                    {
                        "observation": "case",
                        "target": "yes",
                        "target_probability": 0.5,
                    }
                ],
                candidate="interactive",
                evaluation="eval",
            )
            + "\n"
        )
        process.stdin.flush()
        assert selector.select(timeout=10), (
            "Forecast assay did not flush a JSONL response"
        )
        response = json.loads(process.stdout.readline())
        assert response["candidate"] == "interactive"
        assert process.poll() is None
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        assert process.stderr.read() == ""
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def test_forecast_assay_jsonl_returns_line_errors_and_continues():
    valid = candidate_request(
        [
            {
                "observation": "case",
                "target": "yes",
                "target_probability": 0.5,
            }
        ],
        candidate="valid",
        evaluation="eval",
    )
    invalid_probability = candidate_request(
        [
            {
                "observation": "case",
                "target": "yes",
                "target_probability": True,
            }
        ],
        candidate="invalid",
        evaluation="eval",
    )

    result = run_forecast_assay(
        "{\n" + invalid_probability + "\n" + valid + "\n", "--jsonl"
    )

    assert result.returncode == 0
    assert result.stderr == ""
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert [response["error"]["code"] for response in responses[:2]] == [
        "invalid_request",
        "invalid_probability",
    ]
    assert responses[2]["candidate"] == "valid"


def test_forecast_assay_jsonl_rejects_invalid_utf8_and_continues():
    valid = candidate_request(
        [
            {
                "observation": "case",
                "target": "yes",
                "target_probability": 1,
            }
        ],
        candidate="valid",
        evaluation="eval",
    ).encode("utf-8")

    result = run_forecast_assay_bytes(b"\xff\n" + valid + b"\n", "--jsonl")

    assert result.returncode == 0
    assert result.stderr == b""
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]["error"]["code"] == "invalid_request"
    assert "UTF-8" in responses[0]["error"]["message"]
    assert responses[1]["candidate"] == "valid"


def test_forecast_assay_jsonl_accepts_empty_stream():
    result = run_forecast_assay("", "--jsonl")

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_forecast_assay_encodes_infinite_target_surprisal_as_valid_json():
    result = run_forecast_assay(
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


def test_forecast_assay_canonicalizes_negative_zero_in_the_response():
    result = run_forecast_assay(
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


def test_forecast_assay_rejects_duplicate_keys_and_bad_probabilities():
    duplicate = run_forecast_assay(
        '{"schema_version":1,"candidate":"first","candidate":"second",'
        '"evaluation":"eval","observations":['
        '{"observation":"case","target":"yes",'
        '"target_probability":1}]}'
    )
    invalid_probability = run_forecast_assay(
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


def test_forecast_assay_rejects_numbers_that_change_zero_or_one_on_conversion():
    requests = [
        '{"schema_version":1,"candidate":"underflow","evaluation":"eval",'
        '"observations":[{"observation":"case","target":"yes",'
        '"target_probability":1e-999}]}',
        '{"schema_version":1,"candidate":"rounds-to-one",'
        '"evaluation":"eval","observations":['
        '{"observation":"case","target":"yes","target_probability":'
        "0.999999999999999999999999999999}]}",
    ]

    for request in requests:
        message = assert_invalid_request(run_forecast_assay(request))
        assert "zero or one" in message


def test_forecast_assay_rejects_duplicate_observation_identifiers():
    result = run_forecast_assay(
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


def test_forecast_assay_rejects_bad_observation_envelopes():
    missing = run_forecast_assay(
        candidate_request(
            [{"observation": "case", "target_probability": 0.5}]
        )
    )
    extra = run_forecast_assay(
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
    not_an_object = run_forecast_assay(candidate_request(["case"]))

    assert "target" in assert_invalid_request(missing)
    assert "weight" in assert_invalid_request(extra)
    assert "JSON object" in assert_invalid_request(not_an_object)


def test_forecast_assay_rejects_bad_request_envelopes_and_nonfinite_tokens():
    requests = [
        '{"candidate":"bad","evaluation":"eval","observations":[]}',
        '{"schema_version":2,"candidate":"bad","evaluation":"eval",'
        '"observations":[]}',
        '{"schema_version":true,"candidate":"bad","evaluation":"eval",'
        '"observations":[]}',
        '{"schema_version":1.0,"candidate":"bad","evaluation":"eval",'
        '"observations":[]}',
        '{"schema_version":1,"candidate":"bad","evaluation":"eval",'
        '"observations":[],"extra":1}',
        '{"schema_version":1,"candidate":"bad","evaluation":"eval",'
        '"observations":[{"observation":"case","target":"yes",'
        '"target_probability":NaN}]}',
        '{"schema_version":1,"candidate":"bad","evaluation":"eval",'
        '"observations":[{"observation":"case","target":"yes",'
        '"target_probability":Infinity}]}',
        '{"schema_version":1,"candidate":"bad","evaluation":"eval",'
        '"observations":[{"observation":"case","target":"yes",'
        '"target_probability":-Infinity}]}',
    ]

    for request in requests:
        assert_invalid_request(run_forecast_assay(request))


def test_forecast_assay_requires_nonempty_identities_and_observations():
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
        assert_invalid_request(run_forecast_assay(request))


def test_forecast_assay_escapes_a_lone_surrogate_as_canonical_json():
    result = run_forecast_assay_bytes(
        b'{"schema_version":1,"candidate":"\\ud800","evaluation":"eval",'
        b'"observations":[{"observation":"case","target":"yes",'
        b'"target_probability":1}]}'
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


def test_forecast_assay_returns_an_error_envelope_for_json_parser_failures():
    malformed = run_forecast_assay("{")
    huge_number = run_forecast_assay(
        '{"schema_version":1,"candidate":"huge","evaluation":"eval",'
        '"observations":[{"observation":"case","target":"yes",'
        '"target_probability":'
        + "9" * 5000
        + "}]}"
    )
    deeply_nested = run_forecast_assay(
        '{"schema_version":1,"candidate":"deep","evaluation":"eval",'
        '"observations":'
        + "[" * 2000
        + "0"
        + "]" * 2000
        + "}"
    )

    assert_invalid_request(malformed)
    assert_invalid_request(huge_number)
    assert_invalid_request(deeply_nested)


def test_forecast_assay_rejects_invalid_utf8_without_a_traceback():
    result = run_forecast_assay_bytes(b"\xff")

    assert result.returncode == 2
    assert result.stdout == b""
    assert json.loads(result.stderr) == {
        "error": {
            "code": "invalid_request",
            "message": "standard input must be valid UTF-8 JSON",
        }
    }
    assert b"Traceback" not in result.stderr


def test_forecast_assay_rejects_command_line_arguments():
    result = run_forecast_assay("{}", "--loop")

    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "error": {
            "code": "invalid_request",
            "message": "command-line arguments are not supported",
        }
    }
