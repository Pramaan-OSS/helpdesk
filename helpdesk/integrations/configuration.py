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
    sanitise_error_response(response)
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


def sanitise_error_response(response):
    """Keep diagnostics in server logs; all error responses use neutral public text."""
    import json
    import re
    from helpdesk.pramaan import MISSING_KEY_MESSAGE
    if response.status_code < 400:
        return
    fallback = {
        401: "Your session has expired. Sign in again.",
        403: "You do not have permission to open this resource.",
        404: "This page or resource could not be found.",
        422: MISSING_KEY_MESSAGE,
    }.get(response.status_code, "Could not confirm this request. Check its status before trying again.")
    if response.is_json:
        body = response.get_json(silent=True)
        if not isinstance(body, dict):
            body = {}
        message = fallback
        if body.get("exc_type") == "MissingPramaanKey":
            message = MISSING_KEY_MESSAGE
        elif response.status_code < 500:
            # Only application validation messages, never exception strings/traces.
            try:
                entries = json.loads(body.get("_server_messages") or "[]")
                messages = [json.loads(row).get("message", "") if isinstance(row, str) else row.get("message", "") for row in entries]
                safe = [text for text in messages if isinstance(text, str) and not any(token in text for token in ("Traceback", "File \"", "/Users/", "/home/", "frappe", "<"))]
                if safe and not re.search(r"(?:[A-Za-z]:\\|/(?:[^ /\n]+/)+[^\s]+|\bFile [\"\'])", " ".join(safe)):
                    message = " ".join(safe)
            except (TypeError, ValueError, AttributeError):
                pass
        public = {"message": message, "_server_messages": json.dumps([json.dumps({"message": message})])}
        # Retain only stable local types used for permission/session UI behavior.
        if body.get("exc_type") in {"PermissionError", "AuthenticationError", "ValidationError", "RateLimitExceededError", "DoesNotExistError", "TimestampMismatchError", "LinkValidationError", "DuplicateEntryError", "MissingPramaanKey"}:
            public["exc_type"] = body["exc_type"]
        response.set_data(json.dumps(public))
    else:
        response.set_data(f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pramaan Helpdesk</title><body style="font-family:system-ui;margin:4rem auto;max-width:40rem;padding:1rem"><h1>Unable to open this page</h1><p>{fallback}</p><a href="/helpdesk">Return to Helpdesk</a></body></html>')
        response.headers["Content-Type"] = "text/html; charset=utf-8"
