"""Correctness regressions independent of live inference and writer calculations."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.process import JsonProcessError  # noqa: E402
from apps._support.wire import canonical_json  # noqa: E402
import apps.coding_agent.experiment_runtime as solution_runtime  # noqa: E402
from apps.coding_agent.experiment_replay import _verify_selected_solution  # noqa: E402
import apps.coding_agent.final_assay as final_assay  # noqa: E402
from apps.coding_agent.preflight import preflight_task  # noqa: E402
from apps.coding_agent.protocol import CodingTaskError, load_task_profile  # noqa: E402
from apps.coding_agent.experiment_runtime import _selected_solution  # noqa: E402
from apps.harness.experiment import run_experiment as run_harness  # noqa: E402
from apps.population.contract import load_state  # noqa: E402
from apps.population_driver.machine import error_detail  # noqa: E402
from apps.population_driver.paths import population_root  # noqa: E402
from artifacts.git.git_repository import GitCandidateError, run_git  # noqa: E402


def _commit(repository: Path) -> str:
    run_git(["add", "--all"], cwd=repository)
    tree = run_git(["write-tree"], cwd=repository).strip()
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }
    parent = (
        run_git(["rev-parse", "--verify", "HEAD"], cwd=repository).strip()
        if (repository / ".git/refs/heads/main").exists()
        else None
    )
    commit = run_git(
        ["commit-tree", tree, *(["-p", parent] if parent else [])],
        cwd=repository,
        input_text="fixture\n",
        environment=environment,
    ).strip()
    run_git(["update-ref", "refs/heads/main", commit], cwd=repository)
    return commit


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"", b"\xff\n"])
def test_published_patch_reproduces_exact_selected_tree(tmp_path, monkeypatch, newline):
    source = tmp_path / "source"
    source.mkdir()
    run_git(["init", "--quiet", "--initial-branch=main"], cwd=source)
    (source / "solver.py").write_bytes(b"value = 1" + newline)
    (source / "payload.bin").write_bytes(b"\x00\xffold\x00")
    base = _commit(source)
    (source / "solver.py").write_bytes(b"value = 2" + newline)
    (source / "solver.py").chmod(0o755)
    (source / "payload.bin").write_bytes(b"\x00\xffnew\xfe\x00")
    selected = _commit(source)
    selected_tree = run_git(["rev-parse", "HEAD^{tree}"], cwd=source).strip()
    root = tmp_path / "run"
    root.mkdir()
    run_git(["clone", "--bare", "--quiet", str(source), str(root / "candidate.git")])
    artifact = {"commit": selected, "git_tree": selected_tree}
    state = SimpleNamespace(candidates={"a" * 64: {"artifact": artifact}})
    profile = {"repository": {"base_commit": base}, "task_id": "b" * 64}
    descriptor = _selected_solution(root, state, {"candidate_id": "a" * 64}, profile)

    checkout = tmp_path / "apply"
    run_git(["clone", "--quiet", str(source), str(checkout)])
    run_git(["checkout", "--quiet", "--detach", base], cwd=checkout)
    result = subprocess.run(
        ["git", "apply", "--index", str(root / "selected.patch")],
        cwd=checkout,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert run_git(["write-tree"], cwd=checkout).strip() == selected_tree
    assert descriptor["descriptor_schema"] == "selected-solution-commit-v2"
    assert (
        descriptor["patch_sha256"]
        == hashlib.sha256((root / "selected.patch").read_bytes()).hexdigest()
    )
    assert (
        _verify_selected_solution(
            root, state, profile, {"run": {"candidate_id": "a" * 64}}
        )
        == "a" * 64
    )

    # A broken writer cannot establish correctness by hashing its own bad patch.
    monkeypatch.setattr(solution_runtime, "create_patch", lambda *args: b"")
    before = (root / "selected.patch").read_bytes()
    with pytest.raises(GitCandidateError, match="does not reproduce"):
        _selected_solution(root, state, {"candidate_id": "a" * 64}, profile)
    assert (root / "selected.patch").read_bytes() == before

    if newline != b"\xff\n":
        # V1 really did normalize CRLF. Keep its replay meaning, not a false
        # retroactive claim that every historical patch reconstructs its tree.
        legacy_patch = run_git(
            ["diff", "--binary", base, selected], cwd=root / "candidate.git"
        ).encode("utf-8")
        legacy = {
            **descriptor,
            "descriptor_schema": "selected-solution-commit-v1",
            "patch_sha256": hashlib.sha256(legacy_patch).hexdigest(),
        }
        (root / "selected.patch").write_bytes(legacy_patch)
        _write_document(root / "selected-solution.json", legacy)
        marker = tmp_path / "unexpected-external-diff"
        external = tmp_path / "external-diff.py"
        external.write_text(
            f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')\n"
        )
        run_git(
            ["config", "diff.external", f"{sys.executable} {external}"],
            cwd=root / "candidate.git",
        )
        assert (
            _verify_selected_solution(
                root, state, profile, {"run": {"candidate_id": "a" * 64}}
            )
            == "a" * 64
        )
        assert not marker.exists()


def test_failed_controller_summary_keeps_exit_status_without_leaking_stderr():
    error = JsonProcessError(
        "exit", returncode=17, stderr="Bearer secret-value\nprivate traceback"
    )
    summary = error_detail(error)
    assert "17" in summary
    assert "secret-value" not in summary
    assert "private traceback" not in summary


def _write_document(path, document):
    source = (canonical_json(document) + "\n").encode("ascii")
    path.write_bytes(source)
    return hashlib.sha256(source).hexdigest()


def _profile(root, *, output_check=True):
    root.mkdir(parents=True)
    repository = root / "source"
    repository.mkdir()
    run_git(["init", "--quiet", "--initial-branch=main"], cwd=repository)
    (repository / "solver.py").write_text(
        "def solve(left: int, right: int) -> int:\n    return left - right\n"
    )
    base = _commit(repository)
    check = {
        "argv": [
            "python",
            "-c",
            'import json; from solver import solve; print(json.dumps({"answers":[solve(19,23),solve(-3,1)]}))',
        ],
        "case_id": "development",
        "timeout_ms": 10000,
    }
    if output_check:
        check.update(
            {"check_schema": "stdout-json-v1", "expected_stdout": {"answers": [42, -2]}}
        )
    protected = {**check, "case_id": "operator-private-case"}
    protected["argv"] = [
        "python",
        "-c",
        'import json; from solver import solve; print(json.dumps({"answers":[solve(41,-9),solve(8,-8)]}))',
    ]
    if output_check:
        protected["expected_stdout"] = {"answers": [32, 0]}
    final = root / "private-final.json"
    digest = _write_document(
        final,
        {
            "checks": [protected],
            "final_schema": "darwinian-coding-final-v1",
            "schema_version": 1,
        },
    )
    profile = {
        "allocation_draws": [],
        "allowed_paths": ["solver.py"],
        "development_checks": [check],
        "final_assay": {"path": str(final), "sha256": digest},
        "final_draw": {"denominator": 1, "numerator": 0},
        "goal": "Correct solve(left, right) to return their sum without changing its interface.",
        "limits": {
            "max_proposal_calls": 1,
            "max_rounds": 1,
            "max_wall_seconds": 100000,
        },
        "repository": {
            "base_commit": base,
            "entrypoint": "solver.py",
            "path": str(repository),
        },
        "schema_version": 1,
        "task_schema": "darwinian-coding-task-v1",
    }
    path = root / "task.json"
    _write_document(path, profile)
    return path


@pytest.mark.parametrize(
    "defect",
    ["long-argv", "duplicate-private-key", "digest", "schema", "boolean-version"],
)
def test_preflight_rejects_bad_protected_profiles_before_any_execution(
    tmp_path, monkeypatch, defect
):
    path = _profile(tmp_path / "task")
    profile = json.loads(path.read_text())
    final = Path(profile["final_assay"]["path"])
    document = json.loads(final.read_text())
    if defect == "long-argv":
        document["checks"][0]["argv"][2] = "x" * 4097
    elif defect == "schema":
        document["final_schema"] = "unsupported"
    elif defect == "boolean-version":
        document["schema_version"] = True
    if defect == "duplicate-private-key":
        final.write_text('{"private-secret-key":1,"private-secret-key":2}\n')
        profile["final_assay"]["sha256"] = hashlib.sha256(
            final.read_bytes()
        ).hexdigest()
    else:
        profile["final_assay"]["sha256"] = _write_document(final, document)
    if defect == "digest":
        profile["final_assay"]["sha256"] = "0" * 64
    _write_document(path, profile)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "preflight must precede Git publication, conformance, and inference"
        )

    for name in (
        "run_conformance",
        "localize_harness",
        "run_population_driver",
        "initialize_solution_repository",
    ):
        monkeypatch.setattr(solution_runtime, name, forbidden)
    root = tmp_path / "run"
    with pytest.raises(
        CodingTaskError, match="protected profile preflight failed"
    ) as error:
        solution_runtime.run_experiment(
            "fixture",
            path,
            root,
            ROOT / "apps/harness/profiles/runtime-fixture.json",
            tmp_path / "unused-harness.json",
        )
    assert "operator-private-case" not in str(error.value)
    assert "private-secret-key" not in str(error.value)
    assert not root.exists()


@pytest.mark.parametrize("version", [True, 1.0])
def test_task_schema_version_requires_the_declared_json_type(tmp_path, version):
    path = _profile(tmp_path / "task")
    document = json.loads(path.read_text())
    document["schema_version"] = version
    _write_document(path, document)
    with pytest.raises(CodingTaskError, match="not normalized"):
        load_task_profile(path)


def test_preflight_is_read_only_and_discloses_legacy_assurance(tmp_path):
    path = _profile(tmp_path / "task", output_check=False)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = preflight_task(load_task_profile(path))
    assert result["warnings"] and "exit zero" in result["warnings"][0]
    assert "operator-private-case" not in canonical_json(result)
    assert "argv" not in canonical_json(result)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.fixture(scope="module")
def sealed_harness(tmp_path_factory):
    root = tmp_path_factory.mktemp("hardening") / "harness"
    run_harness("fixture", root, None, assay="coding-agent-v1")
    return root / "selected-harness.json"


def test_structured_output_workflow_replays_without_execution_or_writes(
    tmp_path, monkeypatch, sealed_harness
):
    path = _profile(tmp_path / "task")
    root = tmp_path / "run"
    runtime_source = tmp_path / "runtime-source.json"
    runtime_source.write_bytes(
        (ROOT / "apps/harness/profiles/runtime-fixture.json").read_bytes()
    )
    original_task = path.read_bytes()
    original_runtime = runtime_source.read_bytes()
    original_preflight = solution_runtime.preflight_task

    def source_changed_after_validation(profile, **kwargs):
        result = original_preflight(profile, **kwargs)
        path.write_text("changed after validation")
        runtime_source.write_text("changed after validation")
        return result

    monkeypatch.setattr(
        solution_runtime, "preflight_task", source_changed_after_validation
    )
    report = solution_runtime.run_experiment(
        "fixture", path, root, runtime_source, sealed_harness
    )
    assert (root / "task.json").read_bytes() == original_task
    assert (root / "runtime.json").read_bytes() == original_runtime
    assert report["final"]["passed_count"] == report["final"]["task_count"] == 1
    receipts = [
        json.loads(p.read_text()) for p in (root / "evaluation-receipts").glob("*.json")
    ]
    assert receipts and all(
        r["receipt_schema"] == "darwinian-coding-evaluation-receipt-v2"
        for r in receipts
    )
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("offline verification attempted a live/publication effect")

    for name in (
        "_run_protected_final",
        "run_population_driver",
        "_selected_solution",
        "run_conformance",
    ):
        monkeypatch.setattr(solution_runtime, name, forbidden)
    monkeypatch.setattr(final_assay, "run_adapter", forbidden)
    assert solution_runtime.verify_experiment(root)["status"] == "verified"
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_budget_stop_with_a_retained_archive_still_runs_and_replays_final(tmp_path, sealed_harness):
    path = _profile(tmp_path / "task")
    document = json.loads(path.read_text())
    document["limits"].update(max_rounds=2, max_proposal_calls=2, max_wall_seconds=3680)
    document["allocation_draws"] = [{"numerator": 0, "denominator": 1}]
    _write_document(path, document)
    root = tmp_path / "run"
    report = solution_runtime.run_experiment(
        "fixture", path, root, ROOT / "apps/harness/profiles/runtime-fixture.json", sealed_harness
    )
    assert report["development"]["status"] == "wall_reservation_limit"
    assert report["development"]["completed_rounds"] == 1
    assert report["development"]["proposal_calls"] == 1
    assert report["final"]["passed_count"] == report["final"]["task_count"] == 1
    assert solution_runtime.verify_experiment(root)["status"] == "verified"


@pytest.mark.parametrize("phase", ["before-copy", "after-declaration"])
def test_protected_interruption_keeps_selection_and_never_reopens_search(
    tmp_path, monkeypatch, sealed_harness, phase
):
    path = _profile(tmp_path / "task")
    root = tmp_path / "run"
    original_copy = solution_runtime.copy_protected_final_tasks

    def interrupted(*args, **kwargs):
        state = load_state(population_root(root / "state"))
        assert state.records[-1]["kind"] == (
            "allocation" if phase == "before-copy" else "experiment"
        )
        raise OSError("injected protected-boundary interruption")

    if phase == "before-copy":
        monkeypatch.setattr(solution_runtime, "copy_protected_final_tasks", interrupted)
    else:
        monkeypatch.setattr(final_assay, "_case", interrupted)
    with pytest.raises(OSError, match="injected protected-boundary"):
        solution_runtime.run_experiment(
            "fixture",
            path,
            root,
            ROOT / "apps/harness/profiles/runtime-fixture.json",
            sealed_harness,
        )
    state = load_state(population_root(root / "state"))
    allocation = [record for record in state.records if record["kind"] == "allocation"][
        -1
    ]
    mutation_files = {
        p: p.read_bytes() for p in (root / "mutation-receipts").glob("*.json")
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("resume repeated an indeterminate model call")

    monkeypatch.setattr("apps.population_driver.machine.run_json_process", forbidden)
    if phase == "before-copy":
        assert not (root / "protected-final.json").exists()
        monkeypatch.setattr(
            solution_runtime, "copy_protected_final_tasks", original_copy
        )
        report = solution_runtime.continue_experiment(root)
        assert report["final"]["allocation_record_id"] == allocation["record_id"]
        assert report["development"]["completed_rounds"] == 1
    else:
        with pytest.raises(solution_runtime.SolutionExperimentError, match="final"):
            solution_runtime.continue_experiment(root)
        assert not (root / "selected-solution.json").exists()
    assert {
        p: p.read_bytes() for p in (root / "mutation-receipts").glob("*.json")
    } == mutation_files
