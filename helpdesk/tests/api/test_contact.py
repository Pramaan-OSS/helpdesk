# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from helpdesk.api.contact import delete_contact
from helpdesk.test_utils import create_contact, create_customer, make_ticket


class TestDeleteContact(IntegrationTestCase):
    def setUp(self) -> None:
        frappe.set_user("Administrator")

    def tearDown(self) -> None:
        frappe.set_user("Administrator")

    def test_delete_contact_unlinks_tickets_and_invitations(self) -> None:
        email = "delete-contact-unlink@example.com"
        contact, customer, ticket, invitation = self.setup_contact_for_delete(
            "Test Contact Unlink", email
        )

        delete_contact(contact["contact"])

        self.assertFalse(frappe.db.exists("Contact", contact["contact"]))
        ticket.reload()
        self.assertIsNone(ticket.contact)
        invitation.reload()
        self.assertIsNone(invitation.contact)
        self.assertFalse(
            frappe.db.exists(
                "HD Customer Member",
                {"parent": customer.name, "contact_name": contact["contact"]},
            )
        )

    def test_delete_contact_deletes_linked_tickets(self) -> None:
        email = "delete-contact-tickets@example.com"
        contact, _, ticket, invitation = self.setup_contact_for_delete(
            "Test Contact Delete Tickets", email
        )

        delete_contact(contact["contact"], delete_tickets=True)

        self.assertFalse(frappe.db.exists("Contact", contact["contact"]))
        self.assertFalse(frappe.db.exists("HD Ticket", ticket.name))
        invitation.reload()
        self.assertIsNone(invitation.contact)

    def test_delete_contact_clears_customer_primary_contact(self) -> None:
        email = "delete-contact-primary@example.com"
        contact_doc, customer, _, _ = self.setup_contact_for_delete(
            "Test Contact Primary", email
        )
        customer.primary_contact = contact_doc["contact"]
        customer.save()

        delete_contact(contact_doc["contact"])

        customer.reload()
        self.assertIsNone(customer.primary_contact)

    def setup_contact_for_delete(self, customer_name: str, email: str):
        for inv in frappe.db.get_all("User Invitation", {"email": email}, pluck="name"):
            frappe.delete_doc("User Invitation", inv, force=True)

        contact = create_contact("DeleteContact", email, user=False)
        customer = create_customer(
            customer_name, [{"contact_name": contact["contact"]}]
        )
        ticket = make_ticket(customer=customer.name, contact=contact["contact"])
        invitation = frappe.get_doc(
            {
                "doctype": "User Invitation",
                "email": email,
                "app_name": "helpdesk",
                "redirect_to_path": "/helpdesk",
                "roles": [{"role": "HD Customer"}],
                "customer": customer.name,
                "contact": contact["contact"],
            }
        ).insert(ignore_permissions=True)
        return contact, customer, ticket, invitation


class TestEnrichmentSuggestions(IntegrationTestCase):
    def test_company_profile_is_shown_without_overwriting_saved_details(self):
        from helpdesk.api.capabilities import enrich_customer
        customer = create_customer("Enrichment " + frappe.generate_hash(length=8))
        customer.domain = "example.com"
        customer.save()
        profile = {"name": "Suggested company", "domain": "example.com", "industry": "Software"}
        with patch("helpdesk.api.capabilities.client") as factory:
            factory.return_value.call.return_value = profile
            result = enrich_customer(customer.name)
        self.assertEqual(result["company"], profile)
        factory.return_value.call.assert_called_once_with("companies.enrich", {"domain": "example.com"})
        self.assertEqual(customer.reload().customer_name, customer.name)

    def test_person_profile_is_shown_without_overwriting_saved_contact(self):
        from helpdesk.api.capabilities import enrich_contact
        from helpdesk.test_utils import unique_email
        name = "Enrichment " + frappe.generate_hash(length=8)
        email = unique_email("enrich")
        contact = create_contact(name, email, user=False)
        profile = {"fullName": "Suggested person", "title": "Support lead"}
        with patch("helpdesk.api.capabilities.client") as factory:
            factory.return_value.call.return_value = profile
            result = enrich_contact(contact["contact"])
        self.assertEqual(result["person"], profile)
        factory.return_value.call.assert_called_once_with("people.enrich", {"email": email})
        self.assertEqual(frappe.db.get_value("Contact", contact["contact"], "first_name"), name)
