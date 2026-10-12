"""Manager settings for social sign-in; secrets stay with the platform."""
import frappe
from frappe import _

def only_for_managers():
    frappe.only_for(["Agent Manager", "System Manager"])


@frappe.whitelist(methods=["GET", "POST"])
def get_data():
    only_for_managers()
    values = frappe._dict(frappe.db.get_singles_dict("HD Settings", cast=True))
    return {
        "enabled": bool(values.get("social_sign_in_enabled")),
        "providerKey": values.get("social_provider_key") or "",
        "clientId": values.get("social_client_id") or "",
        "authorizeUrl": values.get("social_authorize_url") or "",
        "scope": values.get("social_scope") or "openid email profile",
        "usePkce": bool(values.get("social_use_pkce")),
    }


@frappe.whitelist(methods=["PUT", "POST"])
def update_data(enabled: bool, providerKey: str = "", clientId: str = "",
                authorizeUrl: str = "", scope: str = "", usePkce: bool = True):
    only_for_managers()
    providerKey = (providerKey or "").strip()
    clientId = (clientId or "").strip()
    authorizeUrl = (authorizeUrl or "").strip()
    if enabled:
        import re
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", providerKey):
            frappe.throw(_("Enter the connected sign-in account's key."), frappe.ValidationError)
        if not clientId or not authorizeUrl.startswith("https://"):
            frappe.throw(_("A client id and an https authorization endpoint are required."), frappe.ValidationError)
    frappe.db.set_single_value("HD Settings", {
        "social_sign_in_enabled": int(enabled),
        "social_provider_key": providerKey,
        "social_client_id": clientId,
        "social_authorize_url": authorizeUrl,
        "social_scope": (scope or "openid email profile").strip(),
        "social_use_pkce": int(usePkce),
    })
    return {"saved": True}
