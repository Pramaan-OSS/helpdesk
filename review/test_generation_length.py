import unittest
from test_pramaan_stubs import boundary, FakeTransport


class GenerationLengthTests(unittest.TestCase):
    def test_free_text_preserves_length_marker_for_review_without_retry(self):
        fake = FakeTransport({"text": "Partial text", "finishReason": "length"})
        result = boundary.PramaanClient(api_key="fake", transport=fake).call(
            "llm.complete", {"messages": [{"role": "user", "content": "Draft"}]})
        self.assertEqual(result["finishReason"], "length")
        self.assertEqual(len(fake.requests), 1)
        self.assertGreaterEqual(fake.requests[0][3]["maxTokens"], 256)

    def test_structured_and_tool_replies_fail_before_use(self):
        for capability, fields in [("llm.complete", {"jsonSchema": {"type": "object", "properties": {}}}),
                ("llm.chat", {"tools": [{"name": "save", "parameters": {"type": "object", "properties": {}}}]})]:
            fake = FakeTransport({"text": '{"name":', "finishReason": "length"})
            with self.assertRaisesRegex(boundary.IncompleteGeneration, "incomplete"):
                boundary.PramaanClient(api_key="fake", transport=fake).call(capability,
                    {"messages": [{"role": "user", "content": "Draft"}], **fields})
            self.assertEqual(len(fake.requests), 1)

    def test_final_max_tokens_refusal_is_plain_configuration_error(self):
        fake = FakeTransport({"error": {"code": "invalid_request", "message": "maxTokens reached without output"}}, status=400)
        with self.assertRaisesRegex(boundary.GenerationConfigurationError, "administrator") as error:
            boundary.PramaanClient(api_key="fake", transport=fake).call("llm.chat",
                {"messages": [{"role": "user", "content": "Draft"}]})
        self.assertFalse(error.exception.uncertain)
        self.assertEqual(len(fake.requests), 1)

    def test_http_preserves_only_the_safe_reply_limit_marker(self):
        import io
        from urllib.error import HTTPError
        from unittest.mock import patch
        failure = HTTPError("https://platform.example.test", 400, "Bad request", {},
            io.BytesIO(b'{"error":{"code":"invalid_request","message":"maxTokens exhausted; hidden service detail"}}'))
        with patch.object(boundary, "build_opener") as opener:
            opener.return_value.open.side_effect = failure
            with self.assertRaisesRegex(boundary.GenerationConfigurationError, "administrator") as raised:
                client = boundary.PramaanClient(api_key="fake")
                client._transport = client._http  # Only the mocked HTTP decoder is exercised.
                client.call("llm.complete", {"messages": [{"role": "user", "content": "Draft"}]})
        self.assertNotIn("hidden", str(raised.exception))
        self.assertEqual(opener.return_value.open.call_count, 1)
