"""Automatic email settings remain disabled until platform loop markers exist."""
from unittest.mock import patch
import frappe
from frappe.tests import IntegrationTestCase
from helpdesk.api.settings import email_notifications as settings
from helpdesk.pramaan import CapabilityUnavailable
from helpdesk.test_utils import create_agent, make_agent_manager, unique_email

class TestEmailNotifications(IntegrationTestCase):
    def test_manager_sees_disabled_automatic_features(self):
        with self.set_user(make_agent_manager("notification-manager")):
            for feature in ("acknowledgement", "share_feedback", "reply_to_agents"):
                result = settings.get_data(feature)
                self.assertFalse(result["enabled"])
                self.assertFalse(result["available"])
                self.assertIn("not available", result["reason"])

    def test_automatic_email_cannot_be_enabled(self):
        with self.set_user("Administrator"):
            for update in (settings.update_acknowledgement, settings.update_reply_to_agents):
                with self.assertRaises(CapabilityUnavailable):
                    update(enabled=True, content="Hello")

    def test_agent_cannot_change_email_settings(self):
        agent = create_agent(unique_email("notification-agent"))
        with self.set_user(agent.name), self.assertRaises(frappe.PermissionError):
            settings.update_acknowledgement(enabled=True, content="Hello")
