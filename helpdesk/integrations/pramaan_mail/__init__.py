"""Durable mail delivery through the application's single Pramaan client."""
import base64
import json
import mimetypes
import uuid
from email.utils import getaddresses

import frappe
from frappe import _
from helpdesk.pramaan import CapabilityUnavailable, PramaanClient, PramaanError


def client():
    return PramaanClient()


def addresses(value):
    values = value if isinstance(value, (list, tuple)) else [value or ""]
    return list(dict.fromkeys(address for _, address in getaddresses(values) if address))


def sender_account(sender=None):
    sender = addresses(sender)
    filters = {"enable_outgoing": 1}
    if sender:
        filters["email_id"] = sender[0]
    else:
        filters["default_outgoing"] = 1
    account = frappe.db.get_value("Email Account", filters, ["name", "email_id"], as_dict=True)
    if not account:
        frappe.throw(_("Choose an outgoing mailbox in Email Accounts."))
    return account.email_id


def sendmail(recipients=None, sender=None, subject=None, message=None, **kwargs):
    """Queue a supported send atomically; the worker runs only after commit."""
    if kwargs.get("email_headers") or kwargs.get("auto_submitted"):
        raise CapabilityUnavailable("automated_threaded_email")
    inbox = sender_account(sender)
    payload = {"from": inbox, "to": addresses(recipients), "cc": addresses(kwargs.get("cc")),
               "bcc": addresses(kwargs.get("bcc")), "subject": subject or "Message"}
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
    capability = "email.message.send"
    parent = kwargs.get("in_reply_to")
    if parent:
        comm = frappe.get_doc("Communication", parent)
        comm.check_permission("read")
        # Edited recipients/subject cannot be represented by the current reply contract.
        normalized = lambda value: (value or "").removeprefix("Re: ").strip()
        expected = addresses(comm.sender if comm.sent_or_received == "Received" else comm.recipients)
        if set(expected) != set(payload["to"]) or normalized(comm.subject) != normalized(payload["subject"]):
            raise CapabilityUnavailable("automated_threaded_email")
        if not comm.message_id:
            frappe.throw(_("The previous email has not been accepted yet. Wait before replying."))
        capability = "email.message.reply"
        payload = {"inbox": inbox, "messageId": comm.message_id, "html": payload["html"],
                   "cc": payload["cc"], "bcc": payload["bcc"], "attachments": attachments}
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
        result = client().call(outbox.capability, json.loads(outbox.payload),
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
    message_id = result.get("messageId")
    if not message_id:
        outbox.db_set({"state": "Uncertain", "error": "Delivery could not be confirmed. Check before trying again."})
        finish_legacy_queue(outbox, "Error")
        frappe.db.commit()
        return
    outbox.db_set({"state": "Accepted", "message_id": message_id, "result_ref": result.get("ref", ""), "error": ""})
    if outbox.communication:
        frappe.db.set_value("Communication", outbox.communication, {"message_id": message_id, "delivery_status": "Sent"})
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
