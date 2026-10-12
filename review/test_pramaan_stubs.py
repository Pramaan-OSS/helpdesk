"""Standalone checks: python3 -m unittest discover -s review -p 'test_*.py'."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "helpdesk" / "pramaan.py"
SPEC = importlib.util.spec_from_file_location("pramaan_stub_boundary", MODULE_PATH)
boundary = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = boundary
SPEC.loader.exec_module(boundary)


class FeatureContractTests(unittest.TestCase):
    def test_delivered_features_are_enabled(self):
        features = {item.feature: item for item in boundary.PramaanClient().availability()}
        for feature in ("browser_calling", "automated_threaded_email", "social_sign_in"):
            self.assertTrue(features[feature].enabled, feature)

    def test_browser_session_create_sends_a_contract_shaped_request(self):
        requests = []
        def transport(method, url, headers, body):
            requests.append((method, url, headers, body))
            return 200, {"ref": "ref_session1", "connectUrl": "wss://relay.example/connect",
                         "credential": "short-lived", "expiresAt": "2026-10-12T10:00:00Z",
                         "number": "+14155550111"}
        client = boundary.PramaanClient(api_key="fake", transport=transport)
        result = client.call("voice.browser-session.create",
                             {"agent": "agent-7", "from": "+14155550111",
                              "origin": "https://desk.example.com", "lifetimeSeconds": 900},
                             idempotency_key="key-1", approved_by="agent@example.com")
        self.assertEqual(result["ref"], "ref_session1")
        method, url, headers, body = requests[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/v1/capabilities/voice.browser-session.create"))
        self.assertEqual(headers["Idempotency-Key"], "key-1")
        self.assertEqual(headers["Pramaan-Approved-By"], "agent@example.com")
        self.assertEqual(body["origin"], "https://desk.example.com")

    def test_browser_actions_require_an_idempotency_key(self):
        client = boundary.PramaanClient(api_key="fake", transport=lambda *a: (200, {}))
        for capability, inputs in [
            ("voice.browser-session.create", {"agent": "a", "from": "+14155550111", "origin": "https://x.example.com"}),
            ("voice.browser-call.start", {"ref": "ref_1", "to": "+14155550100"}),
            ("voice.browser-call.accept", {"ref": "ref_2"}),
            ("voice.browser-call.reject", {"ref": "ref_2"}),
            ("voice.call.end", {"ref": "ref_2"}),
        ]:
            with self.subTest(capability=capability):
                with self.assertRaises(boundary.PramaanError):
                    client.run(capability, inputs)

    def test_read_only_events_needs_no_key_and_polls_sync(self):
        calls = []
        client = boundary.PramaanClient(api_key="fake", transport=lambda *a: calls.append(a) or (200, {"events": [{"id": "ve_1", "type": "call.ringing", "at": "x"}]}))
        page = client.call("voice.browser-session.events", {"ref": "ref_1", "cursor": "ve_0"})
        self.assertEqual(page["events"][0]["type"], "call.ringing")
        self.assertTrue(calls[0][1].endswith("/v1/capabilities/voice.browser-session.events"))

    def test_exchange_returns_verified_claims_only(self):
        def transport(method, url, headers, body):
            self.assertEqual(headers["Pramaan-Account"], "sign-in-1")
            self.assertNotIn("client_secret", body)
            return 200, {"providerKey": "google", "subjectId": "sub-1", "email": "a@example.com",
                         "emailVerified": True, "displayName": "Agent"}
        client = boundary.PramaanClient(api_key="fake", transport=transport)
        claims = client.exchange_social_sign_in(provider_key="google", code="one-time",
                                                redirect_uri="https://desk.example.com/callback",
                                                pkce_verifier="v" * 43, expected_nonce="n",
                                                account="sign-in-1")
        self.assertTrue(claims["email_verified"])
        self.assertEqual(claims["subject_id"], "sub-1")

    def test_exchange_refuses_unverified_email(self):
        client = boundary.PramaanClient(api_key="fake", transport=lambda *a: (200, {"providerKey": "google", "subjectId": "s", "email": "a@example.com", "emailVerified": False}))
        with self.assertRaises(boundary.PramaanError):
            client.exchange_social_sign_in(provider_key="google", code="c",
                                           redirect_uri="https://desk.example.com/callback")


if __name__ == "__main__":
    unittest.main()
