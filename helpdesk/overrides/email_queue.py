"""Block the framework SMTP path, including mail queued before migration."""
from email import message_from_string

import frappe
from frappe.email.doctype.email_queue.email_queue import EmailQueue
from helpdesk.integrations.pramaan_mail import sendmail
from helpdesk.pramaan import CapabilityUnavailable


class PramaanEmailQueue(EmailQueue):
    def send(self, **kwargs):
        if not self.can_send_now() and not kwargs.get("force_send"):
            return
        if self.get("pramaan_outbox"):
            return
        parsed = message_from_string(self.message)
        if parsed.get("X-Auto-Generated") or parsed.get("Auto-Submitted") or parsed.get("In-Reply-To"):
            self.db_set({"status": "Error", "error": "This email format is not available yet."})
            return
        if parsed.is_multipart():
            self.db_set({"status": "Error", "error": "Recreate this queued email in the reply editor."})
            return
        content = parsed.get_payload(decode=True) or b""
        result = sendmail(sender=self.sender, recipients=[r.recipient for r in self.recipients if not r.is_mail_sent()],
                          subject=parsed.get("Subject", "Message"), message=content.decode(parsed.get_content_charset() or "utf-8", "replace"),
                          communication=self.communication)
        self.db_set({"pramaan_outbox": result.name, "status": "Sending"})
