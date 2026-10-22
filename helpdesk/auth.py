import json

import frappe

ALLOWED_PATHS = [
    "/api/method/ping",
    "/api/method/frappe.desk.form.activity.get_activity_timeline",
    "/api/method/frappe.desk.form.assign_to.add",
    "/api/method/frappe.desk.form.assign_to.add_multiple",
    "/api/method/frappe.desk.doctype.bulk_update.bulk_update.submit_cancel_or_update_docs",
    "/api/method/frappe.desk.form.activity.get_more_email_activities",
    "/api/method/frappe.desk.form.activity.get_more_milestone_activities",
    "/api/method/frappe.translate.get_boot_translations",
    "/api/method/frappe.apps.get_apps",
    "/api/method/login",
    "/api/method/logout",
    "/api/method/frappe.core.doctype.user.user.sign_up",
    "/api/method/frappe.core.doctype.user.user.verify_password",
    "/api/method/frappe.core.doctype.user.user.get_timezones",
    "/api/method/frappe.core.doctype.user.user.test_password_strength",
    "/api/method/frappe.core.doctype.communication.email.mark_email_as_seen",
    "/api/method/frappe.realtime.get_user_info",
    "/api/method/frappe.realtime.can_subscribe_doc",
    "/api/method/frappe.realtime.can_subscribe_doctype",
    "/api/method/frappe.realtime.has_permission",
    "/api/method/frappe.integrations.oauth2.authorize",
    "/api/method/frappe.integrations.oauth2.approve",
    "/api/method/frappe.integrations.oauth2.get_token",
    "/api/method/frappe.www.login.send_login_link",
    "/api/method/frappe.www.login.login_via_token",
    "/api/method/frappe.www.login.login_via_key",
    "/api/method/frappe.integrations.oauth2.openid_profile",
    "/api/method/upload_file",
    "/api/method/frappe.search.web_search",
    "/api/method/frappe.email.queue.unsubscribe",
    "/api/method/frappe.website.doctype.web_form.web_form.accept",
    "/api/method/frappe.core.doctype.user.user.test_password_strength",
    "/api/method/frappe.core.doctype.user.user.update_password",
    "/api/method/frappe.client.get_value",
    "/api/method/frappe.client.get_count",
    "/api/method/frappe.client.get",
    "/api/method/frappe.client.insert",
    "/api/method/frappe.client.set_value",
    "/api/method/frappe.client.delete",
    "/api/method/frappe.client.get_list",
    "/api/method/frappe.client.rename_doc",
    "/api/method/frappe.onboarding.get_onboarding_status",
    "/api/method/frappe.onboarding.update_user_onboarding_status",
    "/api/method/frappe.utils.print_format.download_pdf",
    "/api/method/frappe.desk.search.search_link",
    "/api/method/frappe.core.doctype.communication.email.make",
    "/api/method/frappe.core.doctype.user.user.reset_password",
    "/api/method/frappe.desk.form.load.getdoctype",
    "/api/method/run_doc_method",
    "/api/method/frappe.core.api.user_invitation.accept_invitation",
    "/api/method/frappe.core.api.user_invitation.get_pending_invitations",
    "/api/method/frappe.core.api.user_invitation.cancel_invitation",
    "/api/method/frappe.core.api.user_invitation.invite_by_email",
    "/api/method/frappe.core.api.user_invitation.resend_invitation",
    "/api/method/frappe.desk.reportview.export_query",
    "/api/method/frappe.desk.reportview.delete_items",
    "/api/method/frappe.desk.reportview.get_count",
    "/api/method/frappe.desk.doctype.notification_log.notification_log.mark_as_read",
    "/api/method/frappe.desk.doctype.notification_log.notification_log.mark_all_as_read",
    "/api/method/frappe.desk.doctype.notification_log.notification_log.trigger_indicator_hide",
]

WILDCARD_PATHS = [
]


def authenticate():
    # Outside-service entrypoints are blocked for every account, including admins.
    path = f"/api/method/{frappe.form_dict.cmd}" if frappe.form_dict.cmd else frappe.request.path
    retired_api = path.startswith("/api/method/") and (
        path.startswith(("/api/method/telephony.", "/api/method/telephony/"))
        or any(value in path for value in ("login_via_", "oauth2_logins", ".telephony.", "frappe.www.login.custom"))
    )
    if (path.startswith("/api/") and "frappe.integrations." in path and path not in ALLOWED_PATHS) or retired_api:
        frappe.throw("This connection is not available yet.", frappe.PermissionError)
    restricted = {"Email Domain", "Connected App", "Social Login Key", "Server Script", "Webhook", "SMS Settings", "Notification", "Auto Email Report"}
    doctype = frappe.form_dict.get("doctype") or frappe.form_dict.get("dt")
    if not doctype and (frappe.form_dict.get("doc") or frappe.form_dict.get("docs")):
        try:
            raw_doc = frappe.form_dict.get("doc") or frappe.form_dict.get("docs")
            doc = json.loads(raw_doc) if isinstance(raw_doc, str) else raw_doc
            doctype = doc.get("doctype")
        except (ValueError, AttributeError):
            frappe.throw("Invalid document.")
    if path == "/api/method/run_doc_method":
        # Document methods can otherwise activate inherited outside integrations.
        if not doctype and frappe.form_dict.get("dt"):
            doctype = frappe.form_dict.dt
        if not doctype or not (doctype.startswith("HD ") or doctype in {"Contact", "Assignment Rule"}):
            frappe.throw("This document action is not available.", frappe.PermissionError)
    local_auth = {"OAuth Client", "OAuth Bearer Token", "OAuth Authorization Code", "OAuth Provider Settings"}
    outside_settings = doctype and doctype not in local_auth and frappe.db.get_value("DocType", doctype, "module") == "Integrations"
    if outside_settings or doctype in restricted or any("/api/resource/" + value in path or "/api/resource/" + value.replace(" ", "%20") in path for value in restricted):
        frappe.throw("Configure connections in Pramaan settings.", frappe.PermissionError)
    if not path.startswith("/api/") or path.startswith("/api/method/helpdesk."):
        return
    if path in ALLOWED_PATHS or any(path.startswith(prefix) for prefix in WILDCARD_PATHS):
        return
    frappe.throw("This endpoint is not available.", frappe.PermissionError)
