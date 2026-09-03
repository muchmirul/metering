from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "apps" / "population_driver" / "population_driver.py"
POPULATION = ROOT / "apps" / "population" / "population.py"
EXAMPLE = ROOT / "apps" / "population_driver" / "example-request.json"
V1_STATE_MANIFEST = (
    ROOT / "tests" / "fixtures" / "population-driver-v1-state.sha256.json"
)
RESOURCE_NAMES = (
    "actions",
    "energy_millijoules",
    "gpu_milliseconds",
    "memory_bytes",
    "storage_bytes",
    "tokens",
    "wall_milliseconds",
)


def encode(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def run_script(
    script: Path,
    request: dict[str, object] | None,
    *arguments: str,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=ROOT,
        input="" if request is None else encode(request),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=timeout,
    )


def records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def make_adapter(tmp_path: Path) -> Path:
    script = tmp_path / "bounded_adapters.py"
    script.write_text(
        """import json,os,sys
from pathlib import Path
NAMES=('actions','energy_millijoules','gpu_milliseconds','memory_bytes','storage_bytes','tokens','wall_milliseconds')
def count(name):
 p=Path(os.environ[name]); n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n)); return n
def proposal(r):
 n=count('PROPOSAL_COUNT')
 if os.environ.get('FAIL_FIRST_PROPOSAL')=='1' and n==1: raise RuntimeError('planned proposal failure')
 g=r['context']['generation']; child=dict(r['parent']['artifact']); child['commit']=format(g,'040x'); child['git_tree']=format(g+100,'040x'); child['content_sha256']=format(g+200,'064x'); return {'challenger_artifact':child,'reason':f'mutation {g}'}
def runner(r):
 good=int(r['candidate']['artifact']['commit'],16)>0; p=.9 if good else .1; return {'forecast':{'outcomes':[{'outcome':'fail','probability':1-p},{'outcome':'pass','probability':p}]},'submission':{'good':good}}
def evaluator(r):
 out=[]
 for item in r['submissions']:
  good=item['submission']['good']; out.append({'candidate_id':item['candidate_id'],'evidence':{'good':good},'outcome':'pass' if good else 'fail','passed':good,'safety_passed':True})
 return {'results':out}
def evidence(r):
 n=count('EVIDENCE_COUNT')
 if os.environ.get('FAIL_EVIDENCE_ALWAYS')=='1' or (os.environ.get('FAIL_FIRST_EVIDENCE')=='1' and n==1): raise RuntimeError('planned evidence failure')
 out=[]
 for role in ('incumbent_report','challenger_report'):
  report=r['controller_result'][role]; passed=report['task_summary']['passed_count']; unsafe=os.environ.get('UNSAFE_CHILD')=='1' and role=='challenger_report'; out.append({'candidate_id':report['candidate'],'behavior_distribution':[float(not passed),float(bool(passed))],'cost':{name:1 for name in NAMES},'protected_passed':not unsafe,'seed':{'round':r['round']}})
 return {'candidates':out,'protocol_version':1}
try:
 request=json.load(sys.stdin); result={'proposal':proposal,'runner':runner,'evaluator':evaluator,'evidence':evidence}[sys.argv[1]](request); print(json.dumps(result,separators=(',',':'),sort_keys=True))
except Exception as exc:
 print(str(exc),file=sys.stderr); raise SystemExit(2)
""",
        encoding="utf-8",
    )
    return script


def driver_request(
    adapter: Path,
    *,
    max_rounds: int = 3,
    max_proposal_calls: int | None = None,
    maximum_cost: int = 100,
    max_wall_seconds: int = 2000,
    stop_on_goal: bool = False,
) -> dict[str, object]:
    def component(action: str) -> dict[str, object]:
        return {
            "command": [sys.executable, str(adapter), action],
            "timeout_seconds": 5,
        }

    request: dict[str, object] = {
        "allocation_draws": [
            {"denominator": 1, "numerator": 0} for _ in range(max_rounds - 1)
        ],
        "evidence_adapter": component("evidence"),
        "generation": {
            "evaluation": "population-driver/test-v1",
            "evaluator": component("evaluator"),
            "runner": component("runner"),
            "selection_policy": {
                "minimum_pass_improvement": 1,
                "reject_safety_regression": True,
                "type": "task-pass-count-v1",
            },
            "tasks": [{"case_id": "bounded-case", "input": {}}],
        },
        "initial_parent_artifact": {
            "artifact_schema": "git-candidate-v1",
            "commit": "0" * 40,
            "content_sha256": "0" * 64,
            "entrypoint": "solver.py",
            "git_tree": "0" * 40,
            "outputs": [],
            "repository": "test://ordinary-code-candidates",
        },
        "limits": {
            "max_proposal_calls": max_proposal_calls or max_rounds + 1,
            "max_rounds": max_rounds,
            "max_total_candidate_cost": {name: maximum_cost for name in RESOURCE_NAMES},
            "max_wall_seconds": max_wall_seconds,
        },
        "population": {
            "configuration": {
                "archive_policy": {
                    "capacity": 32,
                    "reliability_kappa": 0,
                    "type": "pareto-uniform-v1",
                },
                "name": "bounded-test-population",
            },
            "development": {
                "behavior_space": ["fail", "pass"],
                "budget": {name: 10 for name in RESOURCE_NAMES},
                "runtime_id": "1" * 64,
            },
        },
        "proposal": {
            **component("proposal"),
            "context": {"objective": "bounded ordinary-code mutation"},
        },
        "schema_version": 1,
    }
    if stop_on_goal:
        request["stopping"] = {
            "minimum_replicates": 1,
            "type": "all-development-cases-pass-v1",
        }
    return request


def adapter_environment(tmp_path: Path, **extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "EVIDENCE_COUNT": str(tmp_path / "evidence-count"),
        "PROPOSAL_COUNT": str(tmp_path / "proposal-count"),
        **extra,
    }


def test_population_driver_runs_allocated_rounds_and_ignores_sqlite(tmp_path: Path):
    adapter = make_adapter(tmp_path)
    request = driver_request(adapter)
    environment = adapter_environment(tmp_path)
    state = tmp_path / "state"

    result = run_script(DRIVER, request, "run", str(state), env=environment)

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "round_limit"
    assert summary["completed_rounds"] == 3
    assert summary["proposal_calls"] == 3
    assert summary["sqlite_index_used"] is False
    assert (tmp_path / "proposal-count").read_text() == "3"
    assert not (state / "population" / "population.sqlite").exists()

    driver_records = records(state / "driver.jsonl")
    population_records = records(state / "population" / "population.jsonl")
    population_by_id = {record["record_id"]: record for record in population_records}
    assert len(driver_records) == 4
    for previous, current in zip(driver_records[1:-1], driver_records[2:], strict=True):
        allocation_id = previous["next_allocation_record_id"]
        allocation = population_by_id[allocation_id]["body"]
        assert (
            current["parent_candidate_id"]
            == allocation["result"]["selected_candidate_id"]
        )
        assert current["parent_allocation_record_id"] == allocation_id
    first_archive = population_by_id[
        driver_records[1]["population_record_ids"]["archive"]
    ]["body"]
    assert first_archive["excluded"] == [
        {
            "candidate_id": driver_records[1]["parent_candidate_id"],
            "reason": "dominated",
        }
    ]

    before_driver = (state / "driver.jsonl").read_bytes()
    before_population = (state / "population" / "population.jsonl").read_bytes()
    (state / "population" / "population.sqlite").write_bytes(b"not an index")
    resumed = run_script(DRIVER, request, "run", str(state), env=environment)
    verified = run_script(DRIVER, None, "verify", str(state), env=environment)

    assert resumed.returncode == verified.returncode == 0
    assert json.loads(resumed.stdout)["status"] == "round_limit"
    assert json.loads(verified.stdout)["status"] == "verified"
    assert (tmp_path / "proposal-count").read_text() == "3"
    assert (state / "driver.jsonl").read_bytes() == before_driver
    assert (state / "population" / "population.jsonl").read_bytes() == before_population


def test_evaluator_verified_goal_stops_before_the_numeric_round_limit(
    tmp_path: Path,
):
    adapter = make_adapter(tmp_path)
    request = driver_request(adapter, max_rounds=3, stop_on_goal=True)
    environment = adapter_environment(tmp_path)
    state = tmp_path / "state"

    result = run_script(DRIVER, request, "run", str(state), env=environment)

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "development_goal_reached"
    assert summary["completed_rounds"] == 1
    assert summary["candidate_count"] == 2
    assert summary["proposal_calls"] == 1
    round_record = records(state / "driver.jsonl")[1]
    assert round_record["next_allocation_record_id"] is None
    assert round_record["population_record_ids"]["allocation"] is None
    assert len(records(state / "population" / "population.jsonl")) == 7

    before = (state / "driver.jsonl").read_bytes()
    resumed = run_script(DRIVER, request, "run", str(state), env=environment)
    verified = run_script(DRIVER, None, "verify", str(state), env=environment)

    assert resumed.returncode == verified.returncode == 0
    assert json.loads(resumed.stdout)["status"] == "development_goal_reached"
    assert json.loads(verified.stdout)["status"] == "verified"
    assert (tmp_path / "proposal-count").read_text() == "1"
    assert (state / "driver.jsonl").read_bytes() == before


def test_goal_stopping_policy_must_fit_the_numeric_round_limit(tmp_path: Path):
    adapter = make_adapter(tmp_path)
    request = driver_request(adapter, max_rounds=3, stop_on_goal=True)
    request["stopping"]["minimum_replicates"] = 4

    result = run_script(DRIVER, request, "run", str(tmp_path / "state"))

    assert result.returncode == 2
    assert "minimum_replicates cannot exceed limits.max_rounds" in result.stderr


def test_indeterminate_controller_attempt_requires_an_explicit_retry(tmp_path: Path):
    adapter = make_adapter(tmp_path)
    request = driver_request(adapter, max_rounds=1, max_proposal_calls=2)
    environment = adapter_environment(tmp_path, FAIL_FIRST_PROPOSAL="1")
    state = tmp_path / "state"

    failed = run_script(DRIVER, request, "run", str(state), env=environment)
    pending_before = (state / "pending" / "round-intent.json").read_bytes()
    ledger_before = (state / "driver.jsonl").read_bytes()
    repeated = run_script(DRIVER, request, "run", str(state), env=environment)

    assert failed.returncode == repeated.returncode == 0
    failed_summary = json.loads(failed.stdout)
    assert failed_summary["status"] == "pending_round"
    assert "explicit retry" in failed_summary["pending_error"]
    assert (tmp_path / "proposal-count").read_text() == "1"
    assert (state / "pending" / "round-intent.json").read_bytes() == pending_before
    assert (state / "driver.jsonl").read_bytes() == ledger_before

    wrong = run_script(
        DRIVER,
        {"intent_id": "f" * 64, "reason": "wrong intent", "schema_version": 1},
        "retry",
        str(state),
        env=environment,
    )
    assert wrong.returncode == 2
    retry = run_script(
        DRIVER,
        {
            "intent_id": failed_summary["pending_intent_id"],
            "reason": "operator confirmed that another model call is allowed",
            "schema_version": 1,
        },
        "retry",
        str(state),
        env=environment,
    )

    assert retry.returncode == 0, retry.stderr
    assert json.loads(retry.stdout)["status"] == "round_limit"
    assert (tmp_path / "proposal-count").read_text() == "2"
    assert not (state / "pending" / "round-intent.json").exists()
    attempts = records(state / "driver.jsonl")[1]["attempts"]
    assert [attempt["retry"] for attempt in attempts] == [False, True]


def test_evidence_adapter_resume_never_repeats_controller_call(tmp_path: Path):
    adapter = make_adapter(tmp_path)
    request = driver_request(adapter, max_rounds=1)
    environment = adapter_environment(tmp_path, FAIL_FIRST_EVIDENCE="1")
    state = tmp_path / "state"

    failed = run_script(DRIVER, request, "run", str(state), env=environment)

    assert failed.returncode == 0, failed.stderr
    assert json.loads(failed.stdout)["status"] == "pending_round"
    pending = json.loads((state / "pending" / "round-intent.json").read_text())
    assert pending["stage"] == "controller_complete"
    assert (tmp_path / "proposal-count").read_text() == "1"
    assert (tmp_path / "evidence-count").read_text() == "1"

    resumed = run_script(DRIVER, request, "run", str(state), env=environment)

    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout)["status"] == "round_limit"
    assert (tmp_path / "proposal-count").read_text() == "1"
    assert (tmp_path / "evidence-count").read_text() == "2"
    assert len(list((state / "receipts").glob("*.controller.json"))) == 1


def test_evidence_adapter_retries_consume_a_finite_wall_reservation(
    tmp_path: Path,
):
    adapter = make_adapter(tmp_path)
    request = driver_request(adapter, max_rounds=1, max_wall_seconds=110)
    environment = adapter_environment(tmp_path, FAIL_EVIDENCE_ALWAYS="1")
    state = tmp_path / "state"

    first = run_script(DRIVER, request, "run", str(state), env=environment)
    second = run_script(DRIVER, request, "run", str(state), env=environment)
    third = run_script(DRIVER, request, "run", str(state), env=environment)

    assert first.returncode == second.returncode == third.returncode == 0
    assert json.loads(first.stdout)["reserved_wall_seconds"] == 105
    assert json.loads(second.stdout)["reserved_wall_seconds"] == 110
    third_summary = json.loads(third.stdout)
    assert third_summary["status"] == "pending_round"
    assert "wall reservation limit" in third_summary["pending_error"]
    assert third_summary["reserved_wall_seconds"] == 110
    assert (tmp_path / "proposal-count").read_text() == "1"
    assert (tmp_path / "evidence-count").read_text() == "2"


def test_partial_population_ingestion_resumes_without_another_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    adapter = make_adapter(tmp_path)
    request = driver_request(adapter, max_rounds=1)
    environment = adapter_environment(tmp_path)
    for name, value in environment.items():
        if name in {"EVIDENCE_COUNT", "PROPOSAL_COUNT"}:
            monkeypatch.setenv(name, value)
    state = tmp_path / "state"
    spec = importlib.util.spec_from_file_location(
        "population_driver_interruption_test", DRIVER
    )
    assert spec is not None and spec.loader is not None
    driver_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver_module)
    driver_machine = importlib.import_module("apps.population_driver.machine")
    real_append = driver_machine.append_driver_record

    def interrupt_after_population(*_args, **_kwargs):
        raise OSError("simulated interruption before driver append")

    monkeypatch.setattr(
        driver_machine, "append_driver_record", interrupt_after_population
    )
    with pytest.raises(OSError, match="simulated interruption"):
        driver_module.run_population_driver(encode(request), state)

    assert (tmp_path / "proposal-count").read_text() == "1"
    assert (tmp_path / "evidence-count").read_text() == "1"
    assert len(records(state / "driver.jsonl")) == 1
    assert len(records(state / "population" / "population.jsonl")) == 7
    pending = json.loads((state / "pending" / "round-intent.json").read_text())
    assert pending["stage"] == "evidence_complete"

    monkeypatch.setattr(driver_machine, "append_driver_record", real_append)
    resumed = driver_module.run_population_driver(encode(request), state)

    assert resumed["status"] == "round_limit"
    assert resumed["completed_rounds"] == 1
    assert (tmp_path / "proposal-count").read_text() == "1"
    assert (tmp_path / "evidence-count").read_text() == "1"
    assert len(records(state / "driver.jsonl")) == 2
    assert not (state / "pending" / "round-intent.json").exists()


def test_cost_limit_stops_before_a_proposal_and_unsafe_child_is_excluded(
    tmp_path: Path,
):
    adapter = make_adapter(tmp_path)
    environment = adapter_environment(tmp_path)
    limited_state = tmp_path / "limited"
    limited = run_script(
        DRIVER,
        driver_request(adapter, max_rounds=1, maximum_cost=19),
        "run",
        str(limited_state),
        env=environment,
    )

    assert limited.returncode == 0, limited.stderr
    assert json.loads(limited.stdout)["status"] == "candidate_cost_limit"
    assert not (tmp_path / "proposal-count").exists()
    assert len(records(limited_state / "population" / "population.jsonl")) == 3

    unsafe_root = tmp_path / "unsafe-root"
    unsafe_root.mkdir()
    unsafe_adapter = make_adapter(unsafe_root)
    unsafe_environment = adapter_environment(unsafe_root, UNSAFE_CHILD="1")
    unsafe_state = unsafe_root / "state"
    unsafe = run_script(
        DRIVER,
        driver_request(unsafe_adapter, max_rounds=1),
        "run",
        str(unsafe_state),
        env=unsafe_environment,
    )

    assert unsafe.returncode == 0, unsafe.stderr
    assert json.loads(unsafe.stdout)["status"] == "round_limit"
    archive = next(
        record["body"]
        for record in reversed(
            records(unsafe_state / "population" / "population.jsonl")
        )
        if record["kind"] == "archive"
    )
    child_id = records(unsafe_state / "driver.jsonl")[1]["child_candidate_id"]
    assert {"candidate_id": child_id, "reason": "infeasible"} in archive["excluded"]
    assert child_id not in [member["candidate_id"] for member in archive["members"]]


def test_final_evidence_seals_automatic_search(tmp_path: Path):
    adapter = make_adapter(tmp_path)
    request = driver_request(adapter, max_rounds=1)
    environment = adapter_environment(tmp_path)
    state = tmp_path / "state"
    first = run_script(DRIVER, request, "run", str(state), env=environment)
    assert first.returncode == 0, first.stderr
    population_state = state / "population"
    driver_before = (state / "driver.jsonl").read_bytes()
    seed_id = records(state / "driver.jsonl")[0]["seed_candidate_id"]

    final_experiment = run_script(
        POPULATION,
        {
            "experiment": {
                "behavior_space": ["fail", "pass"],
                "budget": {name: 10 for name in RESOURCE_NAMES},
                "case_count": 1,
                "evaluator_id": "2" * 64,
                "information_objective": False,
                "role": "final",
                "runtime_id": "3" * 64,
                "task_set_id": "4" * 64,
            },
            "schema_version": 1,
        },
        "experiment",
        str(population_state),
    )
    assert final_experiment.returncode == 0, final_experiment.stderr
    final_experiment_id = json.loads(final_experiment.stdout)["experiment_id"]

    stopped_before_reveal = run_script(
        DRIVER, request, "run", str(state), env=environment
    )
    assert stopped_before_reveal.returncode == 0, stopped_before_reveal.stderr
    assert json.loads(stopped_before_reveal.stdout)["status"] == "final_evidence_sealed"
    assert (tmp_path / "proposal-count").read_text() == "1"
    assert (state / "driver.jsonl").read_bytes() == driver_before

    final_run = run_script(
        POPULATION,
        {
            "candidate_id": seed_id,
            "evidence": {
                "behavior_distribution": [1.0, 0.0],
                "cost": {name: 1 for name in RESOURCE_NAMES},
                "evidence_receipt": {"sha256": "5" * 64, "uri": "final://receipt"},
                "information_model": None,
                "protected_passed": True,
                "target_probabilities": [0.5],
                "task": {
                    "case_count": 1,
                    "passed_count": 0,
                    "safety_failures": 0,
                },
            },
            "experiment_id": final_experiment_id,
            "replicate_id": "withheld-final",
            "schema_version": 1,
            "seed": "final",
        },
        "run",
        str(population_state),
    )
    assert final_run.returncode == 0, final_run.stderr

    sealed = run_script(DRIVER, request, "run", str(state), env=environment)
    verified = run_script(DRIVER, None, "verify", str(state), env=environment)

    assert sealed.returncode == verified.returncode == 0
    assert json.loads(sealed.stdout)["status"] == "final_evidence_sealed"
    assert json.loads(verified.stdout)["final_evaluation_started"] is True
    assert (tmp_path / "proposal-count").read_text() == "1"
    assert (state / "driver.jsonl").read_bytes() == driver_before


def test_receipt_tampering_is_detected(tmp_path: Path):
    adapter = make_adapter(tmp_path)
    request = driver_request(adapter, max_rounds=1)
    environment = adapter_environment(tmp_path)
    state = tmp_path / "state"
    result = run_script(DRIVER, request, "run", str(state), env=environment)
    assert result.returncode == 0, result.stderr
    receipt = next((state / "receipts").glob("*.controller.json"))
    receipt.write_bytes(
        receipt.read_bytes().replace(b'"receipt_schema"', b'"receipt_schemb"')
    )

    verified = run_script(DRIVER, None, "verify", str(state), env=environment)

    assert verified.returncode == 2
    assert "digest mismatch" in verified.stderr


def test_documented_population_driver_example(tmp_path: Path):
    request = json.loads(EXAMPLE.read_text())
    state = tmp_path / "documented-state"

    result = run_script(DRIVER, request, "run", str(state))

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "round_limit"
    assert summary["completed_rounds"] == 3
    assert summary["candidate_count"] == 4
    assert not (state / "population" / "population.sqlite").exists()
    expected_manifest = json.loads(V1_STATE_MANIFEST.read_text())
    actual_manifest = {
        path.relative_to(state).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(state.rglob("*"))
        if path.is_file()
    }
    assert actual_manifest == expected_manifest
