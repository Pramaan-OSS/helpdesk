"""The disposable browser transport remains deterministic and cannot use network I/O."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import qa_transport
from helpdesk.pramaan import InvalidGenerationRequest


class QATransportTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.scratch/qa'
        root.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.directory.cleanup)
        log = Path(self.directory.name) / 'requests.jsonl'
        self.path = patch.object(qa_transport, 'Path', return_value=log)
        self.path.start()
        self.addCleanup(self.path.stop)

    def test_a_plan_works_across_requests_and_changed_input_is_refused(self):
        body = {'input': {'content': 'fixture'}, 'options': {}, 'basis': {}}
        url = 'https://fixture.example.test/v1/outcomes/document.summarize'
        status, estimate = qa_transport.transport('POST', url + '/estimate', {}, body)
        self.assertEqual(status, 200)
        status, result = qa_transport.transport('POST', url, {'Pramaan-Plan': estimate['plan']}, body)
        self.assertEqual(status, 200)
        self.assertEqual(result['status'], 'done')
        changed = dict(body, options={'changed': True})
        self.assertEqual(qa_transport.transport('POST', url, {'Pramaan-Plan': estimate['plan']}, changed)[0], 409)

    def test_generation_requests_still_need_the_real_wire_contract(self):
        url = 'https://fixture.example.test/v1/capabilities/llm.complete'
        with self.assertRaises(InvalidGenerationRequest):
            qa_transport.transport('POST', url, {}, {'prompt': 'legacy'})
        status, result = qa_transport.transport('POST', url, {}, {'messages': [{'role': 'user', 'content': 'Draft'}], 'maxTokens': 1024})
        self.assertEqual(status, 200)
        self.assertEqual(result['finishReason'], 'stop')

    def test_unrouted_actions_are_unavailable_instead_of_falling_through(self):
        status, result = qa_transport.transport('POST', 'https://fixture.example.test/v1/capabilities/voice.call.create', {}, {})
        self.assertEqual(status, 503)
        self.assertEqual(result['error']['code'], 'upstream_unavailable')
