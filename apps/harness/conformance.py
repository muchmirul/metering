#!/usr/bin/env python3
"""Run the fixed boot/execute/interrupt/snapshot/cleanup kernel assay."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_digest, write_document  # noqa: E402
from apps.harness.kernel_contract import (  # noqa: E402
    KernelContractError,
    KernelSession,
)
from apps.harness.protocol import HarnessProtocolError, load_candidate  # noqa: E402
from apps.harness.runtime_manifest import (  # noqa: E402
    RuntimeManifestError,
    assert_candidate_compatible,
    load_runtime_manifest,
)


class ConformanceError(RuntimeError):
    """Raised when one required kernel behavior is absent."""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ConformanceError(message)


def run_conformance(
    runtime_path: Path,
    checkout: Path,
    *,
    allow_fixture: bool = False,
) -> dict[str, object]:
    runtime = load_runtime_manifest(runtime_path)
    candidate = load_candidate(checkout)
    assert_candidate_compatible(
        runtime, (checkout / candidate.paths["dependency_lock"]).read_bytes()
    )
    policy = {
        "allowed_names": ["counter"],
        "max_bytes": 4096,
        "mode": "after-each-success-v1",
        "restore_after_restart": True,
        "schema_version": 1,
    }
    session = KernelSession(
        runtime,
        candidate.text("ipython_bootstrap"),
        policy,
        allow_fixture=allow_fixture,
    )
    checks: list[str] = []
    try:
        _expect(type(session.ping().get("engine")) is str, "kernel did not boot")
        checks.append("boot")

        result = session.execute("counter = 1\ncounter", timeout_ms=1000)
        _expect(result.status == "ok" and result.result_repr == "1", "execute failed")
        checks.append("execute")

        snapshot = session.snapshot()
        _expect(type(snapshot.get("sha256")) is str, "snapshot failed")
        session.execute("counter = 2", timeout_ms=1000)
        session.restore(snapshot)
        result = session.execute("counter", timeout_ms=1000)
        _expect(result.status == "ok" and result.result_repr == "1", "restore failed")
        checks.extend(["snapshot", "restore"])

        result = session.execute(
            "import time\ntime.sleep(60)",
            timeout_ms=50,
            interrupt=True,
            interrupt_grace_ms=500,
        )
        _expect(result.status == "interrupted", "interrupt failed")
        result = session.execute("counter", timeout_ms=1000)
        _expect(
            result.status == "ok" and result.result_repr == "1",
            "interrupt recovery failed",
        )
        checks.append("interrupt")

        result = session.execute("import time\ntime.sleep(60)", timeout_ms=50)
        _expect(result.status == "timeout", "hard timeout failed")
        result = session.execute("counter", timeout_ms=1000)
        _expect(
            result.status == "ok" and result.result_repr == "1",
            "timeout recovery failed",
        )
        checks.append("timeout")

        session.cleanup()
        result = session.execute("counter", timeout_ms=1000)
        _expect(result.status == "error", "cleanup retained conformance state")
        checks.append("cleanup")
    finally:
        observations = session.close()
    checks.append("shutdown")
    document = {
        "candidate_manifest_id": candidate.manifest_id,
        "checks": checks,
        "isolation_enforced": runtime.isolation_enforced,
        "resources": [item.document() for item in observations],
        "runtime_id": runtime.runtime_id,
        "schema": "evolutionary-harness-conformance-v1",
    }
    return {**document, "conformance_id": canonical_digest(document)}


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    allow_fixture = False
    if arguments and arguments[0] == "--allow-unsafe-fixture":
        allow_fixture = True
        arguments.pop(0)
    if len(arguments) != 2:
        print(
            "usage: conformance.py [--allow-unsafe-fixture] RUNTIME.json CHECKOUT",
            file=sys.stderr,
        )
        return 2
    try:
        report = run_conformance(
            Path(arguments[0]), Path(arguments[1]), allow_fixture=allow_fixture
        )
    except (
        ConformanceError,
        HarnessProtocolError,
        KernelContractError,
        OSError,
        RuntimeManifestError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    write_document(sys.stdout, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
