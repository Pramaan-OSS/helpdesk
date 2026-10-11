import frappe
from frappe import _
from frappe.utils import cint, get_system_timezone
from frappe.utils.jinja_globals import is_rtl

from helpdesk.utils import get_agent_name

no_cache = 1


def get_context(context):
    frappe.db.commit()
    context.boot = get_boot()

    return context


@frappe.whitelist(methods=["POST"], allow_guest=True)
def get_context_for_dev():
    if not frappe.conf.developer_mode:
        frappe.throw(_("This method is only meant for developer mode"))
    return get_boot()


def get_boot():
    return frappe._dict(
        {
            "default_route": get_default_route(),
            "site_name": frappe.local.site,
            "read_only_mode": frappe.flags.read_only,
            "csrf_token": frappe.sessions.get_csrf_token(),
            "setup_complete": cint(frappe.get_system_settings("setup_complete")),
            "socketio_port": frappe.conf.get("socketio_port", 9000),
            "session_user": frappe.session.user,
            "agent": get_agent_name(),
            "date_format": frappe.get_system_settings("date_format"),
            "time_format": frappe.get_system_settings("time_format"),
            "default_country": frappe.db.get_default("country"),
            "timezone": {
                "system": get_system_timezone(),
                "user": frappe.db.get_value("User", frappe.session.user, "time_zone")
                or get_system_timezone(),
            },
            "lang": frappe.local.lang,
            "dir": "rtl" if is_rtl() else "ltr",
            "apps": frappe.get_installed_apps(),

        }
    )


def get_default_route():
    return "/helpdesk"
