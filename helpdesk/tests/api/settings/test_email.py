import imaplib
import json
from typing import Any
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from helpdesk.api.auth import get_current_user_email_info, set_user_email_accounts
from helpdesk.api.settings.email import create_email_account
from helpdesk.test_utils import (
    create_agent,
    create_user,
    get_linked_email_accounts,
    make_agent_manager,
    make_email_account,
    make_email_account_data,
    unique_email,
)

EMAIL_ACCOUNT_MODULE = "frappe.email.doctype.email_account.email_account"


class TestCreateEmailAccount(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.pramaan = self.enterContext(patch("helpdesk.api.settings.email.client")).return_value
        self.pramaan.call.return_value = {"address": "support@example.com", "status": "active"}

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_owned_mailbox_has_no_vendor_credentials(self):
        data = make_email_account_data(None)
        account = frappe.get_doc("Email Account", create_email_account(data))
        self.assertEqual(account.email_id, data["email_id"])
        self.assertEqual(account.append_to, "HD Ticket")
        self.assertFalse(account.smtp_server or account.email_server or account.password)
        self.pramaan.call.assert_called_once_with("email.inbox.get", {"address": data["email_id"]})

    def test_vendor_configuration_rejected_before_network(self):
        data = make_email_account_data(None, smtp_server="mail.example.com", password="secret")
        with self.assertRaises(frappe.ValidationError):
            create_email_account(data)
        self.pramaan.call.assert_not_called()
        self.assertFalse(frappe.db.exists("Email Account", {"email_id": data["email_id"]}))

    def test_invalid_address_rejected_before_network(self):
        with self.assertRaises(frappe.ValidationError):
            create_email_account(make_email_account_data(None, email_id="invalid"))
        self.pramaan.call.assert_not_called()

    def test_agent_cannot_connect_mailbox(self):
        agent = create_agent(unique_email("email-agent"))
        with self.set_user(agent.name), self.assertRaises(frappe.PermissionError):
            create_email_account(make_email_account_data(None))
        self.pramaan.call.assert_not_called()

    def test_manager_can_connect_owned_mailbox(self):
        data = make_email_account_data(None)
        with self.set_user(make_agent_manager("email-manager")):
            name = create_email_account(data)
        self.assertEqual(frappe.db.get_value("Email Account", name, "email_id"), data["email_id"])


class TestSetUserEmailAccounts(IntegrationTestCase):
    """Agents manage links to outgoing accounts only; other links stay."""

    def setUp(self) -> None:
        frappe.set_user("Administrator")
        self.enterContext(patch("helpdesk.api.settings.email.client"))
        self.agent = create_agent(unique_email("email-agent")).name
        self.support = make_email_account("owned", enable_incoming=0)
        self.sales = make_email_account("owned", enable_incoming=0)
        self.incoming_only = make_email_account("owned", enable_outgoing=0)

    def test_agent_replaces_outgoing_links_and_keeps_other_links(self) -> None:
        user = frappe.get_doc("User", self.agent)
        user.append("user_emails", {"email_account": self.incoming_only})
        user.save()

        with self.set_user(self.agent):
            set_user_email_accounts([self.support])
            self.assertEqual(
                get_linked_email_accounts(self.agent),
                {self.incoming_only, self.support},
            )
            # the settings screen lists only the outgoing links
            outgoing = get_current_user_email_info()["outgoing_emails"]
            self.assertEqual([row.email_account for row in outgoing], [self.support])

            set_user_email_accounts([self.sales, self.sales])
            self.assertEqual(
                get_linked_email_accounts(self.agent), {self.incoming_only, self.sales}
            )

    def test_accounts_without_outgoing_email_are_not_linked(self) -> None:
        with self.set_user(self.agent):
            set_user_email_accounts([self.incoming_only, "No Such Account"])

        self.assertEqual(get_linked_email_accounts(self.agent), set())

    def test_non_agent_cannot_set_email_accounts(self) -> None:
        user = create_user(unique_email("not-an-agent")).name

        with self.set_user(user), self.assertRaises(frappe.PermissionError):
            set_user_email_accounts([self.support])


class TestPramaanDelivery(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.enterContext(patch("helpdesk.api.settings.email.client"))
        self.account = make_email_account("owned")
        self.address = frappe.db.get_value("Email Account", self.account, "email_id")
        self.enterContext(patch("frappe.enqueue"))
        # Delivery commits intent in production; the test runner owns transactions.
        self.enterContext(patch.object(frappe.db, "commit"))
        self.transport = self.enterContext(patch("helpdesk.integrations.pramaan_mail.client")).return_value

    def test_accepted_delivery_keeps_actual_message_id_and_never_resends(self):
        from helpdesk.integrations.pramaan_mail import sendmail, deliver
        queued = sendmail(sender=self.address, recipients=unique_email("recipient"), subject="Support", message="Hello")
        self.transport.call.return_value = {"messageId": "<accepted@example.com>", "status": "sent"}
        deliver(queued.name)
        deliver(queued.name)
        saved = frappe.get_doc("Pramaan Outbox", queued.name)
        self.assertEqual(saved.state, "Accepted")
        self.assertEqual(saved.message_id, "<accepted@example.com>")
        self.transport.call.assert_called_once()
        self.assertEqual(self.transport.call.call_args.kwargs["idempotency_key"], saved.idempotency_key)

    def test_uncertain_delivery_never_retries(self):
        from helpdesk.integrations.pramaan_mail import sendmail, deliver
        from helpdesk.pramaan import PramaanError
        queued = sendmail(sender=self.address, recipients=unique_email("recipient"), subject="Support", message="Hello")
        self.transport.call.side_effect = PramaanError(uncertain=True)
        deliver(queued.name)
        deliver(queued.name)
        self.assertEqual(frappe.db.get_value("Pramaan Outbox", queued.name, "state"), "Uncertain")
        self.transport.call.assert_called_once()

    def test_unavailable_delivery_is_visible_on_the_ticket_and_never_resent(self):
        from helpdesk.integrations.pramaan_mail import sendmail, deliver
        from helpdesk.pramaan import PramaanNotAvailable
        from helpdesk.test_utils import make_ticket, get_latest_ticket_communication
        from helpdesk.helpdesk.doctype.hd_ticket.api import get_communications
        ticket = make_ticket()
        from frappe.tests.utils import change_settings
        with change_settings("HD Settings", {"enable_reply_email_via_agent": 1, "skip_email_workflow": 0}):
            ticket.reply_via_agent(message="Fixture reply", to=unique_email("recipient"), from_email={"email_account": self.account, "email_id": self.address})
        communication = get_latest_ticket_communication(ticket.name)
        outbox = frappe.db.get_value("Pramaan Outbox", {"communication": communication.name}, "name")
        self.transport.call.side_effect = PramaanNotAvailable("email.message.send")
        deliver(outbox)
        deliver(outbox)
        self.transport.call.assert_called_once()
        self.assertEqual(frappe.db.get_value("Pramaan Outbox", outbox, "state"), "Failed")
        messages = get_communications(ticket.name)
        self.assertEqual(next(row for row in messages if row.name == communication.name).delivery_message, "Mailbox email is not available yet.")

    def test_automated_mail_queues_the_loop_marker(self):
        from helpdesk.integrations.pramaan_mail import sendmail
        queued = sendmail(sender=self.address, recipients=unique_email("recipient"),
                          subject="We got it", message="Hello", auto_submitted="auto-generated")
        payload = json.loads(frappe.db.get_value("Pramaan Outbox", queued.name, "payload"))
        self.assertEqual(payload["autoSubmitted"], "auto-generated")
        self.transport.call.assert_not_called()

    def test_header_marker_maps_to_the_typed_value(self):
        from helpdesk.integrations.pramaan_mail import sendmail
        queued = sendmail(sender=self.address, recipients=unique_email("recipient"), message="Hello",
                          email_headers={"X-Auto-Generated": "hd-acknowledgement"})
        payload = json.loads(frappe.db.get_value("Pramaan Outbox", queued.name, "payload"))
        self.assertEqual(payload["autoSubmitted"], "auto-generated")

    def test_edited_reply_keeps_thread_parent_and_overrides(self):
        from helpdesk.integrations.pramaan_mail import sendmail
        parent = frappe.get_doc({"doctype": "Communication", "communication_type": "Communication",
                                 "communication_medium": "Email", "sent_or_received": "Received",
                                 "subject": "Printer on fire", "content": "help", "message_id": "<in@example.com>"}).insert()
        recipient = unique_email("edited")
        queued = sendmail(sender=self.address, recipients=recipient, subject="Printer, actually",
                          message="Now fixed", in_reply_to=parent.name)
        row = frappe.db.get_value("Pramaan Outbox", queued.name, ["capability", "payload"], as_dict=True)
        self.assertEqual(row.capability, "email.message.reply")
        payload = json.loads(row.payload)
        self.assertEqual(payload["messageId"], "<in@example.com>")
        self.assertEqual(payload["to"], [recipient])
        self.assertEqual(payload["subject"], "Printer, actually")
        self.assertNotIn("autoSubmitted", payload)

    def test_reply_without_accepted_parent_is_refused_before_queue(self):
        from helpdesk.integrations.pramaan_mail import sendmail
        parent = frappe.get_doc({"doctype": "Communication", "communication_type": "Communication",
                                 "communication_medium": "Email", "sent_or_received": "Received",
                                 "subject": "No id yet", "content": "portal reply"}).insert()
        before = frappe.db.count("Pramaan Outbox")
        with self.assertRaises(frappe.ValidationError):
            sendmail(sender=self.address, recipients=unique_email("recipient"),
                     message="Hello", in_reply_to=parent.name)
        self.assertEqual(frappe.db.count("Pramaan Outbox"), before)
        self.transport.call.assert_not_called()


class TestDefaultSender(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.enterContext(patch("frappe.enqueue"))
        self.enterContext(patch.object(frappe.db, "commit"))
        self.transport = self.enterContext(patch("helpdesk.integrations.pramaan_mail.client")).return_value
        self.enterContext(patch("helpdesk.integrations.pramaan_mail.sender_account",
                                return_value="Pramaan Helpdesk <noreply@updates.pramaan.one>"))

    def queue(self, **kwargs):
        from helpdesk.integrations.pramaan_mail import sendmail
        return sendmail(recipients=unique_email("recipient"), subject="Support", message="Hello", **kwargs)

    def test_default_send_uses_shared_sender_and_accepts_reference_without_inventing_message_id(self):
        from helpdesk.integrations.pramaan_mail import deliver
        queued = self.queue()
        self.transport.call.return_value = {"status": "sent", "ref": "mail-reference"}
        deliver(queued.name)
        deliver(queued.name)
        saved = frappe.get_doc("Pramaan Outbox", queued.name)
        self.assertEqual(saved.state, "Accepted")
        self.assertFalse(saved.message_id)
        self.assertEqual(saved.result_ref, "mail-reference")
        self.transport.call.assert_called_once()
        args, kwargs = self.transport.call.call_args
        self.assertEqual(args[0], "email.send")
        self.assertEqual(args[1]["from"], "Pramaan Helpdesk <noreply@updates.pramaan.one>")
        self.assertNotIn("replyTo", args[1])
        self.assertNotIn("attachments", args[1])
        self.assertEqual(kwargs["idempotency_key"], saved.idempotency_key)

    def test_default_send_uploads_attachments_before_send(self):
        from helpdesk.integrations.pramaan_mail import deliver
        queued = self.queue(attachments=[{"fname": "notes.txt", "fcontent": "Notes"}])
        self.transport.upload_file.return_value = {"fileId": "uploaded-document"}
        self.transport.call.return_value = {"status": "sent", "ref": "mail-reference", "rfcMessageId": "<accepted@example.com>"}
        deliver(queued.name)
        self.transport.upload_file.assert_called_once_with(b"Notes", "text/plain")
        self.assertEqual(self.transport.call.call_args.args[1]["attachments"], [{"fileId": "uploaded-document", "name": "notes.txt"}])
        self.assertEqual(frappe.db.get_value("Pramaan Outbox", queued.name, "message_id"), "<accepted@example.com>")

    def test_default_send_preserves_thread_and_does_not_retry_uncertain_delivery(self):
        from helpdesk.integrations.pramaan_mail import deliver
        from helpdesk.pramaan import PramaanError
        parent = frappe.get_doc({"doctype": "Communication", "communication_type": "Communication",
                                "communication_medium": "Email", "sent_or_received": "Received",
                                "subject": "Support", "content": "Help", "message_id": "<parent@example.com>"}).insert()
        queued = self.queue(in_reply_to=parent.name)
        self.assertEqual(json.loads(frappe.db.get_value("Pramaan Outbox", queued.name, "payload"))["inReplyTo"], parent.message_id)
        self.transport.call.side_effect = PramaanError(uncertain=True)
        deliver(queued.name)
        deliver(queued.name)
        self.assertEqual(frappe.db.get_value("Pramaan Outbox", queued.name, "state"), "Uncertain")
        self.transport.call.assert_called_once()


class TestCallbacks(IntegrationTestCase):
    def test_callback_uses_saved_action_key_and_never_redials(self):
        from uuid import uuid4
        from frappe.tests.utils import change_settings
        from helpdesk.api.capabilities import start_callback
        from helpdesk.test_utils import make_ticket
        frappe.set_user("Administrator")
        ticket = make_ticket()
        frappe.db.set_value("User", "Administrator", "pramaan_callback_number", "+12025550123")
        request_id = str(uuid4())
        with change_settings("HD Settings", {"pramaan_calling_number": "+12025550124"}), patch.object(frappe.db, "commit"), patch("helpdesk.api.capabilities.client") as factory:
            factory.return_value.run.return_value = {"job_id": "fake-job", "status": "running"}
            first = start_callback(ticket.name, "+12025550125", request_id)
            second = start_callback(ticket.name, "+12025550125", request_id)
        self.assertEqual(first, second)
        factory.return_value.run.assert_called_once()
        self.assertEqual(factory.return_value.run.call_args.kwargs["idempotency_key"], request_id)
        self.assertEqual(frappe.db.get_value("Pramaan Call", first["name"], "state"), "Running")
        self.assertEqual(factory.return_value.run.call_args.args[1]["maxDurationSeconds"], 300)

    def test_uncertain_callback_is_saved_before_error_returns(self):
        from uuid import uuid4
        from frappe.tests.utils import change_settings
        from helpdesk.api.capabilities import start_callback
        from helpdesk.pramaan import PramaanError
        from helpdesk.test_utils import make_ticket
        frappe.set_user("Administrator")
        ticket = make_ticket()
        frappe.db.set_value("User", "Administrator", "pramaan_callback_number", "+12025550123")
        request_id = str(uuid4())
        with change_settings("HD Settings", {"pramaan_calling_number": "+12025550124"}), patch.object(frappe.db, "commit"), patch("helpdesk.api.capabilities.client") as factory:
            factory.return_value.run.side_effect = PramaanError(uncertain=True)
            with self.assertRaises(PramaanError):
                start_callback(ticket.name, "+12025550125", request_id)
        self.assertEqual(frappe.db.get_value("Pramaan Call", {"request_id": request_id}, "state"), "Uncertain")


class TestUnavailableMailbox(IntegrationTestCase):
    def test_owned_mailbox_connect_and_rental_show_unavailable(self):
        from helpdesk.api.settings.email import provision_mailbox
        from helpdesk.pramaan import PramaanNotAvailable
        from helpdesk.test_utils import make_unavailable_pramaan_client
        from uuid import uuid4
        before = frappe.db.count("Email Account")
        with self.set_user("Administrator"), patch("helpdesk.api.settings.email.client", return_value=make_unavailable_pramaan_client()):
            with self.assertRaises(PramaanNotAvailable) as raised:
                create_email_account(make_email_account_data(None))
            self.assertEqual(str(raised.exception), "Mailbox email is not available yet.")
            with self.assertRaises(PramaanNotAvailable) as raised:
                provision_mailbox("Fixture mailbox", str(uuid4()))
            self.assertEqual(str(raised.exception), "Mailbox email is not available yet.")
        self.assertEqual(frappe.db.count("Email Account"), before)
