"""The required live gate must fail closed, never quietly skip or start work."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from connectors.fixed.pi import live_gate as gate  # noqa: E402
from apps._support.wire import canonical_json  # noqa: E402
from connectors.fixed.pi import readiness  # noqa: E402
from test_agentvolve_worker_configuration import configured as configured  # noqa: E402


def test_required_live_gate_cannot_pass_as_skip_without_explicit_approval(tmp_path):
    environment = {**os.environ, 'METERING_REQUIRE_AGENTVOLVE_E2E': '1', 'METERING_RUN_AGENTVOLVE_E2E': '0'}
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', 'tests/test_agentvolve_live_workflow.py'],
                            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert '[live-approval-missing]' in result.stdout
    assert '1 failed' in result.stdout and '1 skipped' not in result.stdout


@pytest.mark.parametrize('value', [None, '', '0', 'true'])
def test_approval_must_be_explicit(value):
    with pytest.raises(AssertionError, match='live-approval-missing'):
        gate.require_live_approval({} if value is None else {'METERING_RUN_AGENTVOLVE_E2E': value})


@pytest.mark.parametrize('extra', [{'METERING_EVOLUTION_LIVE_MAX_RETRIES': '1'},
                                    {'METERING_EVOLUTION_LIVE_RETRY_REASON': 'standing permission'}])
def test_live_gate_rejects_automatic_retry_authorization(extra):
    with pytest.raises(AssertionError, match='automatic-retry-disabled'):
        gate.require_live_approval({'METERING_RUN_AGENTVOLVE_E2E': '1', **extra})


def test_all_profiles_are_preflighted_before_docker_or_model_checks(configured, monkeypatch):
    c = configured
    profiles = [c.task.with_name(f'task-{index}.json') for index in range(3)]
    monkeypatch.setattr(gate, 'registry_status', lambda _: {'blocker': None})
    monkeypatch.setattr(gate, 'review_configured', lambda *_: c.approved)
    loaded = []
    def load(path):
        loaded.append(path)
        if path == profiles[-1]:
            raise ValueError('last approved profile is invalid')
        return {'task_id': str(path), 'repository': {'path': str(c.task.parent), 'base_commit': 'a' * 40},
                'limits': {'max_rounds': 5}}
    monkeypatch.setattr(gate, 'load_task_profile', load)
    monkeypatch.setattr(gate, 'preflight_task', lambda *_a, **_kw: {'development_reservation': {'funded_rounds_without_retries': 5}})
    monkeypatch.setattr(gate, 'run_git', lambda args, **_kw: 'a' * 40 if args[0] == 'rev-parse' else '')
    monkeypatch.setattr(gate.subprocess, 'run', lambda *_a, **_kw: pytest.fail('premature external readiness check'))
    monkeypatch.setattr(gate, 'local_model', lambda *_: pytest.fail('premature model readiness check'))
    with pytest.raises(ValueError, match='last approved'):
        gate.preflight(profiles, c.manifest, c.harness, c.config, c.runs, expected_provider='worker')
    assert loaded == profiles and not c.runs.exists()


def test_registry_blocker_prevents_any_preflight_or_alternate_run(configured, monkeypatch):
    c = configured
    monkeypatch.setattr(gate, 'registry_status', lambda _: {'blocker': {'workflow_root': 'original'}})
    monkeypatch.setattr(gate, 'review_configured', lambda *_: pytest.fail('must handle original blocker first'))
    with pytest.raises(AssertionError, match='registry-blocked'):
        gate.preflight([Path(str(index)) for index in range(3)], c.manifest, c.harness, c.config, c.runs)
    assert not c.runs.exists()


@pytest.fixture
def local(configured, monkeypatch):
    c = configured
    data = json.loads(c.manifest.read_text())
    data['model'].update(provider='llamacpp', model='local')
    c.manifest.write_text(canonical_json(data) + '\n')
    provider = {'baseUrl': 'http://127.0.0.1:9123/custom/v1', 'apiKey': 'private-fixture-token',
                'models': [{'id': 'local', 'name': 'Qwen fixture'}]}
    (c.config / 'models.json').write_text(json.dumps({'providers': {'llamacpp': provider}}))
    calls = []
    body = {'data': [{'id': 'local', 'status': {'value': 'loaded'}}]}
    response = SimpleNamespace(status=200, read=lambda _n: json.dumps(body).encode())
    class Connection:
        def __init__(self, host, port, **kwargs):
            calls.append((host, port, kwargs))
        def request(self, method, path, headers):
            calls.append((method, path, headers))
        def getresponse(self):
            return response
        def close(self):
            calls.append('closed')
    monkeypatch.setattr(readiness.http.client, 'HTTPConnection', Connection)
    return SimpleNamespace(c=c, calls=calls, provider=provider, body=body, response=response)


def test_readiness_uses_reviewed_endpoint_not_ambient_health_override(local, monkeypatch):
    monkeypatch.setenv('METERING_EVOLUTION_LLAMACPP_HEALTH_URL', 'https://wrong.invalid/models')
    result = readiness.local_model(local.c.manifest, local.c.config)
    assert result['state'] == 'ready' and result['inference_performed'] is False
    assert local.calls[0][:2] == ('127.0.0.1', 9123)
    assert local.calls[1][:2] == ('GET', '/custom/v1/models')
    assert local.calls[-1] == 'closed'
    assert 'private-fixture-token' not in json.dumps(result)


@pytest.mark.parametrize('change', ['remote', 'command', 'env', 'redirect', 'unloaded', 'wrong-model', 'oversized'])
def test_readiness_failure_never_falls_back_restarts_or_exposes_credentials(local, change):
    if change == 'remote':
        local.provider['baseUrl'] = 'https://unreviewed.invalid/v1'
    elif change in {'command', 'env'}:
        local.provider['apiKey'] = '!do-not-execute' if change == 'command' else '$PRIVATE_TOKEN'
    elif change == 'redirect':
        local.response.status = 302
    elif change == 'unloaded':
        local.body['data'][0]['status']['value'] = 'unloaded'
    elif change == 'wrong-model':
        local.body['data'][0]['id'] = 'different'
    else:
        local.response.read = lambda _n: b'x' * 262145
    (local.c.config / 'models.json').write_text(json.dumps({'providers': {'llamacpp': local.provider}}))
    with pytest.raises(readiness.ReadinessError) as failure:
        readiness.local_model(local.c.manifest, local.c.config)
    assert 'private-fixture-token' not in str(failure.value)
    assert 'do-not-execute' not in str(failure.value)
    if change in {'remote', 'command', 'env'}:
        assert local.calls == []
