"""Explicit recovery for an older local development site's initial account."""
from pathlib import Path
import secrets
import frappe
from frappe.utils.password import update_password


def reset():
    password = secrets.token_urlsafe(24)
    update_password("Administrator", password)
    frappe.db.commit()
    target = Path(frappe.get_site_path()).resolve().parent.parent / ".local-admin-password"
    target.write_text(password + "\n")
    target.chmod(0o600)
    print("Administrator password replaced. Its private file is .runtime/bench/.local-admin-password.")
