from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from metering import entropy, kl_divergence, mutual_information, self_information


def run_cli(payload: str = "", *arguments: str, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, "-m", "metering", *arguments],
        input=payload,
        text=True,
        capture_output=True,
        cwd=cwd,
        check=False,
    )


@pytest.mark.parametrize(
    ("document", "expected_value"),
    [
        ({"measure": "self_information", "probability": 0.125}, 3.0),
        ({"measure": "entropy", "probabilities": [0.5, 0.5]}, 1.0),
        (
            {
                "measure": "kl_divergence",
                "p": [0.5, 0.5],
                "q": [0.75, 0.25],
            },
            0.2075187496394219,
        ),
        (
            {
                "measure": "mutual_information",
                "joint": [[0.5, 0.0], [0.0, 0.5]],
            },
            1.0,
        ),
        (
            {
                "measure": "mutual_information",
                "joint": [
                    [0.25, 0.125, 0.125],
                    [0.25, 0.125, 0.125],
                ],
            },
            0.0,
        ),
    ],
)
def test_cli_measures_every_public_operation(document, expected_value):
    result = run_cli(json.dumps(document))

    assert result.returncode == 0
    assert result.stderr == ""
    response = json.loads(result.stdout)
    assert response == {
        "base": 2.0,
        "infinite": False,
        "measure": document["measure"],
        "value": pytest.approx(expected_value),
    }


def test_cli_output_is_canonical_one_line_json():
    result = run_cli('{"measure":"entropy","probabilities":[0.5,0.5]}')

    assert result.stdout == (
        '{"base":2.0,"infinite":false,"measure":"entropy","value":1.0}\n'
    )


def test_cli_accepts_an_explicit_base():
    result = run_cli(
        json.dumps(
            {
                "measure": "entropy",
                "probabilities": [0.5, 0.5],
                "base": math.e,
            }
        )
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["base"] == math.e
    assert response["value"] == pytest.approx(math.log(2))


@pytest.mark.parametrize(
    "document",
    [
        {"measure": "self_information", "probability": 0.0},
        {
            "measure": "kl_divergence",
            "p": [1.0, 0.0],
            "q": [0.0, 1.0],
        },
    ],
)
def test_cli_encodes_infinity_as_valid_json(document):
    result = run_cli(json.dumps(document))

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "base": 2.0,
        "infinite": True,
        "measure": document["measure"],
        "value": None,
    }
    assert "Infinity" not in result.stdout


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ("", "invalid_request"),
        ("not json", "invalid_request"),
        ("[]", "invalid_request"),
        ('{"measure":"unknown"}', "invalid_request"),
        ('{"measure":"entropy"}', "invalid_request"),
        (
            '{"measure":"entropy","probabilities":[0.5,0.5],"extra":1}',
            "invalid_request",
        ),
        (
            '{"measure":"entropy","measure":"entropy",'
            '"probabilities":[0.5,0.5]}',
            "invalid_request",
        ),
        (
            '{"measure":"entropy","probabilities":[NaN,1]}',
            "invalid_request",
        ),
        (
            '{"measure":"entropy","probabilities":[0.2,0.2]}',
            "invalid_probability",
        ),
        (
            '{"measure":"entropy","probabilities":[0.5,0.5],"base":1}',
            "invalid_probability",
        ),
        (
            '{"measure":"self_information","probability":-1e-400}',
            "invalid_request",
        ),
        (
            '{"measure":"self_information","probability":1e-400}',
            "invalid_request",
        ),
        (
            '{"measure":"self_information","probability":1e400}',
            "invalid_request",
        ),
        (
            '{"measure":"self_information",'
            '"probability":0.999999999999999999999}',
            "invalid_request",
        ),
        (
            '{"measure":"self_information",'
            '"probability":1e999999999999999999999999999999999}',
            "invalid_request",
        ),
    ],
)
def test_cli_rejects_bad_requests_with_machine_readable_errors(payload, code):
    result = run_cli(payload)

    assert result.returncode == 2
    assert result.stdout == ""
    response = json.loads(result.stderr)
    assert set(response) == {"error"}
    assert set(response["error"]) == {"code", "message"}
    assert response["error"]["code"] == code
    assert type(response["error"]["message"]) is str
    assert response["error"]["message"]


def test_cli_rejects_multiple_documents():
    result = run_cli(
        '{"measure":"entropy","probabilities":[1]}'
        '{"measure":"entropy","probabilities":[1]}'
    )

    assert result.returncode == 2
    assert json.loads(result.stderr)["error"]["code"] == "invalid_request"


def test_cli_preserves_the_smallest_positive_json_float():
    result = run_cli(
        '{"measure":"self_information","probability":5e-324}'
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["value"] == 1074.0


@pytest.mark.parametrize(
    "payload",
    [
        "[" * 1200 + "0" + "]" * 1200,
        (
            '{"measure":"self_information","probability":'
            + "1" * 5000
            + "}"
        ),
    ],
)
def test_cli_translates_decoder_limits_to_structured_errors(payload):
    result = run_cli(payload)

    assert result.returncode == 2
    assert result.stdout == ""
    response = json.loads(result.stderr)
    assert response["error"]["code"] == "invalid_request"
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ("--bogus",),
        ("--ver",),
        ("--version", "--bogus"),
        ("--bogus", "--version"),
        ("--help", "--bogus"),
        ("-h", "--version"),
    ],
)
def test_cli_rejects_unknown_or_composed_options_as_json(arguments):
    result = run_cli("", *arguments)

    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "invalid_request"


def test_cli_help_and_version_do_not_read_stdin():
    help_result = run_cli("", "--help")
    short_help_result = run_cli("", "-h")
    version_result = run_cli("", "--version")

    assert help_result.returncode == 0
    assert "JSON" in help_result.stdout
    assert "self_information" in help_result.stdout
    assert "mutual_information" in help_result.stdout
    assert short_help_result.returncode == 0
    assert short_help_result.stdout == help_result.stdout
    assert version_result.returncode == 0
    assert version_result.stdout.startswith("metering ")


def test_cli_does_not_create_application_files(tmp_path):
    result = run_cli(
        '{"measure":"entropy","probabilities":[0.5,0.5]}',
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("document", "python_value"),
    [
        (
            {"measure": "self_information", "probability": 0.2, "base": 10},
            lambda: self_information(0.2, base=10),
        ),
        (
            {"measure": "entropy", "probabilities": [0.25, 0.75], "base": 10},
            lambda: entropy([0.25, 0.75], base=10),
        ),
        (
            {
                "measure": "kl_divergence",
                "p": [0.25, 0.75],
                "q": [0.5, 0.5],
                "base": 10,
            },
            lambda: kl_divergence([0.25, 0.75], [0.5, 0.5], base=10),
        ),
        (
            {
                "measure": "mutual_information",
                "joint": [[0.4, 0.1], [0.2, 0.3]],
                "base": 10,
            },
            lambda: mutual_information([[0.4, 0.1], [0.2, 0.3]], base=10),
        ),
    ],
)
def test_cli_and_python_api_return_the_same_measure(document, python_value):
    result = run_cli(json.dumps(document))

    assert result.returncode == 0
    assert json.loads(result.stdout)["value"] == pytest.approx(python_value())
