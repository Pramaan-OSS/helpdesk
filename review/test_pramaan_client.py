"""Contract and safety tests; every request uses an in-memory fake."""
import unittest
from unittest.mock import patch
from test_pramaan_stubs import boundary, FakeTransport

class ClientTests(unittest.TestCase):
    def test_sending_result_controls_delivery_tracking(self):
        for capability, result, expected in [
            ("email.send", {"status": "queued", "ref": "mail"}, False),
            ("email.send", {"status": "queued", "ref": "mail", "trackable": False}, False),
            ("email.send", {"status": "sent", "ref": "mail", "trackable": True}, True),
            ("email.message.send", {"messageId": "mail"}, True),
            ("email.message.reply", {"messageId": "mail", "trackable": False}, False),
        ]:
            with self.subTest(capability=capability, result=result):
                fake = FakeTransport(response=result)
                response = boundary.PramaanClient(api_key="fake", transport=fake).call(capability, {}, idempotency_key="saved")
                visible = boundary.email_is_trackable(capability, response)
                self.assertEqual(visible, expected)
                stored = "Enabled" if visible else "Disabled"
                self.assertEqual(boundary.email_is_trackable(capability, stored=stored), expected)
        self.assertFalse(boundary.email_is_trackable("email.send", {"trackable": "true"}))
        self.assertFalse(boundary.email_is_trackable("email.send", stored="Unknown"))

    def test_local_approval_actor_is_not_sent_as_a_platform_member(self):
        fake = FakeTransport(response={"status": "sent", "ref": "accepted-mail"})
        client = boundary.PramaanClient(api_key="fake", transport=fake)
        result = client.call("email.send", {"from": "sender@example.com", "to": ["recipient@example.com"], "subject": "Support", "text": "Hello"},
                             idempotency_key="persisted-mail-intent", approved_by="Administrator")
        self.assertEqual(result["ref"], "accepted-mail")
        self.assertNotIn("Pramaan-Approved-By", fake.requests[0][2])
        self.assertEqual(fake.requests[0][2]["Idempotency-Key"], "persisted-mail-intent")
        self.assertEqual(fake("POST", "https://pramaan.test/v1/capabilities/email.send", {"Pramaan-Approved-By": "Administrator"}, {})[0], 403)

    def test_missing_key_is_clear_and_never_calls_transport(self):
        calls = []
        client = boundary.PramaanClient(api_key="", transport=lambda *args: calls.append(args))
        with self.assertRaises(boundary.MissingPramaanKey) as raised:
            client.call("llm.complete", {})
        self.assertEqual(raised.exception.http_status_code, 422)
        self.assertEqual("Add PRAMAAN_API_KEY to .env", str(raised.exception))
        self.assertFalse(client.configured)
        self.assertEqual(calls, [])

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

    def test_uploaded_document_keeps_raw_bytes_and_content_type(self):
        requests = []
        def transport(*args):
            requests.append(args)
            return 201, {"fileId": "uploaded-document"}
        client = boundary.PramaanClient(api_key="fake", transport=transport)
        self.assertEqual(client.upload_file(b"Document", "text/plain")["fileId"], "uploaded-document")
        self.assertTrue(requests[0][1].endswith("/v1/files?kind=document"))
        self.assertEqual(requests[0][2]["Content-Type"], "text/plain")
        self.assertEqual(requests[0][3], b"Document")

    def test_enrichment_no_match_is_final_and_keeps_no_upstream_message(self):
        calls = []
        def transport(*args):
            calls.append(args)
            return 404, {"error": {"code": "not_found", "message": "Private diagnostic"}}
        client = boundary.PramaanClient(api_key="fake", transport=transport)
        with self.assertRaises(boundary.PramaanError) as raised:
            client.call("people.enrich", {"email": "person@example.com"})
        self.assertEqual(raised.exception.code, "not_found")
        self.assertFalse(raised.exception.uncertain)
        self.assertNotIn("Private", str(raised.exception))
        self.assertEqual(len(calls), 1)
        import io
        import json
        from urllib.error import HTTPError
        payload = io.BytesIO(json.dumps({"error": {"code": "not_found", "message": "Private diagnostic"}}).encode())
        with patch.object(boundary, "build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError("https://pramaan.test", 404, "not found", {}, payload)
            with self.assertRaises(boundary.PramaanError) as refused:
                boundary.PramaanClient(api_key="fake").call("people.enrich", {"email": "person@example.com"})
        self.assertEqual(refused.exception.code, "not_found")
        self.assertFalse(refused.exception.uncertain)

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


    def test_http_unavailable_codes_are_preserved_without_upstream_text(self):
        import io
        import json
        from urllib.error import HTTPError
        payload = io.BytesIO(json.dumps({"error": {"code": "upstream_unavailable", "message": "private upstream diagnostics"}}).encode())
        client = boundary.PramaanClient(api_key="fake", base_url="https://pramaan.test")
        with patch.object(boundary, "build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError("https://pramaan.test", 502, "unavailable", {}, payload)
            with self.assertRaises(boundary.PramaanNotAvailable) as raised:
                client.call("voice.call.start-configured", {}, idempotency_key="fixture")
            self.assertEqual(str(raised.exception), "Calling is not available yet.")
            self.assertNotIn("private", str(raised.exception))
            opener.return_value.open.assert_called_once()
        payload.close()
