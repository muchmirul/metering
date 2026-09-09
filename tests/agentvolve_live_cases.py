"""Prepare ten easy, independent live-test contracts; never launch a workflow.

Usage: uv run python tests/agentvolve_live_cases.py NEW_DIRECTORY MAX_ROUNDS
Review the resulting manifest/profiles before explicitly authorizing live tests.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json  # noqa: E402
from apps.coding_agent.protocol import load_task_profile  # noqa: E402
from apps.coding_agent.task_profile_tool import create_workspace_profile  # noqa: E402

CATALOG = ROOT / "tests/fixtures/agentvolve_easy_tasks.json"


def value_shape(value):
    if isinstance(value, (list, tuple)):
        return [type(value).__name__, [value_shape(item) for item in value]]
    if isinstance(value, dict):
        return [type(value).__name__, {key: value_shape(item) for key, item in value.items()}]
    return type(value).__name__


def output_check(name: str, examples: dict) -> dict:
    # The fixed host compares values AND recursive return types. JSON alone would
    # turn a wrong tuple return into an apparently correct list. No solver/oracle
    # algorithm is shared with candidate code or used to create expected answers.
    code = (
        "import json\nfrom solver import solve\n"
        "def shape(value):\n"
        " if isinstance(value,(list,tuple)): return [type(value).__name__,[shape(x) for x in value]]\n"
        " if isinstance(value,dict): return [type(value).__name__,{k:shape(v) for k,v in value.items()}]\n"
        " return type(value).__name__\n"
        "inputs=json.loads(" + repr(json.dumps(examples["inputs"])) + ")\n"
        "answers=[solve(value) for value in inputs]\n"
        "print(json.dumps({'answers':answers,'types':[shape(value) for value in answers]}))"
    )
    return {"argv": ["python", "-c", code], "case_id": name, "timeout_ms": 10_000,
            "check_schema": "stdout-json-v1", "expected_stdout": {"answers": examples["answers"],
                "types": [value_shape(value) for value in examples["answers"]]}}


def prepare_cases(destination: Path, max_rounds: int) -> dict:
    if type(max_rounds) is not int or not 1 <= max_rounds <= 4:
        raise ValueError("Supply an explicitly chosen generation cap from 1 through 4")
    destination = destination.absolute()
    if destination.resolve() != destination or destination.exists():
        raise ValueError("Live fixtures require a new directory without symlink ancestors; existing evidence is never overwritten")
    catalog = json.loads(CATALOG.read_text())
    if len(catalog) != 10 or len({case["name"] for case in catalog}) != 10:
        raise ValueError("The live catalog must contain ten distinct tasks")
    destination.mkdir(parents=True, mode=0o700)
    manifest = {"authority": "operator-review-required", "max_rounds": max_rounds, "tasks": []}
    for case in catalog:
        seed_directory = destination / "seeds" / case["name"]
        root = seed_directory / "workspaces" / f"task-{uuid.uuid4()}"
        draft = {
            "draft_schema": "agentvolve-session-task-draft-v1", "schema_version": 1,
            "name": case["name"], "repository_path": str(root), "goal": case["goal"],
            "requirements": [case["goal"]], "assumptions": ["Python standard library is available in the reviewed runtime."],
            "entrypoint": "solver.py", "allowed_paths": ["solver.py"],
            "development_checks": [output_check("development", case["development"])],
            "limits": {"max_rounds": max_rounds, "max_proposal_calls": max_rounds, "max_wall_seconds": 3680 * max_rounds},
            "stopping": {"minimum_replicates": 1, "type": "all-development-cases-pass-v1"},
            "final_policy": "replay-development-checks-v1",
        }
        draft_path = destination / f"{case['name']}.draft.json"
        draft_path.write_text(canonical_json(draft) + "\n")
        registered = create_workspace_profile(draft_path, seed_directory)
        # Keep the preparation template unchanged. Author a separate new contract
        # with genuinely separate protected inputs; neither profile has run yet.
        profile = load_task_profile(Path(registered["profile"]))
        del profile["task_id"]
        final = {"checks": [output_check("protected", case["final"])], "final_schema": "darwinian-coding-final-v1", "schema_version": 1}
        final_payload = (canonical_json(final) + "\n").encode("ascii")
        final_path = destination / f"{case['name']}.final.json"
        with final_path.open("xb") as stream:
            stream.write(final_payload)
        final_path.chmod(0o600)
        profile["final_assay"] = {"path": str(final_path), "sha256": hashlib.sha256(final_payload).hexdigest()}
        profile_path = destination / f"{case['name']}.task.json"
        with profile_path.open("x") as stream:
            stream.write(canonical_json(profile) + "\n")
        normalized = load_task_profile(profile_path)
        manifest["tasks"].append({"name": case["name"], "goal": case["goal"], "profile": str(profile_path),
                                  "task_id": normalized["task_id"], "development_examples": len(case["development"]["inputs"]),
                                  "protected_examples": len(case["final"]["inputs"])})
    (destination / "review-manifest.json").write_text(canonical_json(manifest) + "\n")
    return manifest


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError("usage: agentvolve_live_cases.py NEW_DIRECTORY MAX_ROUNDS (1–4; no default)")
        result = prepare_cases(Path(sys.argv[1]), int(sys.argv[2]))
    except (ValueError, OSError) as exc:
        print(f"Fixture preparation failed; any created files are retained: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    print(canonical_json(result))
