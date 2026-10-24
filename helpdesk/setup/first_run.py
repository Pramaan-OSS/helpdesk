"""Finish the framework wizard locally, including the first-agent hook."""
import os

import frappe


def complete():
    if frappe.is_setup_complete():
        return

    from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

    frappe.set_user("Administrator")
    # The framework skips all regional settings unless a country is provided.
    result = setup_complete({
        "language": "English",
        "country": "United States",
        "timezone": os.environ.get("HELPDESK_TIMEZONE", "Etc/UTC"),
        "currency": os.environ.get("HELPDESK_CURRENCY", "USD"),
        "enable_telemetry": "0",
    })
    if result != {"status": "ok"} or not frappe.is_setup_complete():
        raise RuntimeError("Local first-run setup did not complete.")
    if not frappe.db.exists("HD Agent", {"user": "Administrator"}):
        raise RuntimeError("Local first-run setup did not create the Administrator agent.")
    frappe.db.commit()
