"""Trusted operator preparation, separate from runtime protected-task reveal.

Only bounded structural metadata leaves this module. No protected command, case
identifier, expected answer, case count, or assay result is returned or persisted.
No candidate, model, or check is executed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from apps.coding_agent.experiment_config import development_reservation
from apps.coding_agent.harness_workspace_editor import load_harness_descriptor
from apps.coding_agent.protocol import CodingTaskError, load_final_profile
from apps.harness.runtime_manifest import RuntimeManifest
from artifacts.git.git_repository import run_git


def preflight_task(
    profile: dict[str, object],
    *,
    runtime: RuntimeManifest | None = None,
    harness_source: Path | None = None,
) -> dict[str, object]:
    limits = cast(dict[str, int], profile["limits"])
    budget = development_reservation(
        [cast(int, check["timeout_ms"]) for check in cast(list[dict[str, object]], profile["development_checks"])],
        limits["max_rounds"], limits["max_wall_seconds"],
    )
    if budget["funded_rounds_without_retries"] == 0:
        raise CodingTaskError(
            f"wall_reservation_limit: max_wall_seconds={limits['max_wall_seconds']} cannot fund the first "
            f"development round; at least {budget['round_reservation_seconds']} seconds are required "
            f"({budget['requested_rounds_seconds']} for the {limits['max_rounds']}-round cap without retries). "
            "Review a sufficient budget in a new task; existing run limits will not be changed."
        )
    repository = cast(dict[str, str], profile["repository"])
    source = Path(repository["path"])
    if source.is_symlink() or not source.is_dir():
        raise CodingTaskError("coding task repository is absent or unsafe")
    base = repository["base_commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise CodingTaskError(
            "coding task base_commit must be one full immutable commit ID"
        )
    actual = run_git(
        ["rev-parse", "--verify", f"{base}^{{commit}}"], cwd=source
    ).strip()
    if actual != base:
        raise CodingTaskError("coding task base commit does not match")
    kind = run_git(
        ["cat-file", "-t", f"{base}:{repository['entrypoint']}"], cwd=source
    ).strip()
    if kind != "blob":
        raise CodingTaskError("coding task entrypoint must identify a committed file")
    # Check resolved ancestry too: a symlinked parent must not hide a protected
    # profile inside the candidate's source tree.
    final_reference = cast(dict[str, str], profile["final_assay"])
    if Path(final_reference["path"]).resolve().is_relative_to(source.resolve()):
        raise CodingTaskError(
            "protected final profile must remain outside the repository"
        )
    try:
        _, protected_checks = load_final_profile(profile)
    except (CodingTaskError, OSError, ValueError):
        # Parser errors can contain protected case IDs or duplicate JSON keys.
        # Do not pass their text or chained exceptions to the optimizer.
        raise CodingTaskError(
            "protected profile preflight failed: check its digest, canonical schema, "
            "and command/output bounds in the operator-owned profile"
        ) from None
    checks = [
        *cast(list[dict[str, object]], profile["development_checks"]),
        *protected_checks,
    ]
    warnings = (
        [
            "legacy-exit-status-only-checks: exit zero does not prove intended assertions ran"
        ]
        if any("check_schema" not in check for check in checks)
        else []
    )
    if cast(int, budget["funded_rounds_without_retries"]) < limits["max_rounds"]:
        warnings.append(
            f"wall reservation funds only {budget['funded_rounds_without_retries']} of {limits['max_rounds']} "
            "development rounds without retries; the generation cap is not a promise to run every round"
        )
    document: dict[str, object] = {
        "development_reservation": budget,
        "preflight_schema": "agentvolve-operator-preflight-v1",
        "authority": "diagnostic-only",
        "task_id": profile["task_id"],
        "protected_profile": "validated-digest-bound",
        "warnings": warnings,
    }
    if runtime is not None:
        document["runtime_id"] = runtime.runtime_id
    if harness_source is not None:
        if runtime is None:
            raise CodingTaskError("harness preflight requires a runtime profile")
        descriptor = load_harness_descriptor(harness_source)
        if descriptor["runtime_id"] != runtime.runtime_id:
            raise CodingTaskError(
                "selected harness and runtime identities do not match"
            )
        document["harness_candidate_id"] = descriptor["candidate_id"]
    return document
