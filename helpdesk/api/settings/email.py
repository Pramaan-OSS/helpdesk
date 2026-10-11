"""Mailbox configuration through Pramaan; no vendor credentials are accepted."""
import frappe
from helpdesk.integrations.pramaan_mail import client


@frappe.whitelist()
def list_mailboxes():
    frappe.only_for(["System Manager", "Agent Manager"])
    return frappe.get_all("Email Account", fields=["name", "email_id", "enable_incoming", "enable_outgoing", "default_outgoing"])


@frappe.whitelist(methods=["POST"])
def create_email_account(data: dict):
    frappe.only_for(["System Manager", "Agent Manager"])
    # Caller cannot submit vendor hosts or credentials through this endpoint.
    forbidden = {"password", "api_key", "api_secret", "email_server", "smtp_server", "service", "frappe_mail_site"}
    if forbidden.intersection(data):
        frappe.throw("Only Pramaan mailbox settings are supported.")
    if not data.get("email_id"):
        frappe.throw("Enter an owned mailbox address.")
    from frappe.utils import validate_email_address
    validate_email_address(data["email_id"], True)
    # Verify ownership with Pramaan before saving a local mailbox address.
    client().call("email.inbox.get", {"address": data["email_id"]})
    account = frappe.get_doc({"doctype": "Email Account", "email_id": data["email_id"],
                             "email_account_name": data.get("email_account_name") or data["email_id"],
                             "enable_incoming": int(bool(data.get("enable_incoming", 1))), "enable_outgoing": int(bool(data.get("enable_outgoing", 1))), "default_outgoing": not frappe.db.exists("Email Account", {"default_outgoing": 1}),
                             "append_to": "HD Ticket"}).insert()
    frappe.db.set_single_value("HD Settings", "skip_email_workflow", 0)
    return account.name


@frappe.whitelist(methods=["POST"])
def provision_mailbox(display_name: str, request_id: str):
    frappe.only_for(["System Manager", "Agent Manager"])
    # Monthly mailbox rental: invoked only by an explicit product action.
    from uuid import UUID
    UUID(request_id)
    result = client().call("email.inbox.create", {"displayName": display_name}, idempotency_key=request_id, approved_by=frappe.session.user)
    inbox = client().call("email.inbox.get", {"ref": result["ref"]})
    return {"email": inbox.get("address") or inbox.get("email") or inbox.get("inbox")}
