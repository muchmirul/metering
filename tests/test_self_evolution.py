from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTATOR = ROOT / "apps" / "mutator" / "mutator.py"
PI_PROPOSER = ROOT / "connectors" / "fixed" / "pi" / "skill_proposer.py"
DEMO_PROPOSER = ROOT / "apps" / "evolution_driver" / "demo_proposer.py"
EVOLVER = ROOT / "apps" / "evolution_driver" / "evolver.py"
EXAMPLE = ROOT / "apps" / "evolution_driver" / "example-request.json"
RUNNER = ROOT / "apps" / "controller" / "demo_agent_adapter.py"
EVALUATOR = ROOT / "apps" / "controller" / "demo_evaluator_adapter.py"


def encode(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def digest(value: object) -> str:
    return hashlib.sha256(encode(value).encode("ascii")).hexdigest()


def candidate(artifact: dict[str, object]) -> dict[str, object]:
    return {
        "artifact": artifact,
        "candidate_id": digest(
            {"artifact": artifact, "candidate_schema": "agent-candidate-v1"}
        ),
    }


def default_artifact() -> dict[str, object]:
    return {"artifact_schema": "agent-default-v1"}


def skill_artifact(text: str) -> dict[str, object]:
    return {
        "artifact_schema": "agent-skill-v1",
        "files": [
            {"content": text, "executable": False, "path": "SKILL.md"}
        ],
    }


def run(
    script: Path,
    request: dict[str, object],
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=ROOT,
        input=encode(request),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )


def proposal_request(command: list[str]) -> dict[str, object]:
    return {
        "parent_artifact": default_artifact(),
        "proposal_context": {
            "generation": 1,
            "objective": {
                "required_text": "Run relevant tests before claiming completion."
            },
            "previous_generation": None,
        },
        "proposer": {"command": command, "timeout_seconds": 10},
        "schema_version": 2,
    }


def evolution_request() -> dict[str, object]:
    request = json.loads(EXAMPLE.read_text())
    request["proposal"]["command"] = [sys.executable, str(DEMO_PROPOSER)]
    request["generation"]["runner"]["command"] = [sys.executable, str(RUNNER)]
    request["generation"]["evaluator"]["command"] = [
        sys.executable,
        str(EVALUATOR),
    ]
    return request


def test_mutator_owns_one_strict_skill_proposal():
    result = run(
        MUTATOR,
        proposal_request([sys.executable, str(DEMO_PROPOSER)]),
    )

    assert result.returncode == 0, result.stderr
    mutation = json.loads(result.stdout)
    assert mutation["schema_version"] == 2
    assert mutation["parent"]["artifact"] == default_artifact()
    assert mutation["mutation"]["changed_paths"] == ["SKILL.md"]
    assert mutation["mutation"]["producer"] == digest(
        {"command": [sys.executable, str(DEMO_PROPOSER)]}
    )
    files = mutation["child"]["artifact"]["files"]
    assert [item["path"] for item in files] == ["SKILL.md"]


def test_mutator_rejects_a_proposer_that_returns_no_change():
    response = {
        "challenger_artifact": default_artifact(),
        "reason": "no change",
    }
    command = [sys.executable, "-c", f"print({encode(response)!r})"]

    result = run(MUTATOR, proposal_request(command))

    assert result.returncode == 2
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "invalid_request"
    assert "agent-skill-v1" in error["message"]


def test_fixed_pi_skill_proposer_is_tool_free_and_injects_the_parent(tmp_path):
    trace = tmp_path / "argv.json"
    fake_pi = tmp_path / "fake-pi"
    response = {
        "challenger_artifact": skill_artifact(
            "---\nname: revised\ndescription: Revised skill.\n---\n"
        ),
        "reason": "bounded revision",
    }
    fake_pi.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "json.dump(sys.argv[1:],open(os.environ['PI_TRACE'],'w'))\n"
        f"print({encode(response)!r})\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    parent_artifact = skill_artifact(
        "---\nname: current\ndescription: Current skill.\n---\n"
    )
    request = {
        "context": {"objective": "revise"},
        "parent": candidate(parent_artifact),
        "protocol_version": 1,
    }

    result = run(
        PI_PROPOSER,
        request,
        env={
            **os.environ,
            "METERING_PI_COMMAND": encode([str(fake_pi)]),
            "PI_BIN": str(fake_pi),
            "PI_TRACE": str(trace),
        },
    )

    assert result.returncode == 0, result.stderr
    arguments = json.loads(trace.read_text())
    assert "--no-tools" in arguments
    assert "--no-context-files" in arguments
    assert "--no-session" in arguments
    assert arguments[arguments.index("--skill") + 1].endswith("/SKILL.md")
    injected = arguments[arguments.index("--append-system-prompt") + 1]
    assert "name: current" in injected
    assert json.loads(result.stdout) == response


def test_evolver_runs_one_complete_fake_pi_proposal_generation(tmp_path):
    state = tmp_path / "pi-evolution.jsonl"
    fake_pi = tmp_path / "fake-pi"
    response = {
        "challenger_artifact": skill_artifact(
            "---\nname: pi-revised\ndescription: Revised by fake Pi.\n---\n\n"
            "Run relevant tests before claiming completion.\n"
        ),
        "reason": "one bounded fake Pi proposal",
    }
    fake_pi.write_text(
        f"#!{sys.executable}\nprint({encode(response)!r})\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    request = evolution_request()
    request["proposal"]["command"] = [sys.executable, str(PI_PROPOSER)]
    request["limits"]["max_generations"] = 1

    result = run(
        EVOLVER,
        request,
        "--state",
        str(state),
        env={
            **os.environ,
            "METERING_PI_COMMAND": encode([str(fake_pi)]),
            "PI_BIN": str(fake_pi),
        },
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "generation_limit"
    assert summary["completed_generations"] == 1
    generation = json.loads(state.read_text().splitlines()[1])
    assert generation["controller_result"]["selection"]["decision"] == (
        "promote_challenger"
    )
    assert summary["head"] == generation["controller_result"]["mutation"]["child"]


def test_evolver_promotes_then_rejects_and_resumes_without_appending(tmp_path):
    state = tmp_path / "evolution.jsonl"
    request = evolution_request()

    first = run(EVOLVER, request, "--state", str(state))

    assert first.returncode == 0, first.stderr
    summary = json.loads(first.stdout)
    assert summary["status"] == "rejection_limit"
    assert summary["completed_generations"] == 2
    assert summary["consecutive_rejections"] == 1
    records = [json.loads(line) for line in state.read_text().splitlines()]
    assert len(records) == 3
    assert records[1]["controller_result"]["selection"]["decision"] == (
        "promote_challenger"
    )
    assert records[2]["controller_result"]["selection"]["decision"] == (
        "retain_incumbent"
    )
    promoted = records[1]["controller_result"]["next_parent"]
    assert summary["head"] == promoted
    assert records[2]["controller_result"]["next_parent"] == promoted
    for line, record in zip(state.read_text().splitlines(), records, strict=True):
        assert line == encode(record)
        payload = {key: value for key, value in record.items() if key != "record_id"}
        assert record["record_id"] == digest(payload)

    before = state.read_bytes()
    resumed = run(EVOLVER, request, "--state", str(state))

    assert resumed.returncode == 0, resumed.stderr
    assert resumed.stdout == first.stdout
    assert state.read_bytes() == before

    conflicting = json.loads(encode(request))
    conflicting["proposal"]["context"]["required_text"] = "Different objective"
    conflict = run(EVOLVER, conflicting, "--state", str(state))
    assert conflict.returncode == 2
    assert "different evolution request" in json.loads(conflict.stderr)["error"][
        "message"
    ]
    assert state.read_bytes() == before

    state.unlink()
    recreated = run(EVOLVER, request, "--state", str(state))
    assert recreated.returncode == 0, recreated.stderr
    assert recreated.stdout == first.stdout
    assert state.read_bytes() == before


def test_evolver_rejects_tampered_state(tmp_path):
    state = tmp_path / "evolution.jsonl"
    request = evolution_request()
    result = run(EVOLVER, request, "--state", str(state))
    assert result.returncode == 0, result.stderr

    records = state.read_text().splitlines()
    tampered = json.loads(records[1])
    tampered["controller_result"]["selection"]["reason"] = "forged"
    records[1] = encode(tampered)
    state.write_text("\n".join(records) + "\n", encoding="utf-8")

    rejected = run(EVOLVER, request, "--state", str(state))

    assert rejected.returncode == 2
    error = json.loads(rejected.stderr)["error"]
    assert error["code"] == "evolution_error"
    assert "record_id does not match" in error["message"]


def test_failed_generation_never_appends_a_generation_record(tmp_path):
    state = tmp_path / "evolution.jsonl"
    request = evolution_request()
    request["proposal"]["command"] = [
        sys.executable,
        "-c",
        "print('not-json')",
    ]

    result = run(EVOLVER, request, "--state", str(state))

    assert result.returncode == 2
    assert "returned invalid JSON" in json.loads(result.stderr)["error"]["message"]
    records = state.read_text().splitlines()
    assert len(records) == 1
    assert json.loads(records[0])["kind"] == "run"
