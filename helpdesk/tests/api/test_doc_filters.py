from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.tests.utils import change_settings

from helpdesk.api.doc import (
    get_list_data,
    handle_assigned_on_filter,
    handle_at_me_support,
    remove_assignments,
)
from helpdesk.test_utils import (
    create_agent,
    create_contact,
    make_team,
    make_ticket,
    make_todo,
    unique_email,
)

ASSIGNED_AT = {
    "day_before": "2026-01-04 23:59:59",
    "midnight": "2026-01-05 00:00:00",
    "evening": "2026-01-05 18:30:00",
    "day_after": "2026-01-06 09:00:00",
}


class TestAtMeSupport(IntegrationTestCase):
    """`@me` in a saved or typed filter means whoever is looking at the list."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.agent = create_agent(unique_email("at-me")).name

    def test_list_conditions_replace_every_at_me(self) -> None:
        filters = [
            ["owner", "=", "@me"],
            ["_assign", "like", "%@me%"],
            ["HD Ticket", "raised_by", "=", "@me"],
            ["owner", "in", ["x@example.com", "@me", "@me"]],
            ["status", "=", "Open"],
            [],
        ]

        with self.set_user(self.agent):
            handle_at_me_support(filters)

        me = self.agent
        self.assertEqual(
            filters,
            [
                ["owner", "=", me],
                ["_assign", "like", f"%{me}%"],
                ["HD Ticket", "raised_by", "=", me],
                ["owner", "in", ["x@example.com", me, me]],
                ["status", "=", "Open"],
                [],
            ],
        )

    def test_dict_filters_replace_nested_at_me(self) -> None:
        filters = {
            "owner": "@me",
            "_assign": ["like", "%@me%"],
            "raised_by": ["in", ["@me", "x@example.com"]],
        }

        with self.set_user(self.agent):
            handle_at_me_support(filters)

        me = self.agent
        self.assertEqual(filters["owner"], me)
        self.assertEqual(filters["_assign"], ["like", f"%{me}%"])
        self.assertEqual(filters["raised_by"], ["in", [me, "x@example.com"]])


class TestAssignedOnFilter(IntegrationTestCase):
    """The "Assigned on" Date filter matches the session user's open ToDos."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.agent = create_agent(unique_email("assigned-on")).name
        cls.tickets = {}
        for label, at in ASSIGNED_AT.items():
            cls.tickets[label] = make_ticket(subject=f"Assigned on {label}").name
            make_todo(cls.tickets[label], cls.agent, at)

    def test_each_operator_treats_the_value_as_a_whole_day(self) -> None:
        cases = [
            ("=", "2026-01-05", {"midnight", "evening"}),
            ("!=", "2026-01-05", {"day_before", "day_after"}),
            (">", "2026-01-05", {"day_after"}),
            ("<", "2026-01-05", {"day_before"}),
            (">=", "2026-01-05", {"midnight", "evening", "day_after"}),
            ("<=", "2026-01-05", {"day_before", "midnight", "evening"}),
            ("between", ["2026-01-04", "2026-01-05"], set(ASSIGNED_AT) - {"day_after"}),
            ("is", "set", set(ASSIGNED_AT)),
            ("is", "not set", set()),
        ]
        for operator, value, expected in cases:
            with self.subTest(operator=operator, value=value):
                self.assertEqual(self.matches(operator, value), expected)

    def test_timespan_covers_the_full_system_day(self) -> None:
        with self.freeze_time("2026-01-05 23:59:00"):
            self.assertEqual(self.matches("timespan", "today"), {"midnight", "evening"})
            self.assertEqual(self.matches("timespan", "yesterday"), {"day_before"})

    def test_dict_filters_default_to_equals(self) -> None:
        filters = {"__assigned_on": "2026-01-05"}

        with self.set_user(self.agent):
            handle_assigned_on_filter(filters, "HD Ticket")

        self.assertNotIn("__assigned_on", filters)
        self.assertEqual(self.labels(filters["name"][1]), {"midnight", "evening"})

    def test_only_own_open_assignments_count(self) -> None:
        other_agent = create_agent(unique_email("assigned-on-other")).name
        ticket = make_ticket(subject="Assigned to someone else").name
        make_todo(ticket, other_agent, ASSIGNED_AT["evening"])
        cancelled = make_todo(ticket, self.agent, ASSIGNED_AT["evening"])
        frappe.db.set_value("ToDo", cancelled, "status", "Cancelled")

        self.assertNotIn(ticket, self.matching_names("=", "2026-01-05"))

    def test_no_match_lists_no_tickets(self) -> None:
        with self.set_user(self.agent):
            result = get_list_data(
                "HD Ticket", filters=[["__assigned_on", "=", "2020-01-01"]]
            )

        self.assertEqual(result["data"], [])
        self.assertEqual(result["total_count"], 0)

    def test_intersects_an_existing_name_in_filter(self) -> None:
        keep = [self.tickets["midnight"], self.tickets["day_before"]]
        list_filters = [
            ["name", "in", list(keep)],
            ["__assigned_on", "=", "2026-01-05"],
        ]
        dict_filters = {
            "name": ["in", list(keep)],
            "__assigned_on": ["=", "2026-01-05"],
        }

        with self.set_user(self.agent):
            handle_assigned_on_filter(list_filters, "HD Ticket")
            handle_assigned_on_filter(dict_filters, "HD Ticket")

        self.assertEqual(list_filters, [["name", "in", [self.tickets["midnight"]]]])
        self.assertEqual(dict_filters["name"], ["in", [self.tickets["midnight"]]])

    def matches(self, operator: str, value: str | list) -> set[str]:
        return self.labels(self.matching_names(operator, value))

    def matching_names(self, operator: str, value: str | list) -> list[str]:
        filters = [["__assigned_on", operator, value]]
        with self.set_user(self.agent):
            handle_assigned_on_filter(filters, "HD Ticket")
        return filters[0][2]

    def labels(self, names: list[str]) -> set[str]:
        by_name = {name: label for label, name in self.tickets.items()}
        return {by_name[name] for name in names if name in by_name}


class TestRemoveAssignments(IntegrationTestCase):
    """The assignee popover sends removed agents to `remove_assignments`."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.agent = create_agent(unique_email("unassigning")).name
        cls.assignee = create_agent(unique_email("assignee")).name
        cls.customer = create_contact("Unassign", unique_email("unassign-customer"))

    def setUp(self) -> None:
        self.ticket = make_ticket(raised_by=self.customer["user"]).name
        self.todo = make_todo(self.ticket, self.assignee)

    def test_agent_removes_assignment(self) -> None:
        with self.set_user(self.agent):
            remove_assignments("HD Ticket", self.ticket, [self.assignee])

        self.assertEqual(frappe.db.get_value("ToDo", self.todo, "status"), "Cancelled")
        assigned = frappe.db.get_value("HD Ticket", self.ticket, "_assign")
        self.assertNotIn(self.assignee, frappe.parse_json(assigned or "[]"))

    def test_admin_removes_assignment(self) -> None:
        remove_assignments("HD Ticket", self.ticket, [self.assignee])

        self.assertEqual(frappe.db.get_value("ToDo", self.todo, "status"), "Cancelled")

    def test_empty_assignees_change_nothing(self) -> None:
        with self.set_user(self.agent):
            self.assertIsNone(remove_assignments("HD Ticket", self.ticket, []))

        self.assertEqual(frappe.db.get_value("ToDo", self.todo, "status"), "Open")

    def test_customer_cannot_remove_assignments(self) -> None:
        with self.set_user(self.customer["user"]):
            with self.assertRaises(frappe.PermissionError):
                remove_assignments("HD Ticket", self.ticket, [self.assignee])

        self.assertEqual(frappe.db.get_value("ToDo", self.todo, "status"), "Open")

    def test_agent_outside_the_team_cannot_remove_assignments(self) -> None:
        team = make_team(f"Unassign {frappe.generate_hash(length=6)}", [self.assignee])
        frappe.db.set_value("HD Ticket", self.ticket, "agent_group", team.name)

        with change_settings("HD Settings", {"restrict_tickets_by_agent_group": 1}):
            with self.set_user(self.agent):
                with self.assertRaises(frappe.PermissionError):
                    remove_assignments("HD Ticket", self.ticket, [self.assignee])

        self.assertEqual(frappe.db.get_value("ToDo", self.todo, "status"), "Open")


class TestOutsideSettingsBoundary(IntegrationTestCase):
    def test_framework_connection_settings_are_blocked_for_administrator(self):
        from helpdesk.auth import authenticate
        for doctype in ["Google Settings", "Google Contacts", "SMS Settings", "Notification", "Connected App"]:
            with self.subTest(doctype=doctype), patch.object(frappe, "request", SimpleNamespace(path="/api/method/frappe.client.set_value")), patch.object(frappe, "form_dict", frappe._dict(doctype=doctype)):
                with self.assertRaises(frappe.PermissionError):
                    authenticate()

    def test_local_ticket_settings_remain_accessible(self):
        from helpdesk.auth import authenticate
        with patch.object(frappe, "request", SimpleNamespace(path="/api/method/frappe.client.get")), patch.object(frappe, "form_dict", frappe._dict(doctype="HD Ticket")):
            self.assertIsNone(authenticate())


class TestPublicFailureBoundaries(IntegrationTestCase):
    def test_admin_telephony_page_is_not_a_retired_api(self):
        from helpdesk.auth import authenticate
        with patch.object(frappe.local, "request", SimpleNamespace(path="/helpdesk/admin/telephony"), create=True), patch.object(frappe.local, "form_dict", frappe._dict()):
            authenticate()
        with patch.object(frappe.local, "request", SimpleNamespace(path="/api/method/telephony.call"), create=True), patch.object(frappe.local, "form_dict", frappe._dict()):
            with self.assertRaises(frappe.PermissionError):
                authenticate()

    def test_error_pages_never_include_diagnostics(self):
        from werkzeug.wrappers import Response
        from helpdesk.integrations.configuration import sanitise_error_response
        for status in (403, 404, 500):
            response = Response('Traceback File "/Users/private/app.py" frappe', status=status, content_type="text/html")
            sanitise_error_response(response)
            text = response.get_data(as_text=True)
            self.assertIn("Return to Helpdesk", text)
            for token in ("Traceback", "/Users/", "frappe", "<script", "bundle"):
                self.assertNotIn(token, text)

    def test_api_errors_preserve_validation_but_strip_traces(self):
        import json
        from werkzeug.wrappers import Response
        from helpdesk.integrations.configuration import sanitise_error_response
        body = {"exc_type": "ValidationError", "exc": "Traceback /Users/private/app.py", "exception": "private", "_server_messages": json.dumps([json.dumps({"message": "Set the calling number and your callback number in Calling settings."})])}
        response = Response(json.dumps(body), status=417, content_type="application/json")
        sanitise_error_response(response)
        self.assertEqual(response.get_json()["message"], "Set the calling number and your callback number in Calling settings.")
        self.assertEqual(response.get_json()["exc_type"], "ValidationError")
        self.assertNotIn("private", response.get_data(as_text=True))
        malformed = Response('["Traceback /workspace/private/app.py"]', status=500, content_type="application/json")
        sanitise_error_response(malformed)
        self.assertNotIn("/workspace", malformed.get_data(as_text=True))
        for status in (403, 404, 500):
            leaked = Response(json.dumps({"exc": "Traceback", "exception": "/workspace/app.py", "_server_messages": json.dumps([json.dumps({"message": 'File "/workspace/private/app.py" failed'})])}), status=status, content_type="application/json")
            sanitise_error_response(leaked)
            self.assertNotIn("/workspace", leaked.get_data(as_text=True))
            self.assertNotIn("Traceback", leaked.get_data(as_text=True))

    def test_missing_key_stops_every_external_entrypoint_before_writes(self):
        from helpdesk.api import capabilities, calling, outcome_reviews
        from helpdesk.api.settings import email
        from helpdesk.pramaan import PramaanClient, MissingPramaanKey, MISSING_KEY_MESSAGE
        actions = [(capabilities, capabilities.draft_ticket_reply), (capabilities, capabilities.start_callback),
                   (capabilities, capabilities.enrich_customer), (capabilities, capabilities.enrich_contact),
                   (capabilities, capabilities.parse_attachment), (outcome_reviews, outcome_reviews.prepare),
                   (outcome_reviews, outcome_reviews.run), (calling, calling.session),
                   (email, email.create_email_account), (email, email.provision_mailbox)]
        for module, function in actions:
            with patch.object(module, "client", return_value=PramaanClient(api_key="")), patch.object(frappe.db, "commit") as commit:
                with self.assertRaises(MissingPramaanKey) as raised:
                    function()
                self.assertEqual(str(raised.exception), MISSING_KEY_MESSAGE)
                self.assertEqual(raised.exception.http_status_code, 422)
                commit.assert_not_called()

    def test_system_manager_can_read_customer_invites_and_signin_settings(self):
        from helpdesk.test_utils import create_customer
        from helpdesk.api.settings.signin import get_data
        manager = create_agent(unique_email("review-manager"))
        manager.reload().add_roles("System Manager")
        customer = create_customer("Review customer " + frappe.generate_hash(length=8))
        with self.set_user(manager.name):
            self.assertIsInstance(frappe.get_doc("HD Customer", customer.name).get_pending_invites(), list)
            self.assertIn("enabled", get_data())

    def test_agent_cannot_read_manager_invites_or_signin_settings(self):
        from helpdesk.test_utils import create_customer
        from helpdesk.api.settings.signin import get_data
        agent = create_agent(unique_email("review-agent"))
        customer = create_customer("Private invites " + frappe.generate_hash(length=8))
        with self.set_user(agent.name):
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc("HD Customer", customer.name).get_pending_invites()
            with self.assertRaises(frappe.PermissionError):
                get_data()
