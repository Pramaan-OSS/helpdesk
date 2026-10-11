import re
from email import message_from_string

import frappe
from frappe import _
from frappe.core.doctype.communication.communication import Communication
from frappe.email.doctype.email_account.email_account import EmailAccount
from frappe.email.doctype.email_queue.email_queue import EmailQueue
from frappe.email.receive import InboundMail
from frappe.utils import parse_addr


def auto_generated_reason(msg) -> str | None:
    """Why this mail must not become a ticket or a reply, else None.

    A bounce or alert that gets in starts a mail loop: the new-ticket ack,
    the portal CC, and enable_auto_reply all answer it, and it answers back.
    Out-of-office mail (auto-replied) passes on purpose: senders rate-limit
    it, and agents should see it on the ticket.
    """
    if msg.get("X-Auto-Generated"):
        return "X-Auto-Generated"

    # bounce markers first: a DSN usually carries Auto-Submitted too

    # RFC 3464 delivery report -- works even without a Return-Path
    if (
        msg.get_content_type() == "multipart/report"
        and msg.get_param("report-type") == "delivery-status"
    ):
        return "delivery status notification"

    # bounces must use an empty sender (RFC 5321)
    if (msg.get("Return-Path") or "").strip() == "<>":
        return "null return-path"

    # RFC 3834; "no" means a human sent it and may carry parameters
    auto_submitted = (msg.get("Auto-Submitted") or "no").split(";")[0].strip().lower()
    if auto_submitted not in ("no", "auto-replied"):
        return f"Auto-Submitted: {auto_submitted}"

    return None


def _failed_recipient(msg) -> str | None:
    """The address a DSN reports as undeliverable, if it names one."""
    for part in msg.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        for status_block in part.get_payload():
            recipient = status_block.get("Final-Recipient") or ""
            if ";" in recipient:
                return recipient.split(";", 1)[1].strip()
    return None


class CustomInboundMail(InboundMail):
    """
    Extend InboundMail with robust thread stitching for forwarded emails.
       1. Run the standard Frappe parent_communication lookups first (In-Reply-To → Communication, EmailQueue, communication-name fallback)
       2. If still no parent, use the References header from emails, which may contain multiple message IDs in a thread
    """

    def _find_communication_by_message_id(self, msg_id: str):
        """Return a Communication for msg_id, checking both Communication and EmailQueue."""
        # Direct hit: incoming email stored its message_id on Communication
        canonical = msg_id.strip().strip("<>")
        comm = Communication.find_one_by_filters(
            message_id=["in", [canonical, "<" + canonical + ">"]], order_by="creation DESC"
        )
        if comm:
            return comm

        # Outgoing email: message_id lives in EmailQueue, not on Communication
        eq = EmailQueue.find_one_by_filters(message_id=msg_id)
        if eq and eq.communication:
            return Communication.find(eq.communication, ignore_error=True) or None

        return None

    def parent_communication(self):
        # Respect cached result from any prior call on this instance
        if self._parent_communication is not None:
            return self._parent_communication

        # Run the standard Frappe lookup method first. Checks for finding in reply to in Communication then if not found it looks in EmailQueue
        result = super().parent_communication()
        if result:
            return result

        # Pramaan returns full RFC ids, while the framework strips brackets.
        if self.in_reply_to:
            if communication := self._find_communication_by_message_id(self.in_reply_to):
                self._parent_communication = communication
                return communication

        # fallback: use the References header from emails
        references_raw = self.mail.get("References") or ""
        ref_ids = re.findall(r"<([^>]+)>", references_raw)

        for ref_id in reversed(ref_ids):
            communication = self._find_communication_by_message_id(ref_id)
            if communication:
                self._parent_communication = communication
                return self._parent_communication

        self._parent_communication = ""
        return self._parent_communication


class CustomEmailAccount(EmailAccount):
    def handle_bad_emails(self, uid, raw, reason):
        """The framework version only records for IMAP; POP3 and Frappe
        Mail drops deserve the same trace, so this one has no gate."""
        try:
            raw_str = (
                raw.decode("ASCII", "replace")
                if isinstance(raw, bytes)
                else raw.encode(errors="replace").decode()
            )
            message_id = message_from_string(raw_str).get("Message-ID")
        except Exception:
            raw_str = message_id = "can't be parsed"

        frappe.get_doc(
            {
                "doctype": "Unhandled Email",
                "raw": raw_str,
                "uid": uid,
                "reason": reason,
                "message_id": message_id,
                "email_account": self.name,
            }
        ).insert(ignore_permissions=True)
        # keep the record even if a later mail in this batch fails
        frappe.db.commit()  # nosemgrep

    def is_parked(self, message_id: str | None) -> bool:
        """A mail without a Message-ID cannot be matched, so it is parked again."""
        return bool(
            message_id
            and frappe.db.exists(
                "Unhandled Email",
                {"email_account": self.name, "message_id": message_id},
            )
        )

    def notify_ticket_of_parked_mail(self, message, msg, reason):
        """Parked mail never shows on the ticket, so leave a comment
        there -- agents must know their reply bounced."""
        communication = CustomInboundMail(message, self).parent_communication()
        if not communication or communication.reference_doctype != "HD Ticket":
            return

        if reason.startswith("Auto-Submitted"):
            sender = parse_addr(msg.get("From") or "")[1]
            content = _("Auto-reply received from {0}.").format(
                sender or _("the customer")
            )
        else:
            recipient = _failed_recipient(msg)
            content = (
                _(
                    "Delivery failed: the reply to this ticket could not be delivered to {0}."
                ).format(recipient)
                if recipient
                else _(
                    "Delivery failed: the reply to this ticket could not be delivered."
                )
            )

        ticket = frappe.get_doc("HD Ticket", communication.reference_name)
        # a system note, not the pulling user's
        ticket.add_comment("Comment", content, comment_email="Administrator")

    def validate(self):
        from frappe.utils import validate_email_address
        validate_email_address(self.email_id, True)
        # These records hold owned Pramaan mailbox addresses, never credentials.
        self.service = ""
        self.auth_method = "Basic"
        self.password = None
        self.api_key = None
        self.api_secret = None
        self.frappe_mail_site = None
        self.email_server = None
        self.smtp_server = None
        self.use_imap = 0
        self.track_email_status = 0
        self.append_emails_to_sent_folder = 0
        self.append_to = "HD Ticket"

    def get_smtp_server(self):
        return DisabledMailTransport()

    def get_frappe_mail_client(self):
        from helpdesk.pramaan import CapabilityUnavailable
        raise CapabilityUnavailable("automated_threaded_email")

    def get_incoming_server(self, **kwargs):
        from helpdesk.pramaan import PramaanError
        raise PramaanError("unsupported_transport")

    def get_inbound_mails(self) -> list[InboundMail]:
        import base64
        from helpdesk.integrations.pramaan_mail import client
        if not self.enable_incoming:
            return []
        mails = []
        inputs = {"inbox": self.email_id, "limit": 50}
        cursor = self.get("pramaan_inbound_cursor")
        if cursor:
            inputs["cursor"] = cursor
        page = client().call("email.messages.list", inputs)
        for row in page.get("results", []):
            message_id = row.get("messageId")
            if not message_id or frappe.db.exists("Communication", {"message_id": ["in", [message_id, message_id.strip("<>")]]}):
                continue
            if self.is_parked(message_id):
                continue
            raw = client().call("email.message.raw.get", {"inbox": self.email_id, "messageId": message_id})
            content = base64.b64decode(raw["content"], validate=True)
            msg = message_from_string(content.decode("utf-8", "replace"))
            # Never re-import our own outbound messages as customer replies.
            if parse_addr(msg.get("From", ""))[1].lower() == self.email_id.lower():
                continue
            if reason := auto_generated_reason(msg):
                self.handle_bad_emails(message_id, content, reason)
                self.notify_ticket_of_parked_mail(content, msg, reason)
                continue
            mails.append(CustomInboundMail(content, self, message_id, None, "HD Ticket"))
        # Advancing before processing can lose mail after a worker crash. Receive
        # persists this cursor only after every message in the batch was processed.
        self._next_pramaan_cursor = page.get("nextCursor") or ""
        return mails

    def receive(self):
        mails = self.get_inbound_mails()
        for mail in mails:
            mail.process()
            frappe.db.commit()
        self.db_set("pramaan_inbound_cursor", self._next_pramaan_cursor, update_modified=False)


class DisabledMailTransport:
    """An inert compatibility handle; no socket or SMTP object is created."""

    def quit(self):
        return None

    @property
    def session(self):
        from helpdesk.pramaan import PramaanError
        raise PramaanError("unsupported_transport")
