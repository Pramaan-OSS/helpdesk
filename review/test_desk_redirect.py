"""Desk routing must not change API access or redirect unrelated requests."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch


class DeskRedirectTests(unittest.TestCase):
    def check_route(self, path, user='Administrator', method='GET', redirect=False):
        frappe = MagicMock()
        frappe.local.request.path = path
        frappe.local.request.method = method
        frappe.session.user = user
        class Redirect(Exception):
            pass
        frappe.Redirect = Redirect
        spec = importlib.util.spec_from_file_location(
            'desk_redirect_test', Path(__file__).resolve().parents[1] / 'helpdesk/desk_redirect.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': frappe}):
            spec.loader.exec_module(module)
        if redirect:
            with self.assertRaises(Redirect) as caught:
                module.redirect_to_helpdesk()
            self.assertEqual(caught.exception.args, (302,))
            self.assertEqual(frappe.local.flags.redirect_location, '/helpdesk')
        else:
            module.redirect_to_helpdesk()
            self.assertNotEqual(frappe.local.flags.redirect_location, '/helpdesk')

    def test_signed_in_desk_visitors_reach_helpdesk(self):
        for path in ['/desk', '/desk/', '/desk/setup-wizard', '/desk/workspace']:
            self.check_route(path, redirect=True)

    def test_guest_and_write_requests_are_unchanged(self):
        self.check_route('/desk', user='Guest')
        self.check_route('/desk', method='POST')

    def test_api_and_other_routes_are_unchanged(self):
        for path in ['/api/method/example', '/helpdesk', '/desk-other', '/login']:
            self.check_route(path)
