"""Production application for this installation's one local site."""
import os
import frappe.app

# Match the explicit --site used by the development server, independent of Host.
frappe.app._site = os.environ.get("HELPDESK_SITE_NAME", "helpdesk.localhost")
application = frappe.app.application_with_statics()
