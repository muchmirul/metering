"""Invoke the public Metering JSON module from a source checkout."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    if len(sys.argv) != 1:
        print("command-line arguments are not supported", file=sys.stderr)
        return 2
    environment = dict(os.environ)
    python_path = str(ROOT / "src")
    if environment.get("PYTHONPATH"):
        python_path += os.pathsep + environment["PYTHONPATH"]
    environment["PYTHONPATH"] = python_path
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "metering"],
            cwd=ROOT,
            input=sys.stdin.read(),
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
    except OSError as exc:
        print(f"cannot start Metering: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
