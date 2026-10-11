"""Configure the retained local infrastructure and disable external escape paths."""
import frappe


def configure_site():
    install_local_boundaries()
    frappe.db.set_single_value("HD Settings", {
        "brand_name": "Pramaan Helpdesk", "send_acknowledgement_email": 0,
        "enable_email_ticket_feedback": 0, "skip_email_workflow": 1,
        "enable_reply_email_via_agent": 1,
    })
    # Framework email processing creates local users; their welcome mail uses
    # the same Pramaan transport once an outgoing mailbox is configured.
    frappe.db.set_single_value("System Settings", "enable_telemetry", 0)
    frappe.db.set_single_value("Website Settings", {"app_name": "Pramaan Helpdesk", "home_page": "helpdesk"})


def restrict_browser_connections(response):
    import re
    from urllib.parse import urlparse
    host = urlparse(frappe.request.host_url).hostname or "localhost"
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", host):
        host = "localhost"
    port = int(frappe.conf.get("socketio_port", 9000))
    socket_sources = " ".join(f"{scheme}://{host}:{port}" for scheme in ["http", "https", "ws", "wss"])
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
        f"media-src 'self' blob:; connect-src 'self' {socket_sources}; "
        "frame-src 'self' blob:; object-src 'none'; base-uri 'self'"
    )
    return response


def require_local_file(doc, method=None):
    if doc.file_url and not doc.file_url.startswith(("/files/", "/private/files/")):
        frappe.throw("Upload the file here instead of adding an outside file link.")


def disable_telemetry(doc, method=None):
    doc.enable_telemetry = 0


def ignore_outside_sync(*args, **kwargs):
    """Unused inherited sync hooks must not load a vendor client."""
    return None


def install_local_boundaries():
    # These hooks run even with no configured connection. Disable the hooks,
    # rather than retaining unused SDKs just to satisfy their lazy imports.
    from importlib import import_module
    disabled = {
        "frappe.integrations.doctype.google_contacts.google_contacts": [
            "insert_contacts_to_google_contacts", "update_contacts_to_google_contacts", "sync",
        ],
        "frappe.integrations.doctype.google_calendar.google_calendar": [
            "insert_event_in_google_calendar", "update_event_in_google_calendar",
            "delete_event_from_google_calendar", "sync",
        ],
    }
    for name, functions in disabled.items():
        module = import_module(name)
        for function in functions:
            setattr(module, function, ignore_outside_sync)
