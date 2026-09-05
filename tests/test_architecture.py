import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "apps", ROOT / "artifacts", ROOT / "connectors")
ENTRYPOINTS = {
    ROOT / "apps/candidate_runner/candidate_runner.py",
    ROOT / "apps/controller/controller.py",
    ROOT / "apps/coding_agent/candidate_runner.py",
    ROOT / "apps/coding_agent/evaluator.py",
    ROOT / "apps/coding_agent/evidence_adapter.py",
    ROOT / "apps/coding_agent/fixtures/fixture_solution_proposer.py",
    ROOT / "apps/coding_agent/solution_evaluator.py",
    ROOT / "apps/coding_agent/solution_experiment.py",
    ROOT / "apps/coding_agent/validate_solution.py",
    ROOT / "apps/evolution_driver/demo_proposer.py",
    ROOT / "apps/evolution_driver/evolver.py",
    ROOT / "apps/evolution_driver/signal_relay_acceptance.py",
    ROOT / "apps/evolution_driver/signal_relay_evaluator.py",
    ROOT / "apps/forecast_assay/forecast_assay.py",
    ROOT / "apps/harness/conformance.py",
    ROOT / "apps/harness/evidence_adapter.py",
    ROOT / "apps/harness/experiment.py",
    ROOT / "apps/harness/fixtures/arithmetic_evaluator.py",
    ROOT / "apps/harness/fixtures/fixture_model.py",
    ROOT / "apps/harness/fixtures/fixture_proposer.py",
    ROOT / "apps/harness/harness_runner.py",
    ROOT / "apps/harness/validate_candidate.py",
    ROOT / "apps/mutator/mutator.py",
    ROOT / "apps/mutator/skill_artifact.py",
    ROOT / "apps/observer/agent_evaluator.py",
    ROOT / "apps/observer/observer.py",
    ROOT / "apps/population/population.py",
    ROOT / "apps/population_driver/darwinian_code_adapter.py",
    ROOT / "apps/population_driver/population_driver.py",
    ROOT / "apps/selection_gate/selection_gate.py",
    ROOT / "artifacts/git/demo.py",
    ROOT / "artifacts/git/git_artifact.py",
    ROOT / "artifacts/git/git_candidate_adapter.py",
    ROOT / "connectors/live_agent_acceptance.py",
    ROOT / "connectors/fixed/pi/coding_proposer.py",
    ROOT / "connectors/fixed/pi/git_proposer.py",
    ROOT / "connectors/fixed/pi/harness_model.py",
    ROOT / "connectors/fixed/pi/harness_proposer.py",
    ROOT / "connectors/fixed/pi/harness_runner.py",
    ROOT / "connectors/fixed/pi/skill_proposer.py",
    ROOT / "connectors/fixed/pi/text_runner.py",
    ROOT / "connectors/fixed/prime_agent/git_proposer.py",
    ROOT / "connectors/fixed/prime_agent/harness_model.py",
    ROOT / "connectors/fixed/prime_agent/harness_proposer.py",
    ROOT / "connectors/fixed/prime_agent/harness_runner.py",
    ROOT / "connectors/fixed/prime_agent/skill_proposer.py",
    ROOT / "connectors/fixed/prime_agent/text_runner.py",
}


def python_sources():
    for root in SOURCE_ROOTS:
        yield from root.rglob("*.py")


def parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def mutates_python_path(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if (
            node.func.attr in {"append", "insert"}
            and isinstance(owner, ast.Attribute)
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "sys"
            and owner.attr == "path"
        ):
            return True
    return False


def app_owner(path: Path) -> str | None:
    try:
        relative = path.relative_to(ROOT / "apps")
    except ValueError:
        return None
    return relative.parts[0] if len(relative.parts) > 1 else None


def test_only_compatibility_entrypoints_mutate_python_path():
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in python_sources()
        if mutates_python_path(parsed(path)) and path not in ENTRYPOINTS
    ]
    assert offenders == []


def test_cross_application_imports_never_reach_private_symbols():
    offenders = []
    for path in python_sources():
        owner = app_owner(path)
        for node in ast.walk(parsed(path)):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            parts = node.module.split(".")
            imported_owner = parts[1] if len(parts) > 1 and parts[0] == "apps" else None
            if imported_owner is None or imported_owner == owner:
                continue
            private = sorted(
                alias.name for alias in node.names if alias.name.startswith("_")
            )
            if private:
                offenders.append(
                    (path.relative_to(ROOT).as_posix(), node.module, private)
                )
    assert offenders == []


def test_population_driver_depends_only_on_population_owner_contract():
    forbidden = {
        "apps.population.population_index",
        "apps.population.population_policy",
        "apps.population.population_protocol",
        "apps.population.population_state",
    }
    offenders = []
    for path in (ROOT / "apps/population_driver").glob("*.py"):
        for node in ast.walk(parsed(path)):
            if isinstance(node, ast.ImportFrom) and node.module in forbidden:
                offenders.append((path.name, node.module))
    assert offenders == []


def test_sqlite_is_only_a_population_projection_dependency():
    users = []
    for path in python_sources():
        for node in ast.walk(parsed(path)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name == "sqlite3" for name in names):
                users.append(path.relative_to(ROOT).as_posix())
    assert users == ["apps/population/population_index.py"]


def test_shared_support_has_no_domain_owner_dependencies():
    offenders = []
    for path in (ROOT / "apps/_support").glob("*.py"):
        for node in ast.walk(parsed(path)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            if any(
                module.startswith("apps.") and not module.startswith("apps._support")
                for module in modules
            ):
                offenders.append((path.name, modules))
    assert offenders == []


def test_population_driver_replay_has_no_durable_store_instructions():
    forbidden = {
        "append_driver_record",
        "create_driver_ledger",
        "remove_pending",
        "write_pending",
        "write_receipt",
    }
    imported = {
        alias.name
        for node in ast.walk(parsed(ROOT / "apps/population_driver/replay.py"))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert imported.isdisjoint(forbidden)


def test_population_driver_compatibility_cli_is_a_thin_runtime_dispatcher():
    path = ROOT / "apps/population_driver/population_driver.py"
    tree = parsed(path)
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert functions == {"_application", "main"}
    modules = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "apps.population_driver.runtime" in modules


def test_hash_linked_source_ledgers_share_one_journal_mechanism():
    owners = {
        ROOT / "apps/evolution_driver/evolver.py",
        ROOT / "apps/population/population_state.py",
        ROOT / "apps/population_driver/population_driver_state.py",
    }
    for path in owners:
        modules = {
            node.module
            for node in ast.walk(parsed(path))
            if isinstance(node, ast.ImportFrom)
        }
        assert "apps._support.journal" in modules


def test_harness_application_is_provider_neutral():
    offenders = []
    for path in (ROOT / "apps/harness").rglob("*.py"):
        for node in ast.walk(parsed(path)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            if any(module.startswith("connectors") for module in modules):
                offenders.append((path.relative_to(ROOT).as_posix(), modules))
    assert offenders == []


def test_pi_population_mode_is_a_thin_fixed_connector_entrypoint():
    entrypoint = ROOT / ".pi/extensions/population-evolution.ts"
    assert entrypoint.read_text(encoding="utf-8") == (
        "export { default } from "
        '"../../connectors/fixed/pi/population_evolution_extension.ts";\n'
    )

    implementation = (
        ROOT / "connectors/fixed/pi/population_evolution_extension.ts"
    ).read_text(encoding="utf-8")
    support = (
        ROOT / "connectors/fixed/pi/population_evolution_support.ts"
    ).read_text(encoding="utf-8")
    for command in (
        '"agentvolve"',
        '"agentvolve-history"',
        '"goal"',
        '"limit"',
        '"evolve"',
        '"evolve-status"',
        '"evolve-verify"',
        '"evolve-harness"',
        '"evolve-harness-status"',
        '"evolve-harness-resume"',
        '"evolve-harness-retry"',
        '"evolve-code"',
        '"evolve-code-resume"',
        '"evolve-code-retry"',
        '"evolve-code-status"',
        '"evolve-code-verify"',
    ):
        assert command in implementation
    assert "pi.registerCommand(name" in implementation
    assert "registerNoArgumentCommand(" in implementation
    assert 'const MODE_NAME = "Agentvolve";' in implementation
    assert 'from "./population_evolution_support.ts"' in implementation
    assert "export async function codingWorkflowStatus" in support
    assert "export async function workflowHistory" in support
    assert "export async function discoverTaskProfiles" in support
    assert "export function tasksDirectory" in support
    assert "ctx.ui" not in support
    assert "registerCommand" not in support
    assert 'name: "population_evolution"' in implementation
    assert 'name: "darwinian_coding"' in implementation
    assert 'label: "Agentvolve"' in implementation
    assert 'await pi.exec("uv", args' in implementation
    assert 'await pi.exec("systemctl", ["--user", "restart", service]' in implementation
    assert 'ctx.modelRegistry.find(selection.provider, selection.model)' in implementation
    assert 'type AgentvolveModelMode = "local" | "routed"' in implementation
    assert 'Agentvolve · choose model mode' in implementation
    assert 'experiments stay runtime-pinned' in implementation
    assert 'Start Agentvolve workflow' in implementation
    assert 'Run the complete [1/6] through [6/6] pipeline' in implementation
    assert 'Create task from current session' in implementation
    assert 'ctx.sessionManager.buildContextEntries()' in implementation
    assert 'entry.message.role !== "user"' in implementation
    assert 'agentvolve-workflow-configuration' in implementation
    assert 'apps.coding_agent.task_profile_tool' in implementation
    assert "METERING_EVOLUTION_HARNESS_DESCRIPTOR" in implementation
    assert 'ctx.mode === "rpc"' in implementation
    assert "no reviewed task profile" in implementation
    assert 'for (let stage = 1; stage <= 6; stage += 1)' in implementation
    assert '`${marker} [${stage}/6] ${label}`' in implementation
    assert 'Browse workflow history' in implementation
    assert 'WORKFLOW_MONITOR_INTERVAL_MS = 2000' in support
    assert 'await startWorkflowMonitor(ctx)' in implementation
    assert 'ctx.ui.setWidget(WIDGET_KEY, undefined)' in implementation
    assert 'pi.on("session_shutdown"' in implementation
    assert 'new SelectList(items' in implementation
    assert "final-tasks.json" not in implementation + support
    assert "development-tasks.json" not in implementation + support
    assert "execSync" not in implementation + support


def test_coding_agent_application_is_provider_neutral():
    offenders = []
    for path in (ROOT / "apps/coding_agent").rglob("*.py"):
        for node in ast.walk(parsed(path)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            if any(module.startswith("connectors") for module in modules):
                offenders.append((path.relative_to(ROOT).as_posix(), modules))
    assert offenders == []


def test_candidate_python_execution_is_confined_to_kernel_server():
    offenders = []
    for path in (ROOT / "apps/harness").rglob("*.py"):
        if path.name == "kernel_server.py":
            continue
        for node in ast.walk(parsed(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"eval", "exec"}
            ):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_reference_genome_excludes_fixed_evolution_authorities():
    reference = ROOT / "apps/harness/reference"
    files = {
        path.relative_to(reference).as_posix()
        for path in reference.rglob("*")
        if path.is_file()
    }
    assert files == {
        "compaction-policy.json",
        "context-policy.json",
        "dependencies.lock",
        "entrypoint.json",
        "harness.json",
        "ipython-bootstrap.py",
        "snapshot-policy.json",
        "subagent-policy.json",
        "system-prompt.txt",
        "tool-policy.json",
    }


def experiment_modules():
    for owner in ("coding_agent", "harness"):
        yield from (ROOT / "apps" / owner).glob("experiment_*.py")


def test_experiment_entrypoints_only_own_dispatch_and_status():
    entrypoints = {
        "apps/harness/experiment.py": {"main", "harness_process_status"},
        "apps/coding_agent/solution_experiment.py": {"main", "solution_process_status"},
    }
    for relative, expected_functions in entrypoints.items():
        tree = parsed(ROOT / relative)
        assert {
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        } == expected_functions
        assert not any(isinstance(node, ast.ClassDef) for node in tree.body)
        modules = {
            node.module for node in tree.body if isinstance(node, ast.ImportFrom)
        }
        owner = relative.split("/")[1]
        assert f"apps.{owner}.experiment_runtime" in modules
        assert f"apps.{owner}.experiment_replay" in modules


def test_experiment_implementation_does_not_import_compatibility_entrypoints():
    forbidden = {"apps.harness.experiment", "apps.coding_agent.solution_experiment"}
    for path in experiment_modules():
        imported = {
            node.module
            for node in ast.walk(parsed(path))
            if isinstance(node, ast.ImportFrom)
        }
        assert imported.isdisjoint(forbidden), path


def test_experiment_replay_cannot_import_or_call_live_effects():
    forbidden = {
        "atomic_write",
        "copy_canonical",
        "copy_protected_final_tasks",
        "initialize_solution_repository",
        "localize_harness",
        "run_conformance",
        "run_final_assay",
        "run_population_driver",
        "retry_population_driver",
        "advance_process_status",
        "KernelSession",
        "HarnessRuntime",
    }
    writes = {"write_bytes", "write_text", "mkdir", "unlink", "rmtree"}
    for path in experiment_modules():
        if path.name not in {"experiment_replay.py", "experiment_receipts.py"}:
            continue
        tree = parsed(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert all(alias.name not in forbidden for alias in node.names), path
                assert not (node.module or "").endswith("experiment_runtime"), path
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in forbidden, path
                elif isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in forbidden | writes, path


def test_installed_core_never_imports_source_control_plane():
    forbidden = ("apps", "artifacts", "connectors")
    offenders = []
    for path in (ROOT / "src/metering").glob("*.py"):
        for node in ast.walk(parsed(path)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            if any(module.startswith(forbidden) for module in modules):
                offenders.append((path.name, modules))
    assert offenders == []
