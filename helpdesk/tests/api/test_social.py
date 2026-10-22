"""Retired authorization paths cannot exchange codes or open a session."""
from unittest.mock import patch
import frappe
from frappe.tests import IntegrationTestCase
from helpdesk.api import social
from helpdesk.api.settings import signin


class TestLocalSignIn(IntegrationTestCase):
    def test_external_sign_in_stays_disabled_even_with_old_settings(self):
        with self.set_user("Administrator"):
            self.assertEqual(social.status(), {"enabled": False})
            self.assertFalse(signin.get_data()["enabled"])
            with self.assertRaises(frappe.ValidationError):
                signin.update_data(enabled=True, authorizeUrl="https://accounts.example.test/auth")

    def test_old_start_refuses_without_an_outside_request(self):
        with self.set_user("Guest"), self.assertRaises(frappe.ValidationError):
            social.start()

    def test_old_callback_returns_to_password_sign_in_without_a_session(self):
        with self.set_user("Guest"), patch("frappe.auth.LoginManager.login_as") as login:
            with self.assertRaises(frappe.Redirect):
                social.callback(code="fixture", state="fixture", redirect_to="https://outside.example.test")
            self.assertEqual(frappe.local.flags.redirect_location, "/login?social=unavailable")
            login.assert_not_called()
