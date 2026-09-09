"""Read-only setup suggestions, never runtime selection or execution authority."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from apps._support.wire import decode_json_object
from apps.coding_agent.harness_workspace_editor import CodingMutationError, load_harness_descriptor
from apps.coding_agent.pi_execution import bounded_file, configuration_source, resolved_path
from apps.harness.runtime_manifest import load_runtime_manifest

SCHEMA = "agentvolve-setup-discovery-v1"
MAX_HARNESSES = 200


def discover(runs: Path, manifest: Path, configuration: Path, harness: Path | None = None) -> dict:
    """List compatible original seals; each selected seal still needs full replay.

    No registry mutation, provider request, credential resolution, Pi call or model
    inference occurs. Candidate suggestions are not ranked by recency or fitness.
    """
    result = {"setup_schema": SCHEMA, "authority": "diagnostic-only",
              "options": [], "issues": [], "truncated": False}

    def issue(code: str, message: str) -> None:
        result["issues"].append({"code": code, "message": message})

    try:
        manifest = resolved_path(str(manifest))
        bounded_file(manifest)
        runtime = load_runtime_manifest(manifest)
        if runtime.model["connector"] != "pi-v1" or not runtime.isolation_enforced:
            raise ValueError("not an isolated Pi runtime")
    except (ValueError, OSError):
        issue("runtime_unavailable", "Select an existing reviewed OCI pi-v1 runtime manifest. Runtime provisioning needs separate approval.")
        return result

    try:
        configuration = configuration_source(configuration)
        models_bytes = bounded_file(configuration / "models.json")
        models = decode_json_object(models_bytes.decode("utf-8"), ValueError)
        bounded_file(configuration / "auth.json", optional=True)
        provider = models.get("providers", {}).get(runtime.model["provider"], {})
        entries = provider.get("models", [])
        selected = [entry for entry in entries if type(entry) is dict and entry.get("id") == runtime.model["model"]]
        if runtime.model["provider"] == "llamacpp" and len(selected) != 1:
            raise ValueError("local worker model not declared")
        label = selected[0].get("name", runtime.model["model"]) if len(selected) == 1 else runtime.model["model"]
        label = str(label)
        if len(label) > 160 or any(ord(char) < 32 or ord(char) == 127 for char in label):
            label = runtime.model["model"]
    except (ValueError, OSError, AttributeError, TypeError, UnicodeError):
        issue("worker_configuration_unavailable", "Prepare a separate worker directory containing valid models.json for the selected provider/model (and auth.json only if needed). Ask the assistant to prepare it with your approval; do not use interactive Pi's directory or paste credentials into chat.")
        return result

    paths: list[Path] = []
    if harness is not None:
        paths.append(harness)
    try:
        runs = resolved_path(str(runs))
        if runs.exists():
            # Bound enumeration before sorting; an oversized catalogue needs narrowing.
            with os.scandir(runs) as entries:
                for index, entry in enumerate(entries):
                    if index >= 1000:
                        result["truncated"] = True
                        issue("catalogue_limit", "Run catalogue exceeds the bounded scan; select an explicit original seal in advanced setup.")
                        return result
                    if entry.name.startswith("harness-") and entry.is_dir(follow_symlinks=False):
                        paths.append(Path(entry.path) / "selected-harness.json")
                        if len(paths) > MAX_HARNESSES:
                            result["truncated"] = True
                            issue("catalogue_limit", "Too many harness directories; select an explicit original selected-harness.json in advanced setup.")
                            return result
    except (ValueError, OSError):
        issue("registry_unavailable", "The selected run directory cannot be inspected safely. Review its path; do not change registries to bypass interrupted work.")
        return result

    for path in sorted(set(paths)):
        try:
            path = resolved_path(str(path))
            bounded_file(path, limit=262144)
            descriptor = load_harness_descriptor(path)
            final = descriptor["provenance"]
            if (path.name != "selected-harness.json" or descriptor["runtime_id"] != runtime.runtime_id
                    or final["final_task_count"] <= 0
                    or final["final_passed_count"] != final["final_task_count"]
                    or final["final_safety_failures"] != 0):
                continue
            result["options"].append({
                "manifest": str(manifest), "harness": str(path), "configuration": str(configuration),
                "runtime_id": runtime.runtime_id, "harness_candidate_id": descriptor["candidate_id"],
                "worker_models_sha256": hashlib.sha256(models_bytes).hexdigest(),
                "provider": runtime.model["provider"], "model": runtime.model["model"], "model_label": label,
                "implementation_version": runtime.model["implementation_version"],
                "recorded_final_passed": final["final_passed_count"], "recorded_final_total": final["final_task_count"],
            })
        except (ValueError, OSError, KeyError, TypeError, CodingMutationError):
            # Do not reveal file contents or manufacture compatibility for old/bad seals.
            continue
    if not result["options"]:
        issue("compatible_harness_unavailable", "No compatible passing original harness was found. Select an explicitly reviewed original seal in advanced setup, or separately approve and budget harness preparation. No automatic Level-2 run is allowed.")
    return result
