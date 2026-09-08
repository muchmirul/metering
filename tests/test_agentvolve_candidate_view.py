"""Read-only tree/report projections over controlled ledger + actual Git fixtures.

Fixture records are not a claimed Population experiment or assay replay.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.journal import content_record  # noqa: E402
from apps._support.wire import canonical_digest, canonical_json  # noqa: E402
from apps.coding_agent.candidate_view import report_view, tree_view  # noqa: E402
from apps.coding_agent.operator_view import OperatorViewError, main  # noqa: E402


def save(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(document) + "\n", encoding="ascii")


def save_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical_json(record) + "\n" for record in records), encoding="ascii")


def fixture_run(directory: Path, kind: str = "harness", *, final: bool = True) -> tuple[Path, list[str]]:
    root = directory / f"{kind}-pi-20260906T190000000Z"
    root.mkdir(parents=True)
    source = directory / f"source-{kind}"
    source.mkdir()

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=source, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Projection fixture")
    git("config", "user.email", "fixture@example.invalid")
    commits = []
    parents = [None, 0, 0, 1]
    ids = [hashlib.sha256(f"{kind}-{index}".encode()).hexdigest() for index in range(4)]
    for index, parent in enumerate(parents):
        if parent is not None:
            git("checkout", "-q", "--detach", commits[parent])
        (source / "policy.py").write_text("\n".join(f"# candidate {index} line {line}" for line in range(120)) + "\n")
        git("add", "policy.py")
        git("commit", "-qm", f"candidate {index}")
        commits.append(git("rev-parse", "HEAD"))
    git("clone", "--bare", "-q", str(source), str(root / "candidate.git"))
    population = [content_record({"kind": "population", "sequence": 0}, ValueError)]

    def pop(kind_: str, body: dict) -> str:
        record = content_record({"kind": kind_, "body": body, "sequence": len(population), "parent_record_id": population[-1]["record_id"]}, ValueError)
        population.append(record)
        return record["record_id"]

    def register(index: int) -> str:
        parent = parents[index]
        return pop("candidate", {"candidate": {"candidate_id": ids[index], "artifact": {
            "commit": commits[index], "git_tree": git("rev-parse", commits[index] + "^{tree}"), "entrypoint": "policy.py"}},
            "parents": [] if parent is None else [ids[parent]], "variation": {"type": "seed-v1" if parent is None else "mutation-v1"}})

    register(0)
    pop("experiment", {"experiment_id": "dev", "experiment": {"role": "development"}})
    driver = [content_record({"kind": "population-driver", "parent_record_id": None,
        "seed_candidate_id": ids[0], "experiment_id": "dev", "configuration": {"limits": {"max_rounds": 3}}}, ValueError)]
    allocation = None
    for index in range(1, 4):
        parent = parents[index]
        assert parent is not None
        registration = register(index)
        run_refs = []
        for candidate_index in (parent, index):
            run_refs.append(pop("run", {"run": {"candidate_id": ids[candidate_index], "experiment_id": "dev", "replicate_id": f"r{index}-{candidate_index}"},
                "evidence": {"task": {"passed_count": 1, "case_count": 2, "safety_failures": 0}, "cost": {"tokens": 10, "wall_milliseconds": 25}},
                "measurements": {"task_rate": 0.5, "budget_passed": True}}))
        members = [0, 1] if index == 1 else [1, 2] if index == 2 else [2, 3]
        archive = pop("archive", {"experiment_id": "dev", "members": [{"candidate_id": ids[item]} for item in members],
            "excluded": [{"candidate_id": ids[item], "reason": "capacity" if item == 1 else "dominated"} for item in range(index + 1) if item not in members]})
        next_allocation = pop("allocation", {"request": {"archive_record_id": archive, "draw": {"numerator": 0, "denominator": 1}},
            "result": {"selected_candidate_id": ids[0 if index == 1 else 1]}}) if index < 3 else None
        attempt = hashlib.sha256(f"attempt-{kind}-{index}".encode()).hexdigest()
        controller = {"attempt_id": attempt, "controller_request": {"secret_prompt": "NEVER_DISPLAY_THE_PROMPT"},
            "controller_result": {"mutation": {"parent": {"candidate_id": ids[parent]}, "child": {"candidate_id": ids[index]},
                "mutation": {"reason": "Try a different policy", "proposal_id": f"proposal-{index}"}},
                **{key: {"candidate": ids[candidate_index], "cases": [{"case_id": "public-case", "passed": False, "safety_passed": True, "outcome": "fail"}]}
                   for key, candidate_index in (("incumbent_report", parent), ("challenger_report", index))}}}
        receipt_path = root / f"state/receipts/{attempt}.controller.json"
        save(receipt_path, controller)
        driver.append(content_record({"kind": "round", "parent_record_id": driver[-1]["record_id"], "round": index,
            "intent_id": f"intent-{index}", "parent_candidate_id": ids[parent], "child_candidate_id": ids[index],
            "parent_allocation_record_id": allocation, "next_allocation_record_id": next_allocation,
            "attempts": [{"attempt_id": attempt, "ordinal": 1, "reason": "initial", "retry": False, "wall_reservation_seconds": 60}],
            "controller_receipt": {"name": receipt_path.name, "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest()},
            "population_record_ids": {"candidate": registration, "incumbent_run": run_refs[0], "challenger_run": run_refs[1], "archive": archive},
            "archive_member_candidate_ids": [ids[item] for item in members],
            "selection": {"decision": "retain_incumbent", "selected": ids[parent], "reason": "no improvement", "comparison": {"incumbent": {"passed_count": 1}, "challenger": {"passed_count": 1}}}}, ValueError))
        allocation = next_allocation
    if final:
        pop("experiment", {"experiment_id": "final", "experiment": {"role": "final"}})
        pop("run", {"run": {"candidate_id": ids[3], "experiment_id": "final"}, "evidence": {
            "task": {"case_count": 2, "passed_count": 2, "safety_failures": 0}, "cost": {"tokens": 0}}})
    save_records(root / "state/population/population.jsonl", population)
    save_records(root / "state/driver.jsonl", driver)
    return root, ids


def every_event(runs: Path, root: Path, label: str, loop: bool = False) -> list[dict]:
    events = []
    offset = 0
    while True:
        report = report_view(runs, root.name, label, offset, loop=loop)
        events.extend(report["events"])
        if report["next_offset"] is None:
            return events
        offset = report["next_offset"]


def test_branching_tree_labels_status_and_every_child_report(tmp_path: Path):
    root, ids = fixture_run(tmp_path)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    tree = tree_view(tmp_path, root.name)
    nodes = tree["items"]
    assert [item["label"] for item in nodes] == ["H0", "H1", "H3", "H2"]
    assert [item["tree_prefix"] for item in nodes] == ["", "├─ ", "│  └─ ", "└─ "]
    assert [item["parent_label"] for item in nodes] == [None, "H0", "H1", "H0"]
    assert [item["status"] for item in nodes] == ["eliminated", "eliminated", "selected", "retained"]
    assert nodes[1]["exclusion_reason"] == "capacity"
    for index in range(4):
        report = report_view(tmp_path, root.name, f"H{index}")
        assert report["node"]["candidate_id"] == ids[index]
        assert report["evidence"]["development"]["total_cases"] > 0
        assert (report["evidence"]["final"] is not None) == (index == 3)
        events = every_event(tmp_path, root, f"H{index}")
        assert {"registration", "proposal attempt", "mutation / Git child", "independent evaluation", "development check", "pairwise Selection Gate", "Population archive", "next parent allocation"} <= {event["step"] for event in events}
        assert "NEVER_DISPLAY_THE_PROMPT" not in json.dumps(events)
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_historical_child_diff_is_complete_and_paginated(tmp_path: Path):
    root, _ids = fixture_run(tmp_path, "solution")
    offset = 0
    lines = []
    while True:
        page = report_view(tmp_path, root.name, "S1", diff_offset=offset)["diff"]
        assert page["available"] and page["warning"] is None
        lines.extend(page["lines"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert offset > 40
    assert "# candidate 1 line 119" in "\n".join(lines)
    assert "# candidate 0 line 119" in "\n".join(lines)
    assert "# candidate 3" not in "\n".join(lines)
    assert len(lines) == page["total_lines"]
    assert report_view(tmp_path, root.name, "S0")["diff"]["available"] is False


def test_pending_failed_attempts_have_steps_but_no_invented_child(tmp_path: Path):
    root, ids = fixture_run(tmp_path, final=False)
    attempt = "a" * 64
    pending = {"round": 4, "intent_id": "pending-4", "stage": "controller_pending", "last_error": "requires retry",
        "parent_candidate_id": ids[2], "parent_allocation_record_id": None, "controller_receipt": None,
        "attempts": [{"attempt_id": attempt, "reason": "initial", "wall_reservation_seconds": 60, "retry": False},
                     {"attempt_id": "b" * 64, "reason": "operator approved retry", "wall_reservation_seconds": 60, "retry": True}]}
    save(root / "state/pending/round-intent.json", {**pending, "pending_id": canonical_digest(pending)})
    diagnostic = {"diagnostic_schema": "population-driver-failure-v1", "authority": "diagnostic-only", "attempt_id": attempt,
        "intent_id": "pending-4", "error": {"summary": "timeout", "stderr_excerpt": "\x1b[31mBearer secret-credential"}}
    encoded = (canonical_json(diagnostic) + "\n").encode()
    save(root / f"state/diagnostics/{hashlib.sha256(encoded).hexdigest()}.json", diagnostic)
    assert tree_view(tmp_path, root.name)["total_items"] == 4
    loops = tree_view(tmp_path, root.name, loops=True)["items"]
    assert loops[-1]["label"] == "HR4" and loops[-1]["child_label"] is None
    events = every_event(tmp_path, root, "HR4", loop=True)
    assert "failed (diagnostic-only)" in events[1]["summary"]
    assert "pending / indeterminate" in events[2]["summary"]
    assert "secret-credential" not in json.dumps(events)
    assert not any(event["step"] == "mutation / Git child" for event in events)


def test_rejects_corruption_unsafe_selectors_and_symlinked_evidence(tmp_path: Path):
    root, _ids = fixture_run(tmp_path)
    for label in ("../S1", "H-1", "H01", "H99"):
        with pytest.raises(OperatorViewError):
            report_view(tmp_path, root.name, label)
    with pytest.raises(OperatorViewError):
        tree_view(tmp_path, "../outside")
    with pytest.raises(OperatorViewError, match="nonnegative"):
        tree_view(tmp_path, root.name, -1)
    ledger = root / "state/population/population.jsonl"
    original = ledger.read_bytes()
    ledger.write_bytes(original.replace(b'policy.py', b'BROKEN.py', 1))
    with pytest.raises(OperatorViewError, match="does not match"):
        tree_view(tmp_path, root.name)
    ledger.write_bytes(original)
    real = root / "saved-population"
    ledger.parent.rename(real)
    ledger.parent.symlink_to(real, target_is_directory=True)
    with pytest.raises(OperatorViewError, match="symlink"):
        tree_view(tmp_path, root.name)


def test_no_protected_profile_access_or_unselected_final_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    root, _ids = fixture_run(tmp_path)
    protected = root / "protected-final.json"
    protected.write_text("DO NOT OPEN")
    original = Path.read_text

    def guard(path, *args, **kwargs):
        assert path != protected
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guard)
    assert main(["candidate", str(tmp_path), root.name, "H1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["evidence"]["final"] is None
    assert "not evaluated" in report["evidence"]["final_status"]
    assert main(["loop", str(tmp_path), root.name, "HR1"]) == 0
    assert main(["candidate", str(tmp_path), root.name, "H1", "-1"]) == 2


def test_labels_stay_stable_when_tree_grows_and_all_nodes_page(tmp_path: Path):
    root, ids = fixture_run(tmp_path, final=False)
    before = {node["candidate_id"]: node["label"] for node in tree_view(tmp_path, root.name)["items"]}
    path = root / "state/population/population.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    seed_body = next(record["body"] for record in records if record.get("kind") == "candidate")
    for index in range(4, 27):
        identity = hashlib.sha256(f"later-{index}".encode()).hexdigest()
        record = content_record({"kind": "candidate", "parent_record_id": records[-1]["record_id"],
            "body": {"candidate": {**seed_body["candidate"], "candidate_id": identity},
                     "parents": [ids[0]], "variation": {"type": "mutation-v1"}}}, ValueError)
        records.append(record)
    save_records(path, records)
    first, second = tree_view(tmp_path, root.name), tree_view(tmp_path, root.name, 20)
    assert first["next_offset"] == 20 and second["next_offset"] is None
    nodes = first["items"] + second["items"]
    assert len(nodes) == first["total_items"] == 27
    assert before.items() <= {node["candidate_id"]: node["label"] for node in nodes}.items()
    assert next(node for node in nodes if node["label"] == "H26")["status"] == "not-yet-archived"


def test_workflow_reports_keep_reused_harness_and_solution_separate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from apps.coding_agent import agentvolve_worker as worker

    harness, _ids = fixture_run(tmp_path / "archived", "harness")
    descriptor = harness / "selected-harness.json"
    save(descriptor, {})
    task, runtime = tmp_path / "task.json", tmp_path / "runtime.json"
    save(task, {})
    save(runtime, {"model": {"connector": "pi", "provider": "fixture", "model": "fixture", "reasoning": "off"}})
    with monkeypatch.context() as patch:
        patch.setattr(worker, "_preflight_workflow", lambda *_args: None)
        patch.setattr(worker.subprocess, "Popen", lambda *_args, **_kwargs: type("Process", (), {"pid": 43210})())
        launched = worker.start_workflow(tmp_path / "runs", task, runtime, descriptor)
    workflow = Path(str(launched["workflow_root"]))
    request = worker.load_workflow_request(workflow)
    solution, _ids = fixture_run(tmp_path / "new", "solution")
    solution.rename(Path(str(request["solution_run_root"])))
    nodes = tree_view(tmp_path / "runs", workflow.name)["items"]
    assert [node["label"] for node in nodes] == ["H0", "H1", "H3", "H2", "S0", "S1", "S3", "S2"]
    assert [node["reused"] for node in nodes] == [True] * 4 + [False] * 4
    report = report_view(tmp_path / "runs", workflow.name, "H1")
    assert report["node"]["run_root"] == str(harness)
    assert report["node"]["reused"] is True
    assert report["evidence"]["final"] is None

    from apps.coding_agent.trace_view import TraceSnapshot

    trace = TraceSnapshot(tmp_path / "runs", workflow.name)
    graph = trace.graph()
    assert [source["reused"] for source in graph["sources"]] == [True, False]
    assert graph["sources"][0]["run_root"] == str(harness)
    assert {node["display_label"] for node in graph["nodes"]} == {"H0", "H1a", "H1b", "H2a", "S0", "S1a", "S1b", "S2a"}
    for node in graph["nodes"]:
        assert trace.files[node["kind"]].inventory(node["candidate_id"])


def test_diff_limits_long_lines_and_missing_controller_are_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from apps.coding_agent import candidate_view

    root, _ids = fixture_run(tmp_path)
    monkeypatch.setattr(candidate_view, "_git_output", lambda *_args, **_kwargs: "header\n" + "+" + "x" * 800 + "\n")
    diff = report_view(tmp_path, root.name, "H1")["diff"]
    assert diff["available"] and diff["total_lines"] == 6
    assert "".join(diff["lines"][1:]) == "+" + "x" * 800
    assert max(map(len, diff["lines"])) <= 200

    def overflow(*_args, **_kwargs):
        raise OperatorViewError("Git diff exceeds output bound")

    monkeypatch.setattr(candidate_view, "_git_output", overflow)
    diff = report_view(tmp_path, root.name, "H1")["diff"]
    assert not diff["available"] and "exceeds output bound" in diff["warning"]
    for path in (root / "state/receipts").iterdir():
        path.unlink()
    events = every_event(tmp_path, root, "H1")
    assert any(event["step"] == "Controller details unavailable" and "missing" in event["summary"] for event in events)
    assert any(event["step"] == "independent evaluation" for event in events)


def test_stale_pending_is_deduplicated_and_corrupt_pending_or_diagnostics_rejected(tmp_path: Path):
    root, ids = fixture_run(tmp_path)
    pending = {"round": 3, "intent_id": "intent-3", "stage": "controller_complete", "parent_candidate_id": ids[1], "attempts": []}
    path = root / "state/pending/round-intent.json"
    save(path, {**pending, "pending_id": canonical_digest(pending)})
    assert tree_view(tmp_path, root.name, loops=True)["total_items"] == 3
    save(path, {**pending, "last_error": "tampered", "pending_id": canonical_digest(pending)})
    with pytest.raises(OperatorViewError, match="invalid content identity"):
        tree_view(tmp_path, root.name)
    path.unlink()
    save(root / f"state/diagnostics/{'a' * 64}.json", {"diagnostic_schema": "population-driver-failure-v1", "authority": "diagnostic-only"})
    with pytest.raises(OperatorViewError, match="diagnostic digest"):
        report_view(tmp_path, root.name, "H1")


def test_missing_population_ledger_does_not_invent_candidates(tmp_path: Path):
    root, _ids = fixture_run(tmp_path)
    (root / "state/population/population.jsonl").unlink()
    tree = tree_view(tmp_path, root.name)
    assert tree["items"] == [] and tree["total_items"] == 0
    assert "Population ledger unavailable" in tree["warnings"][0]
    with pytest.raises(OperatorViewError, match="candidate is unavailable"):
        report_view(tmp_path, root.name, "H1")
