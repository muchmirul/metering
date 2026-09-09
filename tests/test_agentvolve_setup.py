"""Read-only discovery never chooses a run, funds work, or copies credentials."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from connectors.fixed.pi import setup  # noqa: E402
from test_agentvolve_worker_configuration import SECRET  # noqa: E402
from test_agentvolve_worker_configuration import configured as configured  # noqa: E402


@pytest.fixture
def catalogue(configured, monkeypatch):
    monkeypatch.setattr(setup, "load_harness_descriptor", lambda path: json.loads(path.read_text()))
    return configured


def test_discovery_is_read_only_non_effectful_and_contains_no_secrets(catalogue):
    c = catalogue
    before = {p: p.read_bytes() for p in c.config.rglob('*') if p.is_file()}
    probes = list(c.probes)
    result = setup.discover(c.runs, c.manifest, c.config, c.harness)
    assert result['issues'] == [] and len(result['options']) == 1
    option = result['options'][0]
    assert option['runtime_id'] == c.approved['runtime_id']
    assert option['configuration'] == str(c.config)
    assert option['harness'] == str(c.harness)
    assert SECRET not in json.dumps(result)
    assert c.probes == probes and not c.launches and not c.runs.exists()
    assert all(p.read_bytes() == data for p, data in before.items())


def test_all_compatible_harnesses_are_offered_without_newest_selection(catalogue):
    c = catalogue
    for name in ('harness-new', 'harness-old'):
        directory = c.runs / name
        directory.mkdir(parents=True)
        (directory / 'selected-harness.json').write_text(json.dumps(c.descriptor))
    result = setup.discover(c.runs, c.manifest, c.config)
    assert [Path(item['harness']).parent.name for item in result['options']] == ['harness-new', 'harness-old']
    assert 'selected' not in result


@pytest.mark.parametrize('change', ['runtime', 'failed', 'safety', 'legacy', 'symlink'])
def test_incompatible_or_unsafe_descriptors_never_become_options(catalogue, change):
    c = catalogue
    doc = json.loads(c.harness.read_text())
    if change == 'runtime':
        doc['runtime_id'] = 'f' * 64
    elif change == 'failed':
        doc['provenance']['final_passed_count'] = 2
    elif change == 'safety':
        doc['provenance']['final_safety_failures'] = 1
    elif change == 'legacy':
        doc.pop('provenance')
    if change == 'symlink':
        original = c.harness.with_name('original.json')
        c.harness.rename(original)
        c.harness.symlink_to(original)
    else:
        c.harness.write_text(json.dumps(doc))
    result = setup.discover(c.runs, c.manifest, c.config, c.harness)
    assert result['options'] == []
    assert result['issues'][0]['code'] == 'compatible_harness_unavailable'
    assert not c.runs.exists()


@pytest.mark.parametrize('change', ['absent', 'interactive', 'malformed', 'wrong-shape'])
def test_missing_config_has_actionable_private_diagnosis(catalogue, monkeypatch, change):
    c = catalogue
    if change == 'absent':
        (c.config / 'models.json').unlink()
    elif change == 'interactive':
        monkeypatch.setenv('PI_CODING_AGENT_DIR', str(c.config))
    else:
        (c.config / 'models.json').write_text(SECRET if change == 'malformed' else '{"providers":[]}')
    result = setup.discover(c.runs, c.manifest, c.config, c.harness)
    assert result['options'] == []
    assert result['issues'][0]['code'] == 'worker_configuration_unavailable'
    assert 'approval' in result['issues'][0]['message']
    assert SECRET not in json.dumps(result)


def test_missing_runtime_reports_preparation_not_model_failure(catalogue):
    c = catalogue
    c.manifest.unlink()
    result = setup.discover(c.runs, c.manifest, c.config, c.harness)
    assert result['issues'][0]['code'] == 'runtime_unavailable'
    assert not c.launches


def test_catalogue_overflow_fails_closed_without_choosing_partial_results(catalogue, monkeypatch):
    c = catalogue
    monkeypatch.setattr(setup, 'MAX_HARNESSES', 2)
    for index in range(3):
        (c.runs / f'harness-{index}').mkdir(parents=True)
    result = setup.discover(c.runs, c.manifest, c.config)
    assert result['truncated'] is True and result['options'] == []
    assert result['issues'][0]['code'] == 'catalogue_limit'
