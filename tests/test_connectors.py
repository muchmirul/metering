from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from connectors.fixed.pi.environment import (  # noqa: E402
    isolated_configuration as isolated_pi_configuration,
)
from connectors.fixed.prime_agent.environment import (  # noqa: E402
    isolated_configuration as isolated_prime_configuration,
)
PI_PROPOSER = ROOT / "connectors" / "fixed" / "pi" / "skill_proposer.py"
PRIME_PROPOSER = (
    ROOT / "connectors" / "fixed" / "prime_agent" / "skill_proposer.py"
)
PI_RUNNER = ROOT / "connectors" / "fixed" / "pi" / "text_runner.py"
PRIME_RUNNER = ROOT / "connectors" / "fixed" / "prime_agent" / "text_runner.py"
INVOKER = ROOT / "connectors" / "tools" / "metering" / "invoke.py"
LIVE_ACCEPTANCE = ROOT / "connectors" / "live_agent_acceptance.py"


def encode(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def skill_artifact(text: str) -> dict[str, object]:
    return {
        "artifact_schema": "agent-skill-v1",
        "files": [{"content": text, "executable": False, "path": "SKILL.md"}],
    }


def candidate(artifact: dict[str, object]) -> dict[str, object]:
    candidate_id = hashlib.sha256(
        encode({"artifact": artifact, "candidate_schema": "agent-candidate-v1"}).encode(
            "ascii"
        )
    ).hexdigest()
    return {"artifact": artifact, "candidate_id": candidate_id}


def fake_agent(tmp_path: Path, response: dict[str, object]) -> tuple[Path, Path]:
    trace = tmp_path / "agent-arguments.json"
    binary = tmp_path / "fake-agent"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "json.dump(sys.argv[1:],open(os.environ['AGENT_TRACE'],'w'))\n"
        f"print({encode(response)!r})\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary, trace


@pytest.mark.parametrize(
    ("script", "command_environment"),
    [
        (PI_PROPOSER, "METERING_PI_COMMAND"),
        (PRIME_PROPOSER, "METERING_PRIME_AGENT_COMMAND"),
    ],
)
def test_fixed_skill_proposers_use_isolated_concrete_agent_commands(
    tmp_path: Path,
    script: Path,
    command_environment: str,
):
    revised = skill_artifact(
        "---\nname: revised\ndescription: Revised connector skill.\n---\n"
    )
    response = {"challenger_artifact": revised, "reason": "bounded revision"}
    binary, trace = fake_agent(tmp_path, response)
    parent = skill_artifact(
        "---\nname: current\ndescription: Current connector skill.\n---\n"
    )
    request = {
        "context": {"objective": "revise one instruction"},
        "parent": candidate(parent),
        "protocol_version": 1,
    }
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        input=encode(request),
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            command_environment: encode([str(binary), "--pinned-model"]),
            "AGENT_TRACE": str(trace),
        },
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == response
    arguments = json.loads(trace.read_text(encoding="utf-8"))
    assert arguments[0] == "--pinned-model"
    assert "--no-session" in arguments
    assert "--no-context-files" in arguments
    assert "--no-tools" in arguments
    assert arguments[arguments.index("--skill") + 1].endswith("/SKILL.md")
    injected = arguments[arguments.index("--append-system-prompt") + 1]
    assert "name: current" in injected
    assert "separate evaluator decides" in arguments[arguments.index("-p") + 1]


@pytest.mark.parametrize(
    ("script", "command_environment"),
    [
        (PI_RUNNER, "METERING_PI_COMMAND"),
        (PRIME_RUNNER, "METERING_PRIME_AGENT_COMMAND"),
    ],
)
def test_fixed_text_runners_use_the_same_strict_candidate_protocol(
    tmp_path: Path,
    script: Path,
    command_environment: str,
):
    response = {
        "forecast": {
            "outcomes": [
                {"outcome": "fail", "probability": 0.25},
                {"outcome": "pass", "probability": 0.75},
            ]
        },
        "submission": {"answer": "ok"},
    }
    binary, trace = fake_agent(tmp_path, response)
    skill = tmp_path / "candidate"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: candidate\ndescription: Candidate connector skill.\n---\n",
        encoding="utf-8",
    )
    request = {
        "candidate": {"candidate_id": "1" * 64, "skill_path": str(skill)},
        "protocol_version": 1,
        "task": {
            "case_id": "connector-case",
            "input": {"outcomes": ["fail", "pass"], "prompt": "Answer."},
        },
    }
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        input=encode(request),
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            command_environment: encode([str(binary), "--pinned-model"]),
            "AGENT_TRACE": str(trace),
        },
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == response
    arguments = json.loads(trace.read_text(encoding="utf-8"))
    assert arguments[0] == "--pinned-model"
    assert "--no-tools" in arguments
    assert arguments[arguments.index("--skill") + 1] == str(skill / "SKILL.md")
    injected = arguments[arguments.index("--append-system-prompt") + 1]
    assert "name: candidate" in injected
    prompt = arguments[arguments.index("-p") + 1]
    assert '"probability":0.5' in prompt
    assert '"submission":{}' in prompt


def test_prime_connector_excludes_ambient_harness_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "prime-config"
    source.mkdir()
    (source / "auth.json").write_text('{"credential":"test"}\n', encoding="utf-8")
    (source / "models.json").write_text('{"providers":{}}\n', encoding="utf-8")
    (source / "harness").mkdir()
    (source / "harness" / "harness_state.json").write_text(
        '{"entries":{"memory":{"secret":{}}}}\n', encoding="utf-8"
    )
    monkeypatch.setenv("PRIME_AGENT_CODING_AGENT_DIR", str(source))
    monkeypatch.delenv("METERING_PRIME_AGENT_CONFIG_DIR", raising=False)

    with isolated_prime_configuration():
        isolated = Path(os.environ["PRIME_AGENT_CODING_AGENT_DIR"])
        assert isolated != source
        assert (isolated / "auth.json").is_file()
        assert (isolated / "models.json").is_file()
        assert not (isolated / "harness").exists()
    assert os.environ["PRIME_AGENT_CODING_AGENT_DIR"] == str(source)
    assert not isolated.exists()

    with isolated_prime_configuration(include_auth=False):
        tool_enabled = Path(os.environ["PRIME_AGENT_CODING_AGENT_DIR"])
        assert (tool_enabled / "models.json").is_file()
        assert not (tool_enabled / "auth.json").exists()
    assert not tool_enabled.exists()


def test_pi_connector_excludes_ambient_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "pi-config"
    source.mkdir()
    (source / "auth.json").write_text('{"credential":"test"}\n', encoding="utf-8")
    (source / "models.json").write_text('{"providers":{}}\n', encoding="utf-8")
    (source / "settings.json").write_text('{"skills":["ambient"]}\n', encoding="utf-8")
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(source))
    monkeypatch.delenv("METERING_PI_CONFIG_DIR", raising=False)

    with isolated_pi_configuration():
        isolated = Path(os.environ["PI_CODING_AGENT_DIR"])
        assert isolated != source
        assert (isolated / "auth.json").is_file()
        assert (isolated / "models.json").is_file()
        assert not (isolated / "settings.json").exists()
    assert os.environ["PI_CODING_AGENT_DIR"] == str(source)
    assert not isolated.exists()

    with isolated_pi_configuration(include_auth=False):
        tool_enabled = Path(os.environ["PI_CODING_AGENT_DIR"])
        assert (tool_enabled / "models.json").is_file()
        assert not (tool_enabled / "auth.json").exists()
    assert not tool_enabled.exists()


def test_agent_tool_invoker_preserves_the_public_metering_boundary():
    request = {"measure": "entropy", "probabilities": [0.5, 0.5]}

    result = subprocess.run(
        [sys.executable, str(INVOKER)],
        cwd=ROOT,
        input=encode(request),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert result.stdout == encode(response) + "\n"
    assert response == {
        "base": 2.0,
        "infinite": False,
        "measure": "entropy",
        "value": 1.0,
    }


@pytest.mark.live_agents
@pytest.mark.skipif(
    os.environ.get("METERING_RUN_LIVE_AGENT_TESTS") != "1",
    reason="set METERING_RUN_LIVE_AGENT_TESTS=1 for real harness inference",
)
def test_real_pi_and_prime_agent_call_the_metering_tool():
    model = os.environ.get("METERING_LIVE_AGENT_MODEL")
    assert model, "METERING_LIVE_AGENT_MODEL must select a model available to both"

    result = subprocess.run(
        [sys.executable, str(LIVE_ACCEPTANCE), "--model", model],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=420,
        env=os.environ,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "accepted"
    assert [item["agent"] for item in report["agents"]] == ["pi", "prime-agent"]
    assert all(item["metering_response"]["value"] == 3.0 for item in report["agents"])
