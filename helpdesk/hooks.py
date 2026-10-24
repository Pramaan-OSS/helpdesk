app_name = "helpdesk"
app_title = "Pramaan Helpdesk"
app_publisher = "Pramaan"
app_description = "Customer Service Software"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = ""
app_license = "AGPLv3"
required_apps = []
require_type_annotated_api_methods = True

add_to_apps_screen = [
    {
        "name": "helpdesk",
        "logo": "/assets/helpdesk/desk/favicon.svg",
        "title": "Pramaan Helpdesk",
        "route": "/helpdesk",
        "has_permission": "helpdesk.api.permission.has_app_permission",
    }
]



after_install = "helpdesk.setup.install.after_install"
after_migrate = [
    "helpdesk.search.build_index_in_background",
]


# Full Text Search
# ------------------

sqlite_search = ["helpdesk.search_sqlite.HelpdeskSearch"]

scheduler_events = {
    "all": [
        "helpdesk.integrations.pramaan_mail.drain",
        "helpdesk.api.calling.ingest_all",
        "helpdesk.search.build_index_if_not_exists",
        ],
    "daily": [
        "helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.close_tickets_after_n_days"
    ],
    "hourly_long": [
        "helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.update_sla_status_in_ticket"
    ],
}


website_route_rules = [
    {
        "from_route": "/helpdesk/<path:app_path>",
        "to_route": "helpdesk",
    },
]

user_invitation = {
    "allowed_roles": {
        "Agent Manager": [
            "Agent",
            "Agent Manager",
            "HD Customer",
            "HD Customer Manager",
        ],
        "System Manager": [
            "Agent",
            "Agent Manager",
            "System Manager",
            "HD Customer",
            "HD Customer Manager",
        ],
    },
    "after_accept": "helpdesk.helpdesk.hooks.user_invitation.after_accept",
    "extra_invite_params": ["customer", "contact"],
}

doc_events = {
    "System Settings": {"validate": "helpdesk.integrations.configuration.disable_telemetry"},
    "File": {"validate": "helpdesk.integrations.configuration.require_local_file"},
    "Assignment Rule": {
        "on_trash": "helpdesk.extends.assignment_rule.on_assignment_rule_trash",
        "validate": "helpdesk.extends.assignment_rule.on_assignment_rule_validate",
    },
    "Customer": {
        "after_insert": "helpdesk.integrations.erpnext.customer.after_insert",
        "on_update": "helpdesk.integrations.erpnext.customer.on_update",
        "before_rename": "helpdesk.integrations.erpnext.customer.before_rename",
        "after_rename": "helpdesk.integrations.erpnext.customer.after_rename",
        "on_trash": "helpdesk.integrations.erpnext.customer.on_trash",
    },
    "User Permission": {
        "before_validate": "helpdesk.integrations.erpnext.user_permission.before_validate",
        "after_insert": "helpdesk.integrations.erpnext.user_permission.after_insert",
        "on_update": "helpdesk.integrations.erpnext.user_permission.on_update",
        "on_trash": "helpdesk.integrations.erpnext.user_permission.on_trash",
    },
    "DocShare": {
        "before_validate": "helpdesk.integrations.erpnext.doc_share.before_validate",
        "after_insert": "helpdesk.integrations.erpnext.doc_share.after_insert",
        "on_update": "helpdesk.integrations.erpnext.doc_share.on_update",
        "on_trash": "helpdesk.integrations.erpnext.doc_share.on_trash",
    },
    "Notification Log": {
        "before_insert": "helpdesk.extends.notification_log.before_insert",
    },
    "Comment": {
        "before_insert": "helpdesk.extends.comment.before_insert",
        "validate": "helpdesk.extends.comment.validate",
        "on_trash": "helpdesk.extends.comment.on_trash",
    },
}

# For List View
permission_query_conditions = {
    "HD Ticket": "helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.permission_query",
    "HD Saved Reply": "helpdesk.helpdesk.doctype.hd_saved_reply.hd_saved_reply.permission_query",
    "HD Customer": "helpdesk.helpdesk.doctype.hd_customer.hd_customer.permission_query",
}


has_permission = {
    "HD Agent": "helpdesk.helpdesk.doctype.hd_agent.hd_agent.has_permission",
    "HD Ticket": "helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.has_permission",
    "HD Saved Reply": "helpdesk.helpdesk.doctype.hd_saved_reply.hd_saved_reply.has_permission",
    "HD Customer": "helpdesk.helpdesk.doctype.hd_customer.hd_customer.has_permission",
    "Comment": "helpdesk.extends.comment.has_permission",
}

override_whitelisted_methods = {
    "frappe.realtime.has_permission": "helpdesk.overrides.realtime.has_permission",
}


notification_skip_email_types = [
    "Reaction",
    "Ticket Reopened",
]


# DocType Class
# ---------------
# Override standard doctype classes
override_doctype_class = {
    "Notification Log": "helpdesk.overrides.notification_log.PramaanNotificationLog",
    "Email Account": "helpdesk.overrides.email_account.CustomEmailAccount",
    "Email Queue": "helpdesk.overrides.email_queue.PramaanEmailQueue",
    "Assignment Rule": "helpdesk.overrides.assignment_rule.HelpdeskAssignmentRule",
    "User Invitation": "helpdesk.overrides.user_invitation.HelpdeskUserInvitation",
}

ignore_links_on_delete = [
    "HD Notification",
    "HD Ticket Comment",
]

# setup wizard
# setup_wizard_requires = "assets/helpdesk/js/setup_wizard.js"
# setup_wizard_stages = "helpdesk.setup.setup_wizard.get_setup_stages"
setup_wizard_complete = "helpdesk.setup.setup_wizard.setup_complete"


# Testing
# ---------------

before_tests = "helpdesk.test_utils.before_tests"
auth_hooks = ["helpdesk.auth.authenticate"]

before_request = ["helpdesk.integrations.pramaan_mail.install_transport"]
update_website_context = ["helpdesk.desk_redirect.redirect_to_helpdesk"]
before_job = ["helpdesk.integrations.pramaan_mail.install_transport"]

after_request = ["helpdesk.integrations.configuration.restrict_browser_connections"]
