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


class MissingCapabilityTests(unittest.TestCase):
    def test_features_are_explicitly_disabled(self):
        features = boundary.PramaanClient().availability()
        self.assertEqual(
            {item.feature for item in features},
            {"browser_calling", "automated_threaded_email", "social_sign_in"},
        )
        self.assertTrue(all(not item.enabled and item.reason for item in features))

    def test_calls_fail_without_network_or_secret_disclosure(self):
        client = boundary.PramaanClient()
        secret = "private-input-must-not-appear"
        operations = [
            ("browser_calling", lambda: client.start_browser_voice_session(
                agent_ref=secret, number_ref=secret, origin="https://app.example"
            )),
            ("automated_threaded_email", lambda: client.send_automated_or_edited_threaded_email(
                inbox="support@example.com", recipients=("customer@example.com",),
                subject=secret, text=secret, parent_message_id=secret, automated=True
            )),
            ("social_sign_in", lambda: client.exchange_social_sign_in(
                connection_ref=secret, authorization_code=secret,
                redirect_uri="https://app.example/callback", pkce_verifier=secret,
                state=secret
            )),
        ]
        with patch("socket.socket") as socket, patch("urllib.request.urlopen") as http:
            for feature, operation in operations:
                with self.subTest(feature=feature):
                    with self.assertRaises(boundary.CapabilityUnavailable) as raised:
                        operation()
                    self.assertEqual(raised.exception.code, "capability_unavailable")
                    self.assertEqual(raised.exception.feature, feature)
                    self.assertNotIn(secret, str(raised.exception))
            socket.assert_not_called()
            http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
