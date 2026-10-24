"""Route signed-in desk visitors to the template's workspace."""
import frappe


def redirect_to_helpdesk(context=None):
    request = frappe.local.request
    if request.method not in {"GET", "HEAD"} or frappe.session.user == "Guest":
        return
    if request.path == "/desk" or request.path.startswith("/desk/"):
        frappe.local.flags.redirect_location = "/helpdesk"
        raise frappe.Redirect(302)
