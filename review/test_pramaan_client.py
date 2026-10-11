"""Contract and safety tests; every request uses an in-memory fake."""
import unittest
from unittest.mock import patch
from test_pramaan_stubs import boundary

class ClientTests(unittest.TestCase):
    def test_async_completion_uses_same_job_and_only_one_action(self):
        requests = []
        replies = iter([(202, {"job_id": "job/one", "status": "running"}), (200, {"status": "done", "result": {"messageId": "accepted"}})])
        def transport(*args):
            requests.append(args)
            return next(replies)
        client = boundary.PramaanClient(api_key="fake", transport=transport, sleep=lambda _: None)
        self.assertEqual(client.call("email.message.send", {"from":"support@example.com"}, idempotency_key="saved-key"), {"messageId":"accepted"})
        self.assertEqual([r[0] for r in requests], ["POST", "GET"])
        self.assertEqual(requests[0][2]["Idempotency-Key"], "saved-key")
        self.assertTrue(requests[1][1].endswith("/jobs/job%2Fone"))

    def test_uncertain_action_is_not_retried_and_error_is_safe(self):
        calls = []
        def transport(*args):
            calls.append(args)
            raise RuntimeError("vendor secret customer data")
        client = boundary.PramaanClient(api_key="fake", transport=transport)
        with self.assertRaises(boundary.PramaanError) as raised:
            client.call("email.message.send", {}, idempotency_key="saved")
        self.assertTrue(raised.exception.uncertain)
        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(len(calls), 1)

    def test_invalid_actions_are_rejected_before_transport(self):
        calls = []
        client = boundary.PramaanClient(api_key="fake", transport=lambda *args: calls.append(args))
        for cap in ["invented.capability", "email.message.send"]:
            with self.assertRaises(boundary.PramaanError):
                client.run(cap, {})
        self.assertEqual(calls, [])

    def test_redirects_never_forward_credentials(self):
        self.assertIsNone(boundary.NoRedirects().redirect_request(None,None,302,"",{},"https://elsewhere.example"))

    def test_configuration_rejects_credentials_and_remote_plain_http(self):
        for url in ["http://remote.example", "https://user:password@example.com", "https://example.com?secret=key"]:
            with self.assertRaises(boundary.PramaanError):
                boundary.PramaanClient(base_url=url)

    def test_invalid_completed_result_is_rejected(self):
        client = boundary.PramaanClient(api_key="fake", transport=lambda *args: (202, {"job_id":"one", "status":"done", "result":None}))
        with self.assertRaises(boundary.PramaanError):
            client.call("email.message.send", {}, idempotency_key="saved")

    def test_recording_rejects_private_download_hosts_before_http(self):
        client = boundary.PramaanClient(api_key="never-forward-this-key")
        recording = {"url":"https://private.example/audio", "contentType":"audio/mpeg", "sizeBytes":3}
        with patch("socket.getaddrinfo", return_value=[(None,None,None,None,("127.0.0.1",443))]), patch.object(boundary, "build_opener") as http:
            with self.assertRaises(boundary.PramaanError):
                client.recording_bytes(recording)
            http.assert_not_called()
