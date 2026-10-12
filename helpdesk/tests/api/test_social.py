"""Social sign-in: verified exchange only; the browser sees no secrets."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse
import base64
import hashlib

from contextlib import ExitStack

import frappe
from frappe.auth import CookieManager
from frappe.tests import IntegrationTestCase
from frappe.tests.utils import change_settings

from helpdesk.api import social
from helpdesk.pramaan import PramaanError
from helpdesk.test_utils import create_user, unique_email

CONFIG = {
    "social_sign_in_enabled": 1,
    "social_provider_key": "google",
    "social_client_id": "helpdesk-client",
    "social_authorize_url": "https://accounts.example.com/o/oauth2/v2/auth",
    "social_scope": "openid email profile",
    "social_use_pkce": 1,
}


class TestSocialSignIn(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Guest")
        frappe.local.cookie_manager = CookieManager()
        self.old_request = getattr(frappe.local, "request", None)
        frappe.local.request = SimpleNamespace(cookies={}, scheme="http", host="pramaan.localhost",
                                               headers=SimpleNamespace(get=lambda *args: ""))
        self.old_login_manager = getattr(frappe.local, "login_manager", None)
        frappe.local.login_manager = MagicMock()

    def tearDown(self):
        frappe.local.request = self.old_request
        if self.old_login_manager is None:
            delattr(frappe.local, "login_manager")
        else:
            frappe.local.login_manager = self.old_login_manager
        frappe.set_user("Administrator")

    def cookie(self):
        return json.loads(frappe.local.cookie_manager.cookies["pramaan_signin"]["value"])

    def configured(self, **overrides):
        """Enable the feature; settings save as System Manager, calls run as Guest."""
        stack = ExitStack()
        stack.enter_context(self.set_user("Administrator"))
        stack.enter_context(change_settings("HD Settings", {**CONFIG, **overrides}))
        stack.enter_context(self.set_user("Guest"))
        self.addCleanup(stack.close)
        return stack

    def test_disabled_sign_in_refuses_to_start(self):
        with self.set_user("Administrator"), change_settings("HD Settings", {"social_sign_in_enabled": 0}):
            self.assertEqual(social.status(), {"enabled": False})
            with self.set_user("Guest"), self.assertRaises(frappe.PermissionError):
                social.start()

    def test_start_refuses_plain_http_endpoints(self):
        with self.set_user("Administrator"), change_settings("HD Settings", {**CONFIG, "social_authorize_url": "http://accounts.example.com/auth"}):
            with self.set_user("Guest"), self.assertRaises(frappe.ValidationError):
                social.start()

    def test_start_builds_signed_state_pkce_and_nonce(self):
        with self.configured():
            result = social.start()
        url = urlparse(result["authorizeUrl"])
        params = parse_qs(url.query)
        self.assertEqual(params["client_id"], ["helpdesk-client"])
        self.assertEqual(params["response_type"], ["code"])
        self.assertTrue(params["redirect_uri"][0].endswith("/api/method/helpdesk.api.social.callback"))
        state = params["state"][0]
        payload, _, signature = state.rpartition(".")
        self.assertEqual(social._state_signature(payload.encode()), signature)
        cookie = self.cookie()
        self.assertEqual(cookie["state"], state)
        self.assertTrue(cookie["nonce"])
        challenge = base64.urlsafe_b64encode(hashlib.sha256(cookie["verifier"].encode()).digest()).decode().rstrip("=")
        self.assertEqual(params["code_challenge"], [challenge])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(params["nonce"], [cookie["nonce"]])

    def test_provider_without_nonce_support_omits_it(self):
        with self.configured(social_provider_key="github"):
            result = social.start()
        params = parse_qs(urlparse(result["authorizeUrl"]).query)
        self.assertNotIn("nonce", params)

    def test_callback_without_state_or_cookie_is_refused(self):
        with self.configured(), self.assertRaises(frappe.Redirect):
            social.callback(code="one-time", state="forged")
        self.assertEqual(frappe.local.flags.redirect_location, "/login?social=expired")

    def test_verified_exchange_opens_a_local_session(self):
        user = create_user(unique_email("social-agent"))
        with self.configured():
            result = social.start()
            state = parse_qs(urlparse(result["authorizeUrl"]).query)["state"][0]
            frappe.local.request.cookies["pramaan_signin"] = json.dumps(self.cookie())
            with patch("helpdesk.api.social.client") as factory:
                factory.return_value.exchange_social_sign_in.return_value = {
                    "provider_key": "google", "subject_id": "sub-1",
                    "email": user.email, "email_verified": True, "display_name": user.full_name,
                }
                with self.assertRaises(frappe.Redirect):
                    social.callback(code="one-time", state=state)
        factory.return_value.exchange_social_sign_in.assert_called_once()
        kwargs = factory.return_value.exchange_social_sign_in.call_args.kwargs
        self.assertEqual(kwargs["provider_key"], "google")
        self.assertEqual(kwargs["redirect_uri"], frappe.utils.get_url("/api/method/helpdesk.api.social.callback"))
        self.assertTrue(kwargs["pkce_verifier"])
        self.assertTrue(kwargs["expected_nonce"])
        frappe.local.login_manager.login_as.assert_called_once_with(user.name)
        self.assertEqual(frappe.local.flags.redirect_location, "/helpdesk")

    def test_unverified_email_never_reaches_a_session(self):
        user = create_user(unique_email("social-agent"))
        with self.configured():
            result = social.start()
            state = parse_qs(urlparse(result["authorizeUrl"]).query)["state"][0]
            frappe.local.request.cookies["pramaan_signin"] = json.dumps(self.cookie())
            with patch("helpdesk.api.social.client") as factory:
                factory.return_value.exchange_social_sign_in.side_effect = PramaanError("identity_unverified")
                with self.assertRaises(frappe.Redirect):
                    social.callback(code="one-time", state=state)
        self.assertEqual(frappe.local.flags.redirect_location, "/login?social=rejected")
        frappe.local.login_manager.login_as.assert_not_called()

    def test_unknown_email_is_refused_with_an_invite_hint(self):
        email = unique_email("no-such-account")
        with self.configured():
            result = social.start()
            state = parse_qs(urlparse(result["authorizeUrl"]).query)["state"][0]
            frappe.local.request.cookies["pramaan_signin"] = json.dumps(self.cookie())
            with patch("helpdesk.api.social.client") as factory:
                factory.return_value.exchange_social_sign_in.return_value = {
                    "provider_key": "google", "subject_id": "sub-2",
                    "email": email, "email_verified": True, "display_name": "Nobody",
                }
                with self.assertRaises(frappe.Redirect):
                    social.callback(code="one-time", state=state)
        self.assertEqual(frappe.local.flags.redirect_location, "/login?social=unknown")
        frappe.local.login_manager.login_as.assert_not_called()
