"""Deployed Pi UI is quiet until a job is requested; no live inference."""
import json
import shutil
import time

import pytest

from test_agentvolve_jobs import (NAME, approve, bind, boundary as boundary,
                                 deployed, ordinary, projection, submission)

pytestmark = pytest.mark.skipif(shutil.which('pi') is None, reason='Pi is not installed')
KEY = 'population-evolution'


def chrome(events):
    return [event for event in events if event.get('type') == 'extension_ui_request' and (
        event.get('method') == 'setStatus' and event.get('statusKey') == KEY
        or event.get('method') == 'setWidget' and event.get('widgetKey') == KEY)]


def visible(events):
    return [event for event in chrome(events) if event.get('statusText') or event.get('widgetLines')]


def cleared(events):
    statuses = [event for event in chrome(events) if event.get('method') == 'setStatus']
    widgets = [event for event in chrome(events) if event.get('method') == 'setWidget']
    return bool(statuses and widgets and not statuses[-1].get('statusText') and not widgets[-1].get('widgetLines'))


def assert_cleared(events):
    assert cleared(events), events


def wait_for_ui(rpc, events, predicate):
    # Launch acknowledgement and model-selection RPC responses do not wait for
    # an in-flight monitor. Observe real UI events instead of assuming ordering.
    deadline = time.monotonic() + 15
    while not predicate(events):
        events.append(rpc.event(deadline))
    return events


def active_widget(events):
    return any(event.get('widgetLines') for event in visible(events))


def test_startup_reload_and_limit_have_no_idle_chrome_or_welcome(tmp_path):
    with deployed(tmp_path) as rpc:
        for events in (rpc.request({'type': 'get_state', 'id': 'startup'}),
                       rpc.prompt('/job-test-reload')):
            assert_cleared(events)
            assert not visible(events)
            assert not [event for event in events if event.get('method') == 'notify'
                        and 'Agentvolve' in event.get('message', '')]
        assert not visible(rpc.prompt('/limit 5'))
        ordinary(rpc, tmp_path)
        assert not (tmp_path / 'runs').exists()


@pytest.mark.parametrize('state', ['preparing', 'not-launched', 'cancelled', 'failed', 'uncertain-dispatch'])
def test_restoring_unlaunched_request_does_not_reopen_chrome(tmp_path, state):
    with deployed(tmp_path) as rpc:
        rpc.prompt('/job-test-record ' + json.dumps({'schema': 'agentvolve-submission-v1',
                   'attemptId': 'idle-fixture', 'state': state, 'diagnostic': 'retained diagnosis'}))
        events = rpc.prompt('/job-test-reload')
        assert_cleared(events)
        assert not visible(events)
        assert submission(rpc)['state'] == state, 'Restoring UI must not rewrite stored evidence'
        inspected = rpc.prompt('/progress')
        assert any(('not-launched' if state == 'preparing' else state) in event.get('message', '') for event in inspected)
        assert not visible(inspected)
        assert not (tmp_path / 'runs').exists()


def test_cancelled_preparation_pops_status_then_clears_it(tmp_path):
    with deployed(tmp_path) as rpc:
        events = rpc.prompt('/goal Requested job, cancelled at cap input')
        assert any('preparing' in event.get('statusText', '') for event in visible(events))
        assert_cleared(events)
        assert submission(rpc)['state'] == 'not-launched'
        ordinary(rpc, tmp_path)


def test_launched_job_shows_widget_then_clears_on_completion(tmp_path, boundary):
    with deployed(tmp_path, environment=boundary) as rpc:
        events = rpc.prompt('/goal Produce the reviewed output', approve)
        wait_for_ui(rpc, events, active_widget)
        assert submission(rpc)['state'] == 'launched'
        root = tmp_path / 'runs' / NAME
        original = (root / 'evidence.jsonl').read_bytes()
        (tmp_path / 'projection.json').write_text(json.dumps(projection(root, state='completed')))
        events = rpc.request({'type': 'set_model', 'id': 'refresh', 'provider': 'job-fixture', 'modelId': 'other'})
        wait_for_ui(rpc, events, lambda events: cleared(events) and any('Agentvolve finished' in event.get('message', '') for event in events))
        assert_cleared(events)
        events = rpc.prompt('/job-test-reload')
        refreshed = rpc.request({'type': 'set_model', 'id': 'restored', 'provider': 'job-fixture', 'modelId': 'fixture'})
        events += wait_for_ui(rpc, refreshed, cleared)
        assert not visible(events)
        assert not any('Agentvolve finished' in event.get('message', '') for event in events)
        assert submission(rpc)['state'] == 'launched'
        assert (root / 'evidence.jsonl').read_bytes() == original
        ordinary(rpc, tmp_path)


def test_monitor_error_is_not_permanent_chrome_or_repeated_notification(tmp_path, boundary):
    with deployed(tmp_path, environment=boundary) as rpc:
        root = tmp_path / 'runs' / NAME
        bind(rpc, root)
        wait_for_ui(rpc, [], active_widget)
        root.rmdir()  # Only this test-owned empty reference, never live evidence.
        events = rpc.request({'type': 'set_model', 'id': 'missing', 'provider': 'job-fixture', 'modelId': 'other'})
        wait_for_ui(rpc, events, lambda events: cleared(events) and any('referenced job unavailable' in event.get('message', '') for event in events))
        assert_cleared(events)
        events = rpc.request({'type': 'set_model', 'id': 'still-missing', 'provider': 'job-fixture', 'modelId': 'fixture'})
        wait_for_ui(rpc, events, cleared)
        # Drain the completed refresh before asserting that no warning followed.
        events += rpc.request({'type': 'get_state', 'id': 'drain'})
        assert not visible(events)
        assert not any('referenced job unavailable' in event.get('message', '') for event in events)
        assert submission(rpc)['state'] == 'launched'


@pytest.mark.parametrize('state', ['waiting-retry', 'failed', 'closed-incomplete', 'verified'])
def test_inactive_bound_job_clears_chrome_but_preserves_reference(tmp_path, boundary, state):
    with deployed(tmp_path, environment=boundary) as rpc:
        root = tmp_path / 'runs' / NAME
        bind(rpc, root)
        wait_for_ui(rpc, [], active_widget)
        job = submission(rpc)
        view = projection(root, state=state)
        if state == 'failed':
            view['error'] = 'fixture failure remains inspectable'
        (tmp_path / 'projection.json').write_text(json.dumps(view))
        events = rpc.request({'type': 'set_model', 'id': 'inactive', 'provider': 'job-fixture', 'modelId': 'other'})
        wait_for_ui(rpc, events, cleared)
        events += rpc.request({'type': 'get_state', 'id': 'drain'})
        assert not visible(events)
        if state == 'failed':
            assert any('fixture failure' in event.get('message', '') for event in events)
        assert submission(rpc) == job
        assert root.exists()


def test_switching_session_clears_active_widget_without_stopping_job(tmp_path, boundary):
    with deployed(tmp_path, environment=boundary) as rpc:
        root = tmp_path / 'runs' / NAME
        bind(rpc, root)
        wait_for_ui(rpc, [], active_widget)
        events = rpc.request({'type': 'new_session', 'id': 'new'})
        assert_cleared(events)
        assert not visible(events)
        assert root.exists()
        assert not any(entry.get('customType') == 'agentvolve-submission' for entry in rpc.entries())
