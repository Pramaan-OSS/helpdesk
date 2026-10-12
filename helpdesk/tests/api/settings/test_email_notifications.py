"""Automatic email settings are live and editable through the boundary."""
from unittest.mock import patch
import frappe
from frappe.tests import IntegrationTestCase
from helpdesk.api.settings import email_notifications as settings
from helpdesk.test_utils import create_agent, make_agent_manager, unique_email

class TestEmailNotifications(IntegrationTestCase):
    def test_manager_reads_real_automatic_features(self):
        with self.set_user(make_agent_manager("notification-manager")):
            for feature in ("acknowledgement", "share_feedback", "reply_to_agents"):
                result = settings.get_data(feature)
                self.assertIn("enabled", result)
                self.assertIn("content", result)
                self.assertNotIn("available", result)

    def test_manager_can_enable_automated_email(self):
        with self.set_user("Administrator"):
            result = settings.update_acknowledgement(enabled=True, content="We got your ticket.")
        self.assertTrue(result["enabled"])
        self.assertEqual(
            frappe.db.get_single_value("HD Settings", "send_acknowledgement_email"), 1
        )

    def test_agent_cannot_change_email_settings(self):
        agent = create_agent(unique_email("notification-agent"))
        with self.set_user(agent.name), self.assertRaises(frappe.PermissionError):
            settings.update_acknowledgement(enabled=True, content="Hello")

    def test_invalid_template_content_is_refused(self):
        with self.set_user("Administrator"), self.assertRaises(Exception):
            settings.update_acknowledgement(enabled=True, content="{{ broken")
