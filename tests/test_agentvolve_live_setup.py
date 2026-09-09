"""The live test must not depend on other tests adding the source checkout."""

import os
import shutil
import subprocess

import pytest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_standalone_live_module_imports_inspection_before_any_execution(tmp_path):
    script = """
import runpy
import sys

# -I and an unrelated cwd reproduce standalone pytest's missing source path.
assert sys.argv[1] not in sys.path

def no_effects(event, args):
    if event in {"subprocess.Popen", "socket.connect", "os.system"}:
        raise AssertionError("Importing the live test attempted an execution effect: " + event)

sys.addaudithook(no_effects)
namespace = runpy.run_path(sys.argv[1] + "/tests/test_agentvolve_live_workflow.py")
__import__("apps.coding_agent.candidate_view")
# Load every inspection dependency up front, not after expensive inference.
for name in ("report_view", "tree_view", "path_key", "TraceSnapshot"):
    assert callable(namespace[name]), name
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(ROOT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which('pi') is None, reason='Pi is not installed')
def test_live_shell_probe_uses_real_rpc_without_a_model_turn(tmp_path):
    from test_agentvolve_jobs import PROVIDER
    from test_agentvolve_live_workflow import EXTENSION, check_ordinary_shell, close_rpc, rpc_request

    config = tmp_path / 'operator-config'
    config.mkdir(mode=0o700)
    log = tmp_path / 'unexpected-model-call.jsonl'
    process = subprocess.Popen(
        ['pi', '--offline', '--mode', 'rpc', '--no-session', '--no-extensions',
         '--no-skills', '--no-context-files', '--no-prompt-templates',
         '-e', str(EXTENSION), '-e', str(PROVIDER), '--provider', 'job-fixture', '--model', 'fixture'],
        cwd=tmp_path, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, 'PI_CODING_AGENT_DIR': str(config), 'JOB_PROMPT_LOG': str(log),
             'METERING_EVOLUTION_RUNS_DIR': str(tmp_path / 'runs')})
    try:
        check_ordinary_shell(process, 'ordinary')
        response, _ = rpc_request(process, {'type': 'get_entries', 'id': 'entries'}, timeout=30)
        assert response['success'] and any(entry.get('message', {}).get('role') == 'bashExecution'
                                           for entry in response['data']['entries'])
        stats, _ = rpc_request(process, {'type': 'get_session_stats', 'id': 'stats'}, timeout=30)
        assert stats['data']['assistantMessages'] == 0
        assert not log.exists(), 'The live shell probe must not invoke even the fixture model'
    finally:
        close_rpc(process)
