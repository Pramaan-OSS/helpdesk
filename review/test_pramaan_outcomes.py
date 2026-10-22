"""Outcome contract checks using fake responses only."""
import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from test_pramaan_stubs import boundary


class OutcomeTests(unittest.TestCase):
    body = {"input": {"content": "encoded", "extension": "txt"},
            "options": {}, "basis": {"ground": "contract"}}
    description = {"available": True, "effect_class": "read_only"}
    report = {"status": "done", "result": {"summary": "Source summary"},
              "steps": [], "cost": {"charged_micro": 12}}

    def fake(self, *responses):
        requests = []
        replies = iter(responses)
        def transport(*args):
            requests.append(args)
            return next(replies)
        return boundary.PramaanClient(api_key="fake", transport=transport, sleep=lambda _: None), requests

    def test_list_and_get_use_encoded_get_routes(self):
        client, requests = self.fake((200, {"results": []}), (200, self.description))
        self.assertEqual(client.outcomes_list(), {"results": []})
        self.assertEqual(client.outcome_get("one/two"), self.description)
        self.assertEqual([r[0] for r in requests], ["GET", "GET"])
        self.assertTrue(requests[1][1].endswith("/outcomes/one%2Ftwo"))

    def test_estimate_preserves_steps_price_and_plan_and_run_uses_identical_body(self):
        estimate = {"steps": [{"capability": "document.parse"}], "price_max_micro": 42,
                    "plan": "approved-plan", "can_run": True}
        client, requests = self.fake((200, estimate), (200, self.description), (200, self.report))
        self.assertEqual(client.outcome_estimate("document.summarize", self.body), estimate)
        self.assertEqual(client.outcome_run("document.summarize", self.body, plan=estimate["plan"]), self.report)
        self.assertEqual(requests[0][3], requests[2][3])
        self.assertEqual(requests[2][2]["Pramaan-Plan"], "approved-plan")
        for request in requests:
            for header in ("Pramaan-Account", "Pramaan-End-User", "Pramaan-End-User-Group", "Pramaan-Max-Price-Micro"):
                self.assertNotIn(header, request[2])

    def test_effectful_run_sends_saved_key_and_approver(self):
        client, requests = self.fake((200, {"available": True, "requires_approval": True,
                                             "effect_class": "external_irreversible"}), (200, self.report))
        client.outcome_run("email.send-tracked", self.body, plan="p", idempotency_key="saved", approved_by="member")
        self.assertEqual(requests[1][2]["Idempotency-Key"], "saved")
        self.assertNotIn("Pramaan-Approved-By", requests[1][2])

    def test_approval_required_blocks_run_before_post(self):
        client, requests = self.fake((200, {**self.description, "requires_approval": True}))
        with self.assertRaises(boundary.PramaanError) as error:
            client.outcome_run("email.send-tracked", self.body)
        self.assertEqual(error.exception.code, "approval_required")
        self.assertEqual(len(requests), 1)

    def test_action_requires_saved_key(self):
        client, requests = self.fake((200, {"available": True, "effect_class": "external_irreversible"}))
        with self.assertRaises(boundary.PramaanError) as error:
            client.outcome_run("email.send-tracked", self.body, plan="p")
        self.assertEqual(error.exception.code, "missing_idempotency_key")
        self.assertEqual(len(requests), 1)

    def test_202_polls_queued_then_running_then_report_without_resending(self):
        client, requests = self.fake((200, self.description),
            (202, {"job_id": "job/one", "status": "queued"}),
            (200, {"status": "running"}), (200, {"status": "done", "result": self.report}))
        self.assertEqual(client.outcome_run("document.summarize", self.body), self.report)
        self.assertEqual([r[0] for r in requests], ["GET", "POST", "GET", "GET"])
        self.assertTrue(requests[2][1].endswith("/jobs/job%2Fone"))
        self.assertEqual(requests[2][1], requests[3][1])

    def test_http_403_409_429_are_distinct_and_never_retried(self):
        for status, code in ((403, "approval_required"), (409, "plan_changed"), (429, "try_later")):
            with self.subTest(status=status):
                client, requests = self.fake((200, self.description), (status, {"error": "private body"}))
                with self.assertRaises(boundary.PramaanError) as error:
                    client.outcome_run("document.summarize", self.body, plan="old")
                self.assertEqual(error.exception.code, code)
                self.assertFalse(error.exception.uncertain)
                self.assertEqual(len(requests), 2)
                self.assertNotIn("private", str(error.exception))

    def test_unavailable_at_run_time_never_posts(self):
        client, requests = self.fake((200, {"available": False}))
        with self.assertRaises(boundary.PramaanError) as error:
            client.outcome_run("document.summarize", self.body)
        self.assertEqual(error.exception.code, "upstream_unavailable")
        self.assertFalse(error.exception.uncertain)
        self.assertEqual([r[0] for r in requests], ["GET"])

    def test_missing_availability_is_not_fallback_permission(self):
        client, requests = self.fake((200, {}))
        with self.assertRaises(boundary.PramaanError) as error:
            client.outcome_run("document.summarize", self.body)
        self.assertEqual(error.exception.code, "invalid_response")
        self.assertEqual(len(requests), 1)

    def test_502_unavailable_is_fallback_signal_but_generic_502_is_uncertain(self):
        for payload, code, uncertain in (({"error": "upstream_unavailable"}, "upstream_unavailable", False),
                                         ({"error": "other"}, "request_rejected", True)):
            client, requests = self.fake((200, self.description), (502, payload))
            with self.assertRaises(boundary.PramaanError) as error:
                client.outcome_run("document.summarize", self.body)
            self.assertEqual((error.exception.code, error.exception.uncertain), (code, uncertain))
            self.assertEqual(len(requests), 2)

    def test_real_http_error_body_is_normalized_without_leaking(self):
        client = boundary.PramaanClient(api_key="fake")
        for status in (403, 409, 429, 502):
            error = HTTPError("https://api.pramaan.dev", status, "private", {},
                              io.BytesIO(b'{"error":{"code":"upstream_unavailable","message":"private secret"}}'))
            with patch.object(boundary, "build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(boundary.PramaanError) as raised:
                    client._request("POST", "/v1/outcomes/one", {}, outcome=True)
            self.assertNotIn("private", str(raised.exception))
            self.assertEqual(raised.exception.code, {403: "approval_required", 409: "plan_changed",
                                                    429: "try_later", 502: "upstream_unavailable"}[status])

    def test_timeout_never_resends(self):
        requests = []
        def transport(*args):
            requests.append(args)
            if args[0] == "GET":
                return 200, self.description
            raise TimeoutError("private")
        client = boundary.PramaanClient(api_key="fake", transport=transport)
        with self.assertRaises(boundary.PramaanError) as error:
            client.outcome_run("document.summarize", self.body)
        self.assertTrue(error.exception.uncertain)
        self.assertEqual([r[0] for r in requests], ["GET", "POST"])

    def test_failed_report_with_unknown_effect_is_returned_intact(self):
        report = {"status": "failed", "steps": [{"effect": "unknown"}], "cost": {"charged_micro": 5}}
        client, requests = self.fake((200, self.description), (200, report))
        self.assertEqual(client.outcome_run("email.send-tracked", self.body), report)
        self.assertEqual(len(requests), 2)

    def test_failed_job_preserves_report(self):
        report = {"status": "failed", "steps": [{"effect": "done"}]}
        client, requests = self.fake((200, self.description), (202, {"job_id": "j", "status": "running"}),
                                     (200, {"status": "failed", "result": report}))
        self.assertEqual(client.outcome_run("email.send-tracked", self.body), report)
        self.assertEqual(len(requests), 3)

    def test_poll_limit_leaves_run_uncertain_and_does_not_resend(self):
        client, requests = self.fake((200, self.description), (202, {"job_id": "j", "status": "running"}),
                                     (200, {"status": "running"}))
        with self.assertRaises(boundary.PramaanError) as error:
            client.outcome_run("document.summarize", self.body, max_polls=1)
        self.assertEqual(error.exception.code, "job_pending")
        self.assertEqual(error.exception.job_id, "j")
        self.assertTrue(error.exception.uncertain)
        self.assertEqual([r[0] for r in requests], ["GET", "POST", "GET"])

    def test_poll_error_cannot_be_used_as_fallback_signal(self):
        client, requests = self.fake((200, self.description), (202, {"job_id": "j", "status": "running"}),
                                     (502, {"error": "upstream_unavailable"}))
        with self.assertRaises(boundary.PramaanError) as error:
            client.outcome_run("document.summarize", self.body)
        self.assertEqual(error.exception.code, "job_pending")
        self.assertEqual(error.exception.job_id, "j")
        self.assertTrue(error.exception.uncertain)

    def test_invalid_report_after_run_is_uncertain(self):
        client, requests = self.fake((200, self.description), (200, {}))
        with self.assertRaises(boundary.PramaanError) as error:
            client.outcome_run("document.summarize", self.body)
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(len(requests), 2)

    def test_completion_on_last_allowed_poll_is_returned(self):
        client, requests = self.fake((200, self.description), (202, {"job_id": "j", "status": "running"}),
                                     (200, {"status": "done", "result": self.report}))
        self.assertEqual(client.outcome_run("document.summarize", self.body, max_polls=1), self.report)
        self.assertEqual(len(requests), 3)

    def test_outcome_run_refuses_routing_and_price_overrides(self):
        client, requests = self.fake()
        for keyword in ("account", "end_user", "end_user_group", "max_price_micro"):
            with self.subTest(keyword=keyword), self.assertRaises(TypeError):
                client.outcome_run("document.summarize", self.body, **{keyword: "override"})
        self.assertEqual(requests, [])
