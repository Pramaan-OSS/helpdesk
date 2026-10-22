"""Manager view of the supported local sign-in path."""
import frappe
from helpdesk.api.social import MESSAGE


def only_for_managers():
    frappe.only_for(["Agent Manager", "System Manager"])


@frappe.whitelist(methods=["GET", "POST"])
def get_data():
    only_for_managers()
    return {"enabled": False, "message": MESSAGE}


@frappe.whitelist(methods=["PUT", "POST"])
def update_data(enabled: bool = False, **kwargs):
    only_for_managers()
    if frappe.utils.cint(enabled):
        frappe.throw(MESSAGE, frappe.ValidationError)
    frappe.db.set_single_value("HD Settings", "social_sign_in_enabled", 0)
    return {"saved": True}
