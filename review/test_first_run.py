"""Exercise first-run completion without a database or outside requests."""
import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch


class FirstRunTests(unittest.TestCase):
    def load(self, completed=False):
        frappe = MagicMock()
        frappe.is_setup_complete.side_effect = [completed, True]
        wizard = ModuleType('frappe.desk.page.setup_wizard.setup_wizard')
        wizard.setup_complete = MagicMock(return_value={'status': 'ok'})
        modules = {'frappe': frappe, wizard.__name__: wizard}
        spec = importlib.util.spec_from_file_location(
            'first_run_test', Path(__file__).resolve().parents[1] / 'helpdesk/setup/first_run.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(module)
        return module, frappe, wizard, modules

    def test_completed_site_is_untouched(self):
        module, frappe, wizard, modules = self.load(True)
        with patch.dict(sys.modules, modules):
            module.complete()
        wizard.setup_complete.assert_not_called()
        frappe.set_user.assert_not_called()
        frappe.db.commit.assert_not_called()

    def test_real_wizard_receives_defaults_and_admin_session(self):
        module, frappe, wizard, modules = self.load()
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {}, clear=True):
            module.complete()
        frappe.set_user.assert_called_once_with('Administrator')
        args = wizard.setup_complete.call_args.args[0]
        self.assertEqual((args['language'], args['timezone'], args['currency']),
                         ('English', 'Etc/UTC', 'USD'))
        self.assertNotIn('email', args)
        frappe.db.commit.assert_called_once()

    def test_custom_region_is_used(self):
        module, frappe, wizard, modules = self.load()
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {
            'HELPDESK_TIMEZONE': 'Europe/London', 'HELPDESK_CURRENCY': 'GBP'
        }):
            module.complete()
        args = wizard.setup_complete.call_args.args[0]
        self.assertEqual((args['timezone'], args['currency']), ('Europe/London', 'GBP'))

    def test_incomplete_setup_is_not_committed(self):
        module, frappe, wizard, modules = self.load()
        frappe.is_setup_complete.side_effect = [False, False]
        with patch.dict(sys.modules, modules), self.assertRaises(RuntimeError):
            module.complete()
        frappe.db.commit.assert_not_called()

    def test_missing_agent_is_not_committed(self):
        module, frappe, wizard, modules = self.load()
        frappe.db.exists.return_value = False
        with patch.dict(sys.modules, modules), self.assertRaises(RuntimeError):
            module.complete()
        frappe.db.commit.assert_not_called()
