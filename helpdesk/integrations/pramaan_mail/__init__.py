"""Durable mail delivery through the application's single Pramaan client."""
import base64
import json
import mimetypes
import uuid
from email.utils import getaddresses

import frappe
from frappe import _
from helpdesk.pramaan import PramaanClient, PramaanError, email_is_trackable


def client():
    return PramaanClient()


def requires_pramaan(function):
    """Reject missing configuration before validation or any durable action intent."""
    from functools import wraps

    @wraps(function)
    def checked(*args, **kwargs):
        # Use the endpoint's boundary so isolated tests can supply their fake.
        function.__globals__["client"]().require_configured()
        return function(*args, **kwargs)
    return checked


def addresses(value):
    values = value if isinstance(value, (list, tuple)) else [value or ""]
    return list(dict.fromkeys(address for _, address in getaddresses(values) if address))


def default_sender():
    return frappe.conf.get("pramaan_email_sender") or "Pramaan Helpdesk <noreply@updates.pramaan.one>"


def sender_account(sender=None):
    sender = addresses(sender)
    filters = {"enable_outgoing": 1}
    if sender:
        filters["email_id"] = sender[0]
    else:
        filters["default_outgoing"] = 1
    account = frappe.db.get_value("Email Account", filters, ["name", "email_id"], as_dict=True)
    if not account:
        return default_sender()
    return account.email_id


AUTO_SUBMITTED = ("auto-generated", "auto-replied")


def marker_from(value):
    """A typed Auto-Submitted value from a caller header, else None.

    The platform only accepts "auto-generated" or "auto-replied"; an unknown
    app marker still marks the mail so recipients can suppress reply loops.
    """
    if value is True:
        return "auto-generated"
    raw = (value or "").split(";")[0].strip().lower()
    if not raw or raw == "no":
        return None
    return raw if raw in AUTO_SUBMITTED else "auto-generated"


def sendmail(recipients=None, sender=None, subject=None, message=None, **kwargs):
    """Queue a supported send atomically; the worker runs only after commit."""
    auto_submitted = marker_from(kwargs.get("auto_submitted"))
    if not auto_submitted:
        auto_submitted = marker_from((kwargs.get("email_headers") or {}).get(
            "X-Auto-Generated") or (kwargs.get("email_headers") or {}).get("Auto-Submitted"))
    inbox = sender_account(sender)
    payload = {"from": inbox, "to": addresses(recipients), "cc": addresses(kwargs.get("cc")),
               "bcc": addresses(kwargs.get("bcc")), "subject": subject or "Message"}
    if auto_submitted:
        payload["autoSubmitted"] = auto_submitted
    if kwargs.get("template"):
        message = frappe.render_template("templates/emails/" + kwargs["template"] + ".html", kwargs.get("args") or {})
    payload["html"] = message or kwargs.get("content") or ""
    if kwargs.get("as_markdown"):
        from frappe.utils import markdown
        payload["html"] = markdown(payload["html"])
    if kwargs.get("reply_to"):
        payload["replyTo"] = addresses(kwargs["reply_to"])[0]
    attachments = []
    for attachment in kwargs.get("attachments") or []:
        if attachment.get("file_url"):
            file_doc = frappe.get_doc("File", {"file_url": attachment["file_url"]})
            file_doc.check_permission("read")
            content = file_doc.get_content()
            filename = file_doc.file_name
        else:
            content = attachment.get("fcontent") or attachment.get("content") or b""
            filename = attachment.get("fname") or attachment.get("filename") or "attachment"
        if isinstance(content, str):
            content = content.encode()
        attachments.append({"filename": filename, "content": base64.b64encode(content).decode(),
                            "mimeType": mimetypes.guess_type(filename)[0] or "application/octet-stream"})
    payload["attachments"] = attachments
    shared = inbox == default_sender()
    if shared and (len(attachments) > 10 or sum(len(base64.b64decode(a["content"])) for a in attachments) > 6 * 1024 * 1024):
        frappe.throw("Email attachments must total at most 6 MB across 10 files.")
    capability = "email.send" if shared else "email.message.send"
    parent = kwargs.get("in_reply_to")
    if parent:
        comm = frappe.get_doc("Communication", parent)
        comm.check_permission("read")
        if not comm.message_id:
            frappe.throw(_("The previous email has not been accepted yet. Wait before replying."))
        if shared:
            import re
            if not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", comm.message_id):
                frappe.throw("The previous email has no confirmed thread identifier. Start a new message instead.")
            payload["inReplyTo"] = comm.message_id
        else:
            capability = "email.message.reply"
            # Keep edited recipients and subject on the owned-mailbox reply.
            payload = {"inbox": inbox, "messageId": comm.message_id, "html": payload["html"],
                       "cc": payload["cc"], "bcc": payload["bcc"], "attachments": attachments}
            if addresses(recipients):
                payload["to"] = addresses(recipients)
            if subject:
                payload["subject"] = subject
            if auto_submitted:
                payload["autoSubmitted"] = auto_submitted
            if kwargs.get("reply_to"):
                payload["replyTo"] = addresses(kwargs["reply_to"])[0]
    if not (addresses(recipients) or payload.get("cc") or payload.get("bcc")):
        frappe.throw(_("Choose at least one recipient."))
    outbox = frappe.get_doc({"doctype": "Pramaan Outbox", "capability": capability,
                            "payload": json.dumps(payload), "idempotency_key": str(uuid.uuid4()),
                            "state": "Pending", "communication": kwargs.get("communication"),
                            "requested_by": frappe.session.user}).insert(ignore_permissions=True)
    frappe.enqueue(deliver, name=outbox.name, enqueue_after_commit=True)
    return frappe._dict(name=outbox.name, messageId=None, status="queued")


def deliver(name):
    """Persist intent before sending; uncertain outcomes never auto-retry."""
    outbox = frappe.get_doc("Pramaan Outbox", name)
    # Lock also stops a scheduler retry racing the initial worker.
    frappe.db.sql("select name from `tabPramaan Outbox` where name=%s for update", name)
    outbox.reload()
    if outbox.state != "Pending":
        return
    outbox.db_set("state", "Sending")
    frappe.db.commit()
    try:
        payload = json.loads(outbox.payload)
        if outbox.capability == "email.send":
            uploaded = []
            for attachment in payload.pop("attachments", []):
                file = client().upload_file(base64.b64decode(attachment["content"]), attachment["mimeType"])
                uploaded.append({"fileId": file["fileId"], "name": attachment["filename"]})
            if uploaded:
                payload["attachments"] = uploaded
            for key in ("cc", "bcc"):
                if not payload.get(key):
                    payload.pop(key, None)
        result = client().call(outbox.capability, payload,
                               idempotency_key=outbox.idempotency_key, approved_by=outbox.requested_by)
    except PramaanError as error:
        outbox.db_set({"state": "Uncertain" if error.uncertain else "Failed", "error": str(error)})
        if outbox.communication:
            frappe.db.set_value("Communication", outbox.communication, "delivery_status", "Error")
        finish_legacy_queue(outbox, "Error")
        frappe.db.commit()
        return
    except Exception:
        outbox.db_set({"state": "Uncertain", "error": "Delivery could not be confirmed. Check before trying again."})
        finish_legacy_queue(outbox, "Error")
        frappe.db.commit()
        return
    # Only a real accepted message id can become another reply's parent.
    shared = outbox.capability == "email.send"
    message_id = result.get("rfcMessageId") if shared else result.get("messageId")
    accepted = bool(message_id) or (shared and result.get("ref") and result.get("status") in {"sent", "queued"})
    if not accepted:
        outbox.db_set({"state": "Uncertain", "error": "Delivery could not be confirmed. Check before trying again."})
        finish_legacy_queue(outbox, "Error")
        frappe.db.commit()
        return
    outbox.db_set({"state": "Accepted", "message_id": message_id or "", "result_ref": result.get("ref", ""), "error": "",
                   "delivery_tracking": "Enabled" if email_is_trackable(outbox.capability, result) else "Disabled"})
    if outbox.communication:
        frappe.db.set_value("Communication", outbox.communication, {"message_id": message_id or "", "delivery_status": "Sent"})
    finish_legacy_queue(outbox, "Sent")
    frappe.db.commit()


def finish_legacy_queue(outbox, status):
    for name in frappe.get_all("Email Queue", filters={"pramaan_outbox": outbox.name}, pluck="name"):
        frappe.db.set_value("Email Queue", name, "status", status)


def drain():
    from frappe.utils import add_to_date, now_datetime
    stale = add_to_date(now_datetime(), minutes=-10)
    for name in frappe.get_all("Pramaan Outbox", filters={"state": "Sending", "modified": ("<", stale)}, pluck="name"):
        frappe.db.set_value("Pramaan Outbox", name, {"state": "Uncertain", "error": "Delivery was interrupted. Check before trying again."})
    frappe.db.commit()
    for name in frappe.get_all("Pramaan Outbox", filters={"state": "Pending"}, pluck="name", limit_page_length=50):
        deliver(name)


def install_transport(**kwargs):
    """Framework invites and password mail must use the same transport."""
    import frappe.email
    from helpdesk.integrations.configuration import install_local_boundaries
    install_local_boundaries()
    frappe.sendmail = sendmail
    frappe.email.sendmail = sendmail


def communication_tracking(ticket):
    """Return tracking visibility only after the caller checks ticket access."""
    communications = frappe.get_all("Communication", filters={"reference_doctype": "HD Ticket", "reference_name": ticket}, fields=["name", "email_account"])
    result = {row.name: bool(row.email_account) for row in communications}
    if not result:
        return result
    for row in frappe.get_all("Pramaan Outbox", filters={"communication": ["in", list(result)]}, fields=["communication", "capability", "delivery_tracking"], order_by="creation asc"):
        result[row.communication] = email_is_trackable(row.capability, stored=row.delivery_tracking)
    return result
