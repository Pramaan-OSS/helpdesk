"""Deterministic transport for the disposable browser site only; no network."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from helpdesk.pramaan import generation_request


def transport(method, url, headers, body):
    path = urlparse(url).path
    log = Path('/app/.runtime/bench/logs/qa-requests.jsonl')
    with log.open('a') as stream:
        stream.write(json.dumps({'method': method, 'path': path}) + '\n')
    if path.startswith('/v1/outcomes/'):
        parts = path.split('/')
        name = parts[3]
        if name not in {'document.summarize', 'call.review'}:
            return 404, {'error': {'code': 'not_found'}}
        steps = [{'capability': 'document.parse' if name == 'document.summarize' else 'audio.transcription.create'}, {'capability': 'llm.complete'}]
        plan = 'fixture-' + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        if method == 'GET':
            return 200, {'available': True, 'effect_class': 'read_only', 'steps': steps}
        if path.endswith('/estimate'):
            return 200, {'plan': plan, 'can_run': True, 'price_max_micro': 12345, 'steps': steps}
        if headers.get('Pramaan-Plan') != plan:
            return 409, {'error': {'code': 'conflict'}}
        result = {'summary': 'The private attachment describes the support request.', 'points': [{'text': 'Check the supplied details.'}], 'truncated': False} if name == 'document.summarize' else {'findings': [{'criterion': 'Agent explained the next step', 'outcome': 'met', 'quote': 'We will check the details.', 'start': 1, 'note': 'Review the quoted words.'}], 'truncated': False}
        return 200, {'status': 'done', 'completeness': 'complete', 'steps': steps, 'result': result}
    capability = path.rsplit('/', 1)[-1]
    if capability in {'llm.chat', 'llm.complete'}:
        generation_request(body, normalise=False)
        return 200, {'text': 'Suggested support text for review.', 'finishReason': 'stop'}
    if capability == 'companies.enrich':
        return 200, {'name': 'Local fixture company', 'industry': 'Support'}
    if capability == 'people.enrich':
        return 200, {'name': 'Local fixture contact'}
    if capability == 'document.parse':
        return 200, {'text': base64.b64decode(body['content']).decode(errors='replace'), 'truncated': False}
    if capability in {'web.read', 'web.crawl'}:
        return 200, {'text': 'Local fixture documentation for article review.'}
    if capability == 'voice.call.recording.get':
        return 200, {'recording': {'url': 'https://recording.example.test/fixture', 'fileId': 'fixture-recording', 'contentType': 'audio/mpeg', 'sizeBytes': 512, 'expiresAt': (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()}}
    if capability in {'email.message.send', 'email.message.reply'}:
        identity = hashlib.sha256(headers['Idempotency-Key'].encode()).hexdigest()
        return 200, {'messageId': f'<{identity}@example.test>', 'ref': 'ref_fixture'}
    return 503, {'error': {'code': 'upstream_unavailable', 'retryable': False}}
