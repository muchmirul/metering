#!/usr/bin/env python3
"""Concrete git-candidate executor for evolutionary-harness-v1 checkouts."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps._support.wire import canonical_json, decode_json_object  # noqa: E402
from apps.agent_protocol import (  # noqa: E402
    ProtocolError,
    decode_command,
    decode_task,
    require_exact_keys,
    require_sha256,
)
from apps.harness.model_contract import (  # noqa: E402
    ModelContractError,
    SubprocessModelTransport,
)
from apps.harness.protocol import (  # noqa: E402
    HarnessProtocolError,
    load_candidate,
)
from apps.harness.receipts import (  # noqa: E402
    HarnessReceiptError,
    receipt_document,
    write_receipt,
)
from apps.harness.runtime import HarnessRuntime, HarnessRuntimeError  # noqa: E402
from apps.harness.runtime_manifest import (  # noqa: E402
    RuntimeManifestError,
    assert_candidate_compatible,
    load_runtime_manifest,
)

EVIDENCE_KEY = "_metering_harness"
WORKSPACE_KEY = "_metering_coding_workspace"


class HarnessRunnerError(RuntimeError):
    """Raised when the fixed executor configuration or request is invalid."""


def _environment_command(default: list[str] | None) -> list[str]:
    source = os.environ.get("METERING_HARNESS_MODEL_COMMAND")
    if default is not None:
        if source is not None:
            raise HarnessRunnerError(
                "provider harness runner forbids METERING_HARNESS_MODEL_COMMAND override"
            )
        return default
    if source is None:
        raise HarnessRunnerError(
            "METERING_HARNESS_MODEL_COMMAND must contain a JSON string array"
        )
    try:
        value = json.loads(source)
    except json.JSONDecodeError as exc:
        raise HarnessRunnerError(
            f"METERING_HARNESS_MODEL_COMMAND is invalid JSON: {exc}"
        ) from exc
    try:
        return decode_command(value, "METERING_HARNESS_MODEL_COMMAND")
    except ProtocolError as exc:
        raise HarnessRunnerError(str(exc)) from exc


def _request(source: str) -> tuple[str, dict[str, object], Path, str]:
    request = decode_json_object(source, HarnessRunnerError)
    try:
        require_exact_keys(
            request, {"candidate", "protocol_version", "task"}, "request"
        )
        if (
            type(request["protocol_version"]) is not int
            or request["protocol_version"] != 1
        ):
            raise ProtocolError("request.protocol_version must be 1")
        candidate = request["candidate"]
        if type(candidate) is not dict:
            raise ProtocolError("request.candidate must be a JSON object")
        require_exact_keys(
            candidate,
            {"artifact", "candidate_id", "checkout_path"},
            "request.candidate",
        )
        candidate_id = require_sha256(
            candidate["candidate_id"], "request.candidate.candidate_id"
        )
        artifact = candidate["artifact"]
        if type(artifact) is not dict:
            raise ProtocolError("request.candidate.artifact must be a JSON object")
        entrypoint = artifact.get("entrypoint")
        if type(entrypoint) is not str:
            raise ProtocolError(
                "request.candidate.artifact.entrypoint must be a string"
            )
        checkout = candidate["checkout_path"]
        if type(checkout) is not str or not checkout or "\x00" in checkout:
            raise ProtocolError("request.candidate.checkout_path must be a path string")
        task = decode_task(request["task"], "request.task")
    except ProtocolError as exc:
        raise HarnessRunnerError(str(exc)) from exc
    return candidate_id, task, Path(checkout), entrypoint


def execute(
    source: str,
    *,
    default_model_command: list[str] | None = None,
    expected_connector: str | None = None,
) -> dict[str, object]:
    candidate_id, task, checkout, entrypoint = _request(source)
    runtime_source = os.environ.get("METERING_HARNESS_RUNTIME_MANIFEST")
    receipt_source = os.environ.get("METERING_HARNESS_RECEIPT_DIR")
    if not runtime_source:
        raise HarnessRunnerError(
            "METERING_HARNESS_RUNTIME_MANIFEST must name a profile"
        )
    if not receipt_source:
        raise HarnessRunnerError(
            "METERING_HARNESS_RECEIPT_DIR must name durable storage"
        )
    runtime = load_runtime_manifest(Path(runtime_source))
    if expected_connector is None and runtime.kind != "process-fixture-v1":
        raise HarnessRunnerError(
            "live execution requires a provider-specific reviewed harness runner"
        )
    effective_connector = expected_connector or "fixture-v1"
    if runtime.model["connector"] != effective_connector:
        raise HarnessRunnerError(
            f"runtime model connector must be {effective_connector}"
        )
    if expected_connector is not None:
        pins = {
            "provider": os.environ.get("METERING_HARNESS_PROVIDER"),
            "model": os.environ.get("METERING_HARNESS_MODEL"),
            "reasoning": os.environ.get("METERING_HARNESS_REASONING"),
        }
        for name, supplied in pins.items():
            if supplied != runtime.model[name]:
                raise HarnessRunnerError(
                    f"METERING_HARNESS_{name.upper()} does not match runtime identity"
                )
    candidate = load_candidate(checkout, entrypoint=entrypoint)
    assert_candidate_compatible(
        runtime, (checkout / candidate.paths["dependency_lock"]).read_bytes()
    )
    allow_fixture = os.environ.get("METERING_HARNESS_ALLOW_UNSAFE_FIXTURE") == "1"
    if runtime.kind == "process-fixture-v1" and not allow_fixture:
        raise HarnessRunnerError(
            "process-fixture-v1 requires METERING_HARNESS_ALLOW_UNSAFE_FIXTURE=1"
        )
    task_input = task["input"]
    if type(task_input) is not dict:
        raise HarnessRunnerError("harness task input must be a JSON object")
    model = SubprocessModelTransport(
        _environment_command(default_model_command),
        timeout_seconds=runtime.model_timeout_seconds,
        max_response_bytes=runtime.max_output_bytes,
        environment={
            "METERING_HARNESS_MAX_PROVIDER_OUTPUT_BYTES": str(runtime.max_output_bytes),
            "METERING_HARNESS_MODEL_TIMEOUT": str(runtime.model_timeout_seconds),
        },
    )
    completion = HarnessRuntime(
        candidate, runtime, model, allow_fixture=allow_fixture
    ).run(str(task["case_id"]), task_input)
    if type(completion.submission) is not dict:
        raise HarnessRunnerError("harness finish submission must be a JSON object")
    submission = cast(dict[str, object], completion.submission)
    for reserved in (EVIDENCE_KEY, WORKSPACE_KEY):
        if reserved in submission:
            raise HarnessRunnerError(f"harness submission reserves key {reserved}")
    if completion.workspace is not None:
        submission = {**submission, WORKSPACE_KEY: completion.workspace}
        completion = replace(completion, submission=submission)
    receipt = receipt_document(
        candidate_id=candidate_id,
        case_id=str(task["case_id"]),
        task=task_input,
        candidate=candidate,
        runtime=runtime,
        completion=completion,
    )
    reference = write_receipt(Path(receipt_source), receipt)
    submission = {
        **submission,
        EVIDENCE_KEY: {
            "manifest_id": candidate.manifest_id,
            "receipt": reference,
            "runtime_id": runtime.runtime_id,
        },
    }
    return {"forecast": completion.forecast, "submission": submission}


def run_main(
    *,
    default_model_command: list[str] | None = None,
    expected_connector: str | None = None,
) -> int:
    try:
        response = execute(
            sys.stdin.read(),
            default_model_command=default_model_command,
            expected_connector=expected_connector,
        )
    except (
        HarnessProtocolError,
        HarnessReceiptError,
        HarnessRunnerError,
        HarnessRuntimeError,
        ModelContractError,
        OSError,
        RuntimeManifestError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    print(canonical_json(response))
    return 0


def main() -> int:
    return run_main()


if __name__ == "__main__":
    raise SystemExit(main())
