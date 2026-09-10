"""Fail-closed preflight for explicitly approved real-model acceptance.

This module never dispatches, retries, closes a workflow, copies credentials or
starts services. Calling it is not execution approval.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from apps.coding_agent.agentvolve_worker import registry_status
from apps.coding_agent.preflight import preflight_task
from apps.coding_agent.protocol import load_task_profile
from apps.harness.runtime_manifest import load_runtime_manifest
from artifacts.git.git_repository import run_git
from connectors.fixed.pi.readiness import local_model
from connectors.fixed.pi.runtime import review_configured


def require_live_approval(environment=None) -> None:
    environment = os.environ if environment is None else environment
    if environment.get('METERING_RUN_AGENTVOLVE_E2E') != '1':
        raise AssertionError('[live-approval-missing] Live acceptance requires fresh operator approval for at least three exact task profiles and their finite budgets. A required live gate cannot pass by skipping. Do not arm inference automatically.')
    if environment.get('METERING_EVOLUTION_LIVE_MAX_RETRIES', '0') != '0' or environment.get('METERING_EVOLUTION_LIVE_RETRY_REASON'):
        raise AssertionError('[automatic-retry-disabled] Live acceptance never retries automatically. Inspect the exact interrupted job and obtain directly reviewed recovery outside this gate.')


def preflight(profiles: list[Path], runtime: Path, harness: Path, configuration: Path,
              runs: Path, *, expected_provider: str = 'llamacpp') -> dict:
    if len(profiles) < 3 or len(set(profiles)) != len(profiles):
        raise AssertionError('[approved-profiles-missing] Select at least three distinct operator-approved task profiles with fresh finite budgets.')
    registry = registry_status(runs)
    if registry['blocker']:
        raise AssertionError('[registry-blocked] Existing workflow requires directly reviewed management. Preserve this registry/evidence; do not retry in a new directory.')
    manifest = load_runtime_manifest(runtime)
    if (manifest.model['connector'] not in {'pi-v1', 'pi-v2'}
            or manifest.model['provider'] != expected_provider):
        raise AssertionError('[runtime-mismatch] The approved runtime must pin the requested Pi transport/provider; do not substitute a model.')
    review = review_configured(runtime, harness, configuration, runs)
    task_ids = []
    for path in profiles:
        task = load_task_profile(path)
        prepared = preflight_task(task, runtime=manifest, harness_source=harness)
        reservation = prepared['development_reservation']
        if reservation['funded_rounds_without_retries'] != task['limits']['max_rounds']:
            raise AssertionError('[task-budget-underfunded] Explicitly review a development reservation that can fund the requested live cap; do not enlarge existing budgets.')
        repository = Path(task['repository']['path'])
        if run_git(['-c', 'core.fsmonitor=false', 'status', '--porcelain'], cwd=repository).strip():
            raise AssertionError('[task-repository-dirty] An approved source repository has uncommitted changes. Do not stash or commit it automatically.')
        if run_git(['rev-parse', 'HEAD^{commit}'], cwd=repository).strip() != task['repository']['base_commit']:
            raise AssertionError('[task-base-moved] Re-review the task base; do not silently rebind the contract.')
        task_ids.append(task['task_id'])
    if len(set(task_ids)) != len(task_ids):
        raise AssertionError('[duplicate-contracts] Three copies of one contract are not three acceptance tasks.')
    try:
        cgroup = subprocess.run(['docker', 'info', '--format', '{{.CgroupVersion}}'],
                                capture_output=True, text=True, timeout=15)
        if cgroup.returncode or cgroup.stdout.strip() != '2':
            raise AssertionError('[docker-unavailable] A reachable reviewed cgroup-v2 Docker daemon is required; no service will be started.')
        image = subprocess.run(['docker', 'image', 'inspect', manifest.image, '--format', '{{.Id}}'],
                               capture_output=True, text=True, timeout=15)
        if image.returncode:
            raise AssertionError('[runtime-image-missing] The exact approved OCI image must already exist locally; no pull/build is authorized by this gate.')
    except (OSError, subprocess.TimeoutExpired):
        raise AssertionError('[docker-unavailable] Docker readiness could not be inspected; arrange separately approved setup before live acceptance.') from None
    readiness = local_model(runtime, configuration)
    return {'gate_schema': 'agentvolve-live-preflight-v1', 'authority': 'diagnostic-only',
            'task_ids': task_ids, 'review': review, 'readiness': readiness,
            'runs_directory': str(runs), 'inference_performed': False}
