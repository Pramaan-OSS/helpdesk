"""Delivery tracking survives durable sending without a database or network."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from test_pramaan_stubs import boundary, FakeTransport


class MailTrackingTests(unittest.TestCase):
    def test_fake_sends_persist_tracking_and_gate_communication_metadata(self):
        spec = importlib.util.spec_from_file_location("mail_tracking_fixture", Path(__file__).resolve().parents[1] / "helpdesk/integrations/pramaan_mail/__init__.py")
        mail = importlib.util.module_from_spec(spec)
        framework = MagicMock()
        with patch.dict(sys.modules, {"frappe": framework, "helpdesk.pramaan": boundary}):
            spec.loader.exec_module(mail)
        for capability, response, expected in [
            ("email.send", {"status": "queued", "ref": "mail"}, "Disabled"),
            ("email.send", {"status": "sent", "ref": "mail", "trackable": False}, "Disabled"),
            ("email.send", {"status": "sent", "ref": "mail", "trackable": True}, "Enabled"),
            ("email.message.send", {"messageId": "mail"}, "Enabled"),
            ("email.message.send", {"messageId": "mail", "trackable": False}, "Disabled"),
        ]:
            with self.subTest(capability=capability, response=response):
                row = SimpleNamespace(name="outbox", state="Pending", capability=capability, payload='{"from":"sender@example.com","to":["recipient@example.com"],"subject":"Support","html":"Hello"}', idempotency_key="saved-intent", requested_by="Administrator", communication="communication", error="")
                row.reload = lambda: None
                row.db_set = lambda values, value=None: row.__dict__.update(values if isinstance(values, dict) else {values: value})
                framework.get_doc.return_value = row
                framework.get_all.return_value = []
                fake = FakeTransport(response=response)
                with patch.object(mail, "client", return_value=boundary.PramaanClient(api_key="fake", transport=fake)):
                    mail.deliver("outbox")
                    mail.deliver("outbox")
                self.assertEqual(row.state, "Accepted")
                self.assertEqual(row.delivery_tracking, expected)
                self.assertEqual(len(fake.requests), 1)
                framework.get_all.side_effect = [[SimpleNamespace(name="communication", email_account=None)], [SimpleNamespace(communication="communication", capability=capability, delivery_tracking=row.delivery_tracking)]]
                self.assertEqual(mail.communication_tracking("ticket"), {"communication": expected == "Enabled"})
                framework.get_all.side_effect = None
