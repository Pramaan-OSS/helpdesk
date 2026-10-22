import frappe
from frappe.tests import IntegrationTestCase
from helpdesk.helpdesk.doctype.hd_ticket_template.api import get_one
from helpdesk.test_utils import create_agent, create_contact, make_form_script, make_template, unique_email


class TestHDTicketTemplate(IntegrationTestCase):
    def test_new_ticket_scripts_are_scoped_to_the_signed_in_person(self):
        suffix = frappe.generate_hash(length=8)
        template = make_template(f"Scope {suffix}", [])
        agent = create_agent(unique_email("template-agent")).name
        customer = create_contact("Template Customer", unique_email("template-customer"))
        markers = [f"agent-{suffix}", f"portal-{suffix}"]
        for marker, portal in zip(markers, (False, True)):
            make_form_script(self, marker, marker, apply_to_customer_portal=portal, apply_on_new_page=True)
        for user, wanted, refused in ((agent, markers[0], markers[1]), (customer["user"], markers[1], markers[0])):
            with self.set_user(user):
                scripts = get_one(template.name)["_form_script"] or []
                self.assertTrue(any(wanted in script for script in scripts))
                self.assertFalse(any(refused in script for script in scripts))
