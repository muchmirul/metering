"""The live test must not depend on other tests adding the source checkout."""

import subprocess
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
