import frappe
from frappe.desk.form.assign_to import add as add_assign

AUTHOR_EMAIl = "john@example.com"
AUTHOR_NAME = "John Doe"
CONTENT = """<p>Welcome to Pramaan Helpdesk, {{ first_name }}.</p>
<p>This sample ticket shows your team's workspace. Reply after connecting an owned mailbox, or add a private comment for your team.</p>
<p>Use Settings to invite agents and configure response times. Add articles to your knowledge base so customers can find answers.</p>"""


def create_welcome_ticket():
    create_contact()
    create_ticket()


def create_ticket():
    if frappe.db.count("HD Ticket"):
        return

    # Render template with the current user's information
    user_doc = frappe.get_doc("User", frappe.session.user)
    if (user_doc.name or "").strip().lower() == "administrator":
        first_name = "there"
    else:
        first_name = (user_doc.first_name or "").strip() or "there"
    rendered_content = frappe.render_template(
        CONTENT,
        {
            "first_name": first_name,
        },
        safe_render=True,
    )

    d = frappe.new_doc("HD Ticket")
    d.subject = "Welcome to Helpdesk"
    d.description = rendered_content
    d.raised_by = AUTHOR_EMAIl
    d.contact = AUTHOR_NAME
    d.via_customer_portal = True
    d.insert()
    add_assign(
        {
            "doctype": "HD Ticket",
            "name": d.name,
            "assign_to": ["Administrator"],
        }
    )


def create_contact():
    frappe.get_doc(
        {
            "doctype": "Contact",
            "first_name": AUTHOR_NAME,
            "email_ids": [{"email_id": AUTHOR_EMAIl, "is_primary": 1}],
        }
    ).insert()
