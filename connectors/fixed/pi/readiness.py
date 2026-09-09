"""Read-only local endpoint readiness from the reviewed worker configuration."""
from __future__ import annotations

import http.client
from pathlib import Path
from urllib.parse import urlsplit

from apps._support.wire import decode_json_object
from apps.coding_agent.pi_execution import bounded_file, configuration_source
from apps.harness.runtime_manifest import load_runtime_manifest


class ReadinessError(ValueError):
    pass


def local_model(manifest: Path, configuration: Path) -> dict:
    runtime = load_runtime_manifest(manifest)
    result = {'readiness_schema': 'agentvolve-worker-readiness-v1', 'authority': 'diagnostic-only',
              'runtime_id': runtime.runtime_id, 'provider': runtime.model['provider'],
              'model': runtime.model['model'], 'inference_performed': False}
    if runtime.model['provider'] != 'llamacpp':
        return {**result, 'state': 'not-applicable'}
    try:
        directory = configuration_source(configuration)
        models = decode_json_object(bounded_file(directory / 'models.json').decode('utf-8'), ValueError)
        provider = models['providers']['llamacpp']
        selected = [m for m in provider['models'] if m.get('id') == runtime.model['model']]
        if len(selected) != 1:
            raise ValueError('ambiguous/missing model')
        endpoint = urlsplit(provider['baseUrl'])
        if (endpoint.scheme not in {'http', 'https'} or endpoint.hostname not in {'localhost', '127.0.0.1', '::1'}
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
            raise ValueError('local readiness requires a literal loopback endpoint')
        headers = {**provider.get('headers', {}), **selected[0].get('headers', {})}
        key = provider.get('apiKey')
        if key is not None:
            if type(key) is not str or key.startswith('!') or '$' in key:
                raise ValueError('dynamic credentials require explicit provisioning')
            headers.setdefault('Authorization', 'Bearer ' + key)
        if any(type(value) is not str or value.startswith('!') or '$' in value
               or '\r' in value or '\n' in value for value in headers.values()):
            raise ValueError('dynamic credentials require explicit provisioning')
        connection = (http.client.HTTPSConnection if endpoint.scheme == 'https' else http.client.HTTPConnection)(
            endpoint.hostname, endpoint.port, timeout=5)
        try:
            connection.request('GET', endpoint.path.rstrip('/') + '/models', headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                raise ReadinessError(f'Local model readiness returned HTTP {response.status}; no inference or service restart was performed.')
            payload = response.read(262145)
            if len(payload) > 262144:
                raise ValueError('oversized endpoint metadata')
            document = decode_json_object(payload.decode('utf-8'), ValueError)
        finally:
            connection.close()
        matching = [m for m in document.get('data', []) if m.get('id') == runtime.model['model']]
        if len(matching) != 1 or matching[0].get('status', {}).get('value') not in {'loaded', 'ready'}:
            raise ReadinessError('The reviewed local model is not reported loaded/ready. Arrange safe startup separately; Agentvolve does not start or restart shared services.')
        return {**result, 'state': 'ready'}
    except ReadinessError:
        raise
    except (ValueError, OSError, KeyError, TypeError, AttributeError, RecursionError, http.client.HTTPException):
        raise ReadinessError('Cannot verify the reviewed local endpoint. Check the separate worker models.json, literal loopback URL/auth and model availability; no inference, credential command or service restart was performed.') from None
