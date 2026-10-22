"""Password sign-in remains local; external authorization start is unavailable."""
import frappe

MESSAGE = "Single sign-in is not available yet. Use password sign-in."


@frappe.whitelist(allow_guest=True, methods=["GET"])
def status():
    return {"enabled": False}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def start():
    frappe.throw(MESSAGE, frappe.ValidationError)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def callback(code: str = "", state: str = "", error: str = "", redirect_to: str = ""):
    # Retire old callback links without exchanging a code or opening a session.
    frappe.local.flags.redirect_location = "/login?social=unavailable"
    raise frappe.Redirect
