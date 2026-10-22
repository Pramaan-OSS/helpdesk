import frappe
from helpdesk.pramaan import PramaanClient

no_cache = 1


def get_context(context):
    context.pramaan_configured = PramaanClient().configured
    if frappe.session.user != "Guest":
        frappe.local.flags.redirect_location = "/helpdesk"
        raise frappe.Redirect
    return context
