"""Deployed session discovery, correction and no-path-entry delegation."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from test_agentvolve_jobs import deployed, ordinary, result, submission, talk
from test_agentvolve_jobs import boundary as boundary
from test_agentvolve_session_configuration import configure_dialog, records, selections, without_defaults

pytestmark = pytest.mark.skipif(shutil.which('pi') is None, reason='Pi is not installed')


def catalogue(tmp_path, boundary, *, issues=None, count=1):
    paths = selections(boundary)
    options = [{**paths, 'runtime_id': 'b' * 64, 'harness_candidate_id': 'c' * 64,
                'worker_models_sha256': hashlib.sha256((Path(paths['configuration']) / 'models.json').read_bytes()).hexdigest(),
                'provider': 'worker-provider', 'model': 'pinned-worker', 'model_label': f'Reviewed local Qwen {index}',
                'implementation_version': '0.84.4', 'recorded_final_passed': 3, 'recorded_final_total': 3}
               for index in range(count)]
    value = {'setup_schema': 'agentvolve-setup-discovery-v1', 'authority': 'diagnostic-only',
             'options': options, 'issues': issues or [], 'truncated': False}
    (tmp_path / 'setup-catalogue.json').write_text(json.dumps(value))
    return value


def choose(event):
    assert event['method'] != 'input', 'Normal setup must not ask the operator to type paths'
    if event['method'] == 'select':
        assert event['title'] == 'Choose Agentvolve worker setup (no job starts)'
        assert 'verify on selection' in event['options'][0]
        return {'value': event['options'][0]}
    assert event['method'] == 'confirm'
    assert event['title'] == 'Save Agentvolve worker configuration for this session?'
    assert 'does not start a worker' in event['message']
    return {'confirmed': True}


def test_discovered_setup_and_messy_five_generation_request_use_same_session_without_exports(tmp_path, boundary):
    catalogue(tmp_path, boundary)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        before = rpc.request({'id': 'before', 'type': 'get_state'})[-1]['data']
        assert result(talk(rpc, 'Configure worker', dialog=choose))['details']['status'] == 'configured'
        assert len(records(rpc)) == 1 and not (tmp_path / 'dispatched').exists()
        ordinary(rpc, tmp_path)
        def approve_five(event):
            if event['method'] == 'input':
                assert event['title'].startswith('Enter the exact generation cap')
                return {'value': '5'}
            assert event['method'] == 'confirm'
            assert '5 generations, 5 proposal calls' in event['message']
            assert 'clmp number pls' in event['message']
            return {'confirmed': True}
        rpc.prompt('/goal clmp number pls, local qwen, 5 generations', approve_five)
        assert submission(rpc)['state'] == 'launched'
        dispatch = json.loads((tmp_path / 'dispatch-record.json').read_text())
        profile = json.loads(Path(dispatch['args'][6]).read_text())
        assert profile['limits']['max_rounds'] == profile['limits']['max_proposal_calls'] == 5
        after = rpc.request({'id': 'after', 'type': 'get_state'})[-1]['data']
        assert before['sessionId'] == after['sessionId']
        for line in (tmp_path / 'prompts.jsonl').read_text().splitlines():
            env = json.loads(line)['environment']
            assert env['METERING_PI_CONFIG_DIR'] is None
        ordinary(rpc, tmp_path)


def test_multiple_setups_require_explicit_selection_and_cancellation_preserves_state(tmp_path, boundary):
    catalogue(tmp_path, boundary, count=2)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        asked = []
        def cancel(event):
            asked.append(event)
            assert event['method'] == 'select' and len(event['options']) == 3
            return {'cancelled': True}
        talk(rpc, 'Configure worker', dialog=cancel)
        assert len(asked) == 1 and records(rpc) == []
        assert not (tmp_path / 'dispatched').exists()
        assert not any('review-configured' in line for line in (tmp_path / 'execs').read_text().splitlines())


def test_missing_setup_returns_repair_diagnosis_not_blank_path_failure(tmp_path, boundary):
    catalogue(tmp_path, boundary, count=0, issues=[{'code': 'worker_configuration_unavailable',
              'message': 'Prepare separate worker models.json with operator approval.'}])
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        def diagnose(event):
            assert event['method'] == 'select'
            assert event['title'] == 'Agentvolve setup needs preparation'
            return {'value': 'Return diagnosis to the assistant'}
        events = talk(rpc, 'Configure worker', dialog=diagnose, error=True)
        assert 'Prepare separate worker models.json' in json.dumps(events)
        assert records(rpc) == [] and not (tmp_path / 'dispatched').exists()
        ordinary(rpc, tmp_path)


def test_advanced_blank_unknown_path_allows_correction_without_losing_review(tmp_path, boundary):
    paths = selections(boundary)
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        asked = 0
        def correct(event):
            nonlocal asked
            if event['title'].startswith('Agentvolve compatible sealed'):
                asked += 1
                if asked == 1:
                    return {'value': ''}
            return configure_dialog(paths)(event)
        events = talk(rpc, 'Configure worker', dialog=correct)
        assert asked == 2
        assert any('cancel and ask the assistant' in e.get('message', '') for e in events)
        assert len(records(rpc)) == 1 and not (tmp_path / 'dispatched').exists()


def test_changed_discovered_identity_refuses_configuration_before_confirmation(tmp_path, boundary):
    value = catalogue(tmp_path, boundary)
    value['options'][0]['runtime_id'] = 'd' * 64
    (tmp_path / 'setup-catalogue.json').write_text(json.dumps(value))
    with deployed(tmp_path, environment=without_defaults(boundary)) as rpc:
        def select_only(event):
            assert event['method'] == 'select'
            return {'value': event['options'][0]}
        events = talk(rpc, 'Configure worker', dialog=select_only, error=True)
        assert 'changed during discovery' in json.dumps(events)
        assert records(rpc) == [] and not (tmp_path / 'dispatched').exists()
