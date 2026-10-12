"""Browser calling: durable records, saved keys, event replay safety."""
import json
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase
from frappe.tests.utils import change_settings

from helpdesk.api import calling
from helpdesk.pramaan import PramaanError
from helpdesk.test_utils import create_agent, make_ticket, unique_email


def enable_calling():
    return change_settings("HD Settings", {"pramaan_calling_number": "+14155550111"})


class TestBrowserSession(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.agent = create_agent(unique_email("phone-agent"))

    def test_session_requires_a_calling_number(self):
        with self.set_user("Administrator"), change_settings("HD Settings", {"pramaan_calling_number": ""}), patch("helpdesk.api.calling.client") as factory:
            with self.set_user(self.agent.name), self.assertRaises(frappe.ValidationError):
                calling.session()
            factory.return_value.call.assert_not_called()

    def test_session_create_stores_the_ref_and_never_the_credential(self):
        with patch("helpdesk.api.calling.client") as factory:
            factory.return_value.call.return_value = {
                "ref": "ref_sess1", "connectUrl": "wss://relay/connect", "credential": "short-lived",
                "expiresAt": "2099-01-01 00:00:00", "number": "+14155550111",
            }
            with enable_calling(), self.set_user(self.agent.name):
                result = calling.session()
        self.assertEqual(result["credential"], "short-lived")
        saved = frappe.db.get_value("Pramaan Browser Session", {"agent": self.agent.name},
                                    ["session_ref", "request_id", "origin"], as_dict=True)
        self.assertEqual(saved.session_ref, "ref_sess1")
        self.assertTrue(saved.request_id)
        self.assertTrue(saved.origin.startswith("http"))
        kwargs = factory.return_value.call.call_args.kwargs
        self.assertEqual(kwargs["idempotency_key"], saved.request_id)

    def test_open_session_is_refreshed_not_recreated(self):
        frappe.get_doc({"doctype": "Pramaan Browser Session", "agent": self.agent.name,
                        "origin": calling.request_origin(), "session_ref": "ref_sess1",
                        "expires_at": "2099-01-01 00:00:00", "request_id": str(uuid4()),
                        "enabled": 1}).insert(ignore_permissions=True)
        with patch("helpdesk.api.calling.client") as factory:
            factory.return_value.call.return_value = {
                "connectUrl": "wss://relay/connect", "credential": "next",
                "expiresAt": "2099-01-01 01:00:00",
            }
            with enable_calling(), self.set_user(self.agent.name):
                result = calling.session()
        self.assertEqual(factory.return_value.call.call_args.args[0], "voice.browser-session.refresh")
        self.assertEqual(result["credential"], "next")


class TestBrowserCalls(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.agent = create_agent(unique_email("phone-agent"))
        self.ticket = make_ticket()

    def session_for(self):
        return frappe.get_doc({"doctype": "Pramaan Browser Session", "agent": self.agent.name,
                               "origin": calling.request_origin(), "session_ref": "ref_sess1",
                               "expires_at": "2099-01-01 00:00:00", "request_id": str(uuid4()),
                               "enabled": 1}).insert(ignore_permissions=True)

    def test_start_call_saves_the_record_before_dialing_with_the_request_key(self):
        self.session_for()
        request_id = str(uuid4())
        with patch("helpdesk.api.calling.client") as factory, patch.object(frappe.db, "commit"):
            factory.return_value.call.return_value = {"callRef": "ref_call1", "state": "dialing"}
            with enable_calling(), self.set_user(self.agent.name):
                first = calling.start_call(self.ticket.name, "+14155550100", request_id)
                second = calling.start_call(self.ticket.name, "+14155550100", request_id)
        self.assertEqual(first["name"], second["name"])
        factory.return_value.call.assert_called_once()
        kwargs = factory.return_value.call.call_args.kwargs
        self.assertEqual(kwargs["idempotency_key"], request_id)
        self.assertEqual(kwargs["approved_by"], self.agent.name)
        inputs = factory.return_value.call.call_args.args[1]
        self.assertEqual(inputs["correlationId"], self.ticket.name)
        self.assertEqual(frappe.db.get_value("Pramaan Call", first["name"], "state"), "Running")

    def test_start_call_rejects_a_bad_number_before_any_record(self):
        self.session_for()
        with patch("helpdesk.api.calling.client") as factory:
            with enable_calling(), self.set_user(self.agent.name):
                with self.assertRaises(frappe.ValidationError):
                    calling.start_call(self.ticket.name, "12345", str(uuid4()))
        factory.return_value.call.assert_not_called()
        self.assertEqual(frappe.db.count("Pramaan Call", {"source": "browser", "direction": "outbound"}), 0)

    def test_uncertain_start_is_marked_and_never_retried(self):
        self.session_for()
        request_id = str(uuid4())
        with patch("helpdesk.api.calling.client") as factory, patch.object(frappe.db, "commit"):
            factory.return_value.call.side_effect = PramaanError(uncertain=True)
            with enable_calling(), self.set_user(self.agent.name):
                with self.assertRaises(PramaanError):
                    calling.start_call(self.ticket.name, "+14155550100", request_id)
        self.assertEqual(frappe.db.get_value("Pramaan Call", {"request_id": request_id}, "state"),
                         "Uncertain")

    def test_events_are_ingested_once_and_comment_once(self):
        self.session_for()
        events = {"events": [
            {"id": "ve_1", "type": "call.ringing", "at": "t", "callRef": "ref_in1",
             "direction": "inbound", "from": "+14155550100", "to": "+14155550111",
             "correlationId": self.ticket.name},
            {"id": "ve_2", "type": "call.ended", "at": "t", "callRef": "ref_in1",
             "reason": "completed"},
        ], "nextCursor": "ve_2"}
        with patch("helpdesk.api.calling.client") as factory:
            factory.return_value.call.return_value = events
            with enable_calling(), self.set_user(self.agent.name):
                calling.ingest()
                # A replay from the same cursor never duplicates activity.
                factory.return_value.call.return_value = {**events, "nextCursor": ""}
                frappe.db.set_value("Pramaan Browser Session",
                                    {"agent": self.agent.name}, "cursor", "")
                calling.ingest()
        record = frappe.db.get_value("Pramaan Call", {"result_ref": "ref_in1"},
                                     ["state", "request_id", "ticket"], as_dict=True)
        self.assertEqual(record.state, "Ended")
        self.assertEqual(record.ticket, self.ticket.name)
        comments = frappe.get_all("Comment", filters={"reference_doctype": "HD Ticket",
                                                      "reference_name": self.ticket.name,
                                                      "content": ["like", "%Call ended%"]},
                                  pluck="content")
        self.assertEqual(len(comments), 1)


class TestCallOutcomeReview(IntegrationTestCase):
    def setUp(self):
        from helpdesk.api import outcome_reviews
        from helpdesk.test_utils import make_recorded_review_call
        frappe.set_user("Administrator")
        self.actions = outcome_reviews
        self.ticket = make_ticket()
        self.record = make_recorded_review_call(self.ticket)
        factory_patch = patch("helpdesk.api.outcome_reviews.client")
        factory = factory_patch.start()
        self.addCleanup(factory_patch.stop)
        commit_patch = patch.object(frappe.db, "commit")
        commit_patch.start()
        self.addCleanup(commit_patch.stop)
        self.client = factory.return_value
        self.client.outcome_get.return_value = {"available": True, "effect_class": "read_only",
            "steps": [{"capability": "audio.transcription.create"}, {"capability": "llm.complete"}]}
        self.client.call.return_value = {"recording": {"url": "https://files.example.com/audio?signature=fake",
            "fileId": "fake-file", "expiresAt": "2099-01-01T00:00:00Z", "contentType": "audio/mpeg", "sizeBytes": 123}}
        self.client.outcome_estimate.return_value = {"plan": "call-plan", "can_run": True, "price_max_micro": 10,
            "steps": [{"capability": "audio.transcription.create"}, {"capability": "llm.complete"}]}
        self.client.outcome_run.return_value = {"status": "done", "completeness": "complete", "steps": [],
            "result": {"audioUrl": "https://files.example.com/audio?signature=fake", "truncated": False,
                "findings": [{"id": "1", "criterion": "A next step was agreed.", "outcome": "met",
                              "quote": "We agreed a next step <script>alert(1)</script>", "start": 12}]}}

    def test_estimate_approval_and_second_confirmation_before_private_note(self):
        before = frappe.db.count("Comment", {"reference_doctype": "HD Ticket", "reference_name": self.ticket.name, "comment_type": "Comment"})
        review = self.actions.prepare("Call", self.ticket.name, call_name=self.record.name,
                                      criteria=["A next step was agreed."], basis="consent")
        self.client.outcome_run.assert_not_called()
        body = self.client.outcome_estimate.call_args.args[1]
        self.assertEqual(body["basis"], {"ground": "consent"})
        self.assertEqual(body["input"]["audioUrl"], self.client.call.return_value["recording"]["url"])
        self.client.call.assert_called_once_with("voice.call.recording.get", {"ref": self.record.result_ref})
        result = self.actions.run(review["review_id"], approved=True)
        self.assertNotIn("audioUrl", json.dumps(result))
        self.assertNotIn("signature", json.dumps(result))
        self.assertEqual(self.client.outcome_run.call_args.args, ("call.review", body))
        self.assertEqual(frappe.db.count("Comment", {"reference_doctype": "HD Ticket", "reference_name": self.ticket.name, "comment_type": "Comment"}), before)
        with self.assertRaises(frappe.ValidationError):
            self.actions.save_call_note(review["review_id"])
        saved = self.actions.save_call_note(review["review_id"], confirmed=True)
        self.assertTrue(saved["saved"])
        note_id = frappe.db.get_value("Pramaan Outcome Review", review["review_id"], "note")
        note = frappe.get_doc("Comment", note_id)
        self.assertEqual(note.reference_name, str(self.ticket.name))
        self.assertEqual(note.comment_type, "Comment")
        self.assertIn("&lt;script&gt;", note.content)
        self.assertNotIn("<script>", note.content)
        self.assertNotIn("signature", note.content)
        self.actions.save_call_note(review["review_id"], confirmed=True)
        self.assertEqual(frappe.db.count("Comment", {"reference_doctype": "HD Ticket", "reference_name": self.ticket.name, "comment_type": "Comment"}), before + 1)

    def test_private_expired_or_large_recording_is_not_forced_into_outcome(self):
        recording = self.client.call.return_value["recording"]
        for changes in ({"url": "https://["}, {"url": "http://127.0.0.1/private/audio"}, {"url": "https://127.0.0.1/private/audio"},
                        {"expiresAt": "2020-01-01T00:00:00Z"}, {"sizeBytes": 10_000_001}):
            with self.subTest(changes=changes):
                self.client.call.return_value = {"recording": {**recording, **changes}}
                result = self.actions.prepare("Call", self.ticket.name, call_name=self.record.name,
                                              criteria=["A next step was agreed."])
                self.assertEqual(result["state"], "Unavailable")
        self.client.outcome_estimate.assert_not_called()
        self.client.outcome_run.assert_not_called()

    def test_live_unavailable_does_not_retrieve_or_review_recording(self):
        self.client.outcome_get.return_value = {"available": False}
        result = self.actions.prepare("Call", self.ticket.name, call_name=self.record.name, criteria=["The issue was described."])
        self.assertEqual(result["state"], "Unavailable")
        self.client.call.assert_not_called()
        self.client.outcome_run.assert_not_called()

    def test_recording_flag_and_completed_state_are_required(self):
        for changes in ({"recording_enabled": 0}, {"recording_enabled": 1, "state": "Running"}):
            self.record.db_set(changes)
            with self.assertRaises(frappe.ValidationError):
                self.actions.prepare("Call", self.ticket.name, call_name=self.record.name, criteria=["The issue was described."])
        self.client.call.assert_not_called()

    def test_invalid_criteria_or_basis_is_refused_before_retrieval(self):
        for criteria, basis in (([], "contract"), (["x"] * 11, "contract"), (["x" * 401], "contract"), (["x"], "unknown")):
            with self.subTest(basis=basis, count=len(criteria)), self.assertRaises(frappe.ValidationError):
                self.actions.prepare("Call", self.ticket.name, call_name=self.record.name, criteria=criteria, basis=basis)
        self.client.call.assert_not_called()

    def test_changed_recording_ref_requires_new_estimate(self):
        review = self.actions.prepare("Call", self.ticket.name, call_name=self.record.name, criteria=["The issue was described."])
        self.record.db_set("result_ref", "changed-ref")
        result = self.actions.run(review["review_id"], approved=True)
        self.assertEqual(result["state"], "Expired")
        self.client.outcome_run.assert_not_called()

    def test_customer_cannot_review_or_save_call_results(self):
        from helpdesk.test_utils import create_user
        review = self.actions.prepare("Call", self.ticket.name, call_name=self.record.name, criteria=["The issue was described."])
        self.actions.run(review["review_id"], approved=True)
        customer = create_user(unique_email("call-review-customer"))
        with self.set_user(customer.name):
            with self.assertRaises(frappe.PermissionError):
                self.actions.prepare("Call", self.ticket.name, call_name=self.record.name, criteria=["The issue was described."])
            with self.assertRaises(frappe.PermissionError):
                self.actions.save_call_note(review["review_id"], confirmed=True)

    def test_partial_call_findings_are_marked_in_confirmed_note(self):
        self.client.outcome_run.return_value["completeness"] = "partial"
        self.client.outcome_run.return_value["result"]["truncated"] = True
        review = self.actions.prepare("Call", self.ticket.name, call_name=self.record.name, criteria=["The issue was described."])
        result = self.actions.run(review["review_id"], approved=True)
        self.assertTrue(result["partial"])
        self.assertTrue(result["truncated"])
        self.actions.save_call_note(review["review_id"], confirmed=True)
        note_id = frappe.db.get_value("Pramaan Outcome Review", review["review_id"], "note")
        self.assertIn("Only part of the call", frappe.get_doc("Comment", note_id).content)

    def test_run_becomes_unavailable_after_estimate_without_saving_note(self):
        from helpdesk.pramaan import PramaanError
        review = self.actions.prepare("Call", self.ticket.name, call_name=self.record.name, criteria=["The issue was described."])
        self.client.outcome_run.side_effect = PramaanError("upstream_unavailable")
        result = self.actions.run(review["review_id"], approved=True)
        self.assertEqual(result["state"], "Unavailable")
        self.assertIn("Call review is unavailable", result["message"])
        self.assertFalse(frappe.db.get_value("Pramaan Outcome Review", review["review_id"], "note"))

    def test_uncertain_call_review_never_runs_or_retrieves_a_second_time(self):
        from helpdesk.pramaan import PramaanError
        review = self.actions.prepare("Call", self.ticket.name, call_name=self.record.name, criteria=["The issue was described."])
        self.client.outcome_run.side_effect = PramaanError("unavailable", uncertain=True)
        result = self.actions.run(review["review_id"], approved=True)
        self.assertEqual(result["state"], "Uncertain")
        self.actions.run(review["review_id"], approved=True)
        again = self.actions.prepare("Call", self.ticket.name, call_name=self.record.name, criteria=["The issue was described."])
        self.assertEqual(again["review_id"], review["review_id"])
        self.client.outcome_run.assert_called_once()
        self.client.call.assert_called_once()
