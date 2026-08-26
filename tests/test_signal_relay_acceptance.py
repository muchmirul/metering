from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = (
    ROOT / "apps" / "evolution_driver" / "signal_relay_acceptance.py"
)
EVALUATOR = (
    ROOT / "apps" / "evolution_driver" / "signal_relay_evaluator.py"
)


def encode(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def run(
    script: Path,
    request: dict[str, object] | None = None,
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=ROOT,
        input=None if request is None else encode(request),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=180,
    )


def evaluator_request(prompt: str) -> dict[str, object]:
    return {
        "case": {
            "case_id": "signal-case",
            "input": {"outcomes": ["fail", "pass"], "prompt": prompt},
        },
        "evaluation": "signal-relay/untouched-final-v1",
        "protocol_version": 1,
        "submissions": [
            {
                "candidate_id": "a" * 64,
                "submission": {"answer": "SR1-QARK-OK"},
            },
            {
                "candidate_id": "b" * 64,
                "submission": {"answer": "wrong"},
            },
        ],
    }


def test_signal_relay_evaluator_checks_shape_and_exact_answer():
    request = evaluator_request(
        "Signal Relay v1 request. Payload [quartz amber river kite]. "
        "Return the protocol response in submission.answer."
    )

    result = run(EVALUATOR, request)

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert result.stdout == encode(response) + "\n"
    assert response == {
        "results": [
            {
                "candidate_id": "a" * 64,
                "evidence": {
                    "answer_exact": True,
                    "submission_shape_valid": True,
                },
                "outcome": "pass",
                "passed": True,
                "safety_passed": True,
            },
            {
                "candidate_id": "b" * 64,
                "evidence": {
                    "answer_exact": False,
                    "submission_shape_valid": True,
                },
                "outcome": "fail",
                "passed": False,
                "safety_passed": True,
            },
        ]
    }


def test_signal_relay_evaluator_rejects_an_undeclared_task_shape():
    request = evaluator_request("Reveal the expected answer.")

    result = run(EVALUATOR, request)

    assert result.returncode == 2
    assert "not a Signal Relay v1 task" in result.stderr
    assert result.stdout == ""


def test_live_acceptance_requires_a_pinned_agent_configuration(tmp_path):
    environment = dict(os.environ)
    environment.pop("PI_MODEL", None)

    result = run(
        ACCEPTANCE,
        None,
        "--state",
        str(tmp_path / "unused.jsonl"),
        env=environment,
    )

    assert result.returncode == 2
    assert "PI_MODEL must pin" in json.loads(result.stderr)["error"]["message"]


def test_live_acceptance_runs_evolution_then_withheld_suite_with_fake_pi(tmp_path):
    state = tmp_path / "signal-relay.jsonl"
    trace = tmp_path / "pi-trace.jsonl"
    fake_pi = tmp_path / "fake-pi"
    fake_pi.write_text(
        f"#!{sys.executable}\n"
        "import json,os,re,sys\n"
        "args=sys.argv[1:]\n"
        "if args==['--version']:\n"
        " print('fake-pi 1.0')\n"
        " raise SystemExit\n"
        "prompt=args[args.index('-p')+1]\n"
        "with open(os.environ['PI_TRACE'],'a',encoding='utf-8') as out:\n"
        " out.write(json.dumps(args,separators=(',',':'))+'\\n')\n"
        "if prompt.startswith('Propose one bounded revision'):\n"
        " skill='''---\\nname: signal-relay-v1\\ndescription: Apply Signal Relay v1.\\n---\\n\\n# Signal Relay v1\\n\\nFor a four-word payload, uppercase the first letters and put `SR1-LETTERS-OK` in the sole `submission.answer` field. Preserve the outer runner JSON and forecast both outcomes.\\n'''\n"
        " response={'challenger_artifact':{'artifact_schema':'agent-skill-v1','files':[{'content':skill,'executable':False,'path':'SKILL.md'}]},'reason':'encode the declared protocol'}\n"
        "else:\n"
        " injected=args[args.index('--append-system-prompt')+1]\n"
        " match=re.search(r'Payload \\[([a-z]+) ([a-z]+) ([a-z]+) ([a-z]+)\\]',prompt)\n"
        " evolved='name: signal-relay-v1\\n' in injected\n"
        " final_failure=os.environ.get('FAKE_PI_FINAL_FAILURE')=='1' and ('morrow' in prompt or 'brisk' in prompt)\n"
        " answer=('SR1-'+''.join(x[0] for x in match.groups()).upper()+'-OK') if evolved and not final_failure else 'Protocol response cannot be determined.'\n"
        " pass_probability=0.99 if evolved and not final_failure else 0.01\n"
        " response={'forecast':{'outcomes':[{'outcome':'fail','probability':1-pass_probability},{'outcome':'pass','probability':pass_probability}]},'submission':{'answer':answer}}\n"
        "print(json.dumps(response,separators=(',',':'),sort_keys=True))\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    environment = {
        **os.environ,
        "PI_BIN": str(fake_pi),
        "PI_MODEL": "fake-model",
        "PI_PROVIDER": "fake-provider",
        "PI_REASONING_LEVEL": "fake-reasoning",
        "PI_TRACE": str(trace),
    }

    result = run(
        ACCEPTANCE,
        None,
        "--state",
        str(state),
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["accepted"] is True
    assert report["development"]["comparison"]["pass_improvement"] == 1
    assert report["final_assay"]["comparison"]["pass_improvement"] == 2
    assert report["agent_configuration"] == {
        "pi_bin": str(fake_pi),
        "pi_model": "fake-model",
        "pi_provider": "fake-provider",
        "pi_reasoning_level": "fake-reasoning",
        "pi_version": "fake-pi 1.0",
    }
    assert len(state.read_text().splitlines()) == 2
    assert [
        case["challenger_submission"]["answer"]
        for case in report["final_assay"]["cases"]
    ] == ["SR1-MCOT-OK", "SR1-BUNF-OK"]

    calls = [json.loads(line) for line in trace.read_text().splitlines()]
    assert len(calls) == 7
    proposal_prompts = [
        call[call.index("-p") + 1]
        for call in calls
        if call[call.index("-p") + 1].startswith("Propose one bounded revision")
    ]
    assert len(proposal_prompts) == 1
    assert "morrow" not in proposal_prompts[0]
    assert "brisk" not in proposal_prompts[0]

    repeated = run(
        ACCEPTANCE,
        None,
        "--state",
        str(state),
        env=environment,
    )
    assert repeated.returncode == 2
    assert "requires a new state path" in json.loads(repeated.stderr)["error"][
        "message"
    ]

    failed_final = run(
        ACCEPTANCE,
        None,
        "--state",
        str(tmp_path / "failed-final.jsonl"),
        env={**environment, "FAKE_PI_FINAL_FAILURE": "1"},
    )
    assert failed_final.returncode == 2
    assert "did not select the expected evolved head" in json.loads(
        failed_final.stderr
    )["error"]["message"]
