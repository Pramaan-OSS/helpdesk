from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from helpdesk.api.article import get_article_stats, search
from helpdesk.search import NUM_RESULTS
from helpdesk.test_utils import (
    create_agent,
    create_contact,
    make_agent_manager,
    make_article,
    make_article_feedback,
    make_search_hit,
    make_search_page,
    unique_email,
)


class TestGetArticleStats(IntegrationTestCase):
    def setUp(self) -> None:
        frappe.set_user("Administrator")
        self.published = make_article()
        self.draft = make_article(status="Draft")

    def test_counts_views_likes_and_dislikes_of_one_article(self) -> None:
        frappe.db.set_value("HD Article", self.published, "views", 7)
        for feedback in (1, 1, 2, 0):
            make_article_feedback(self.published, feedback)
        make_article_feedback(self.draft, 1)

        stats = get_article_stats(self.published)

        self.assertEqual(stats, {"views": 7, "likes": 2, "dislikes": 1})

    def test_administrator_reads_stats_of_draft(self) -> None:
        self.assertEqual(get_article_stats(self.draft)["likes"], 0)

    def test_agent_reads_stats_of_draft(self) -> None:
        with self.set_user(create_agent(unique_email("article-agent")).name):
            self.assertEqual(get_article_stats(self.draft)["dislikes"], 0)

    def test_agent_manager_reads_stats_of_draft(self) -> None:
        user = make_agent_manager("article-manager")

        with self.set_user(user):
            self.assertEqual(get_article_stats(self.draft)["likes"], 0)

    def test_customer_reads_stats_of_published_article(self) -> None:
        make_article_feedback(self.published, 1)

        customer = create_contact("Article Customer", unique_email("article-customer"))

        with self.set_user(customer["user"]):
            self.assertEqual(get_article_stats(self.published)["likes"], 1)

    def test_customer_cannot_read_stats_of_unpublished_article(self) -> None:
        archived = make_article(status="Archived")
        customer = create_contact("Article Customer", unique_email("article-customer"))

        for article in (self.draft, archived, "missing-article"):
            with self.subTest(article=article), self.set_user(customer["user"]):
                with self.assertRaises(frappe.PermissionError):
                    get_article_stats(article)

    def test_inactive_agent_cannot_read_stats_of_draft(self) -> None:
        agent = create_agent(unique_email("article-agent")).name
        frappe.db.set_value("HD Agent", agent, "is_active", 0)

        with self.set_user(agent), self.assertRaises(frappe.PermissionError):
            get_article_stats(self.draft)


@patch("helpdesk.api.article.get_nouns", return_value=[])
@patch("helpdesk.api.article.get_noun_phrases", return_value=["password reset"])
@patch("helpdesk.api.article.hd_search")
class TestSearchArticles(IntegrationTestCase):
    def setUp(self) -> None:
        frappe.set_user("Administrator")
        self.articles = [make_article() for _ in range(NUM_RESULTS + 1)]

    def test_full_first_page_is_returned_without_fallback(self, hd_search, *_) -> None:
        hits = [make_search_hit(article) for article in self.articles[:NUM_RESULTS]]
        hd_search.return_value = make_search_page(*hits)

        result = search("  How do I RESET my password?! ")

        self.assertEqual(result, hits)
        hd_search.assert_called_once_with("how do i reset my password", qtype="and")

    def test_fallback_merges_unique_hits_up_to_the_limit(self, hd_search, *_) -> None:
        first, second, *rest = [make_search_hit(article) for article in self.articles]
        hd_search.side_effect = [
            make_search_page(first, second),
            make_search_page(second, *rest),
        ]

        result = search("reset my password")

        self.assertEqual(result, [first, second, *rest][:NUM_RESULTS])
        hd_search.assert_called_with("reset my password", qtype="or")

    def test_no_match_returns_empty_list(self, hd_search, *_) -> None:
        hd_search.return_value = []

        self.assertEqual(search("nothing matches this"), [])
        self.assertEqual(hd_search.call_count, 2)

    def test_customer_never_sees_unpublished_article_from_stale_index(
        self, hd_search, *_
    ) -> None:
        published = make_search_hit(self.articles[0])
        stale = [
            make_search_hit(make_article(status="Draft")),
            make_search_hit(make_article(status="Archived")),
            make_search_hit("deleted-article"),
        ]
        hd_search.return_value = make_search_page(published, *stale)
        customer = create_contact("Article Customer", unique_email("article-customer"))

        with self.set_user(customer["user"]):
            result = search("reset password")

        self.assertEqual(result, [published])


class TestDraftActions(IntegrationTestCase):
    def test_agent_reviews_draft_without_saved_reply(self):
        from helpdesk.api.capabilities import draft_ticket_reply
        from helpdesk.test_utils import make_ticket
        ticket = make_ticket()
        before = frappe.db.count("Communication", {"reference_doctype": "HD Ticket", "reference_name": ticket.name})
        with self.set_user("Administrator"), patch("helpdesk.api.capabilities.client") as factory:
            factory.return_value.call.return_value = {"text": "A suggested reply"}
            result = draft_ticket_reply(ticket.name)
        self.assertEqual(result["text"], "A suggested reply")
        self.assertEqual(frappe.db.count("Communication", {"reference_doctype": "HD Ticket", "reference_name": ticket.name}), before)
        self.assertEqual(factory.return_value.call.call_args.args[0], "llm.complete")

    def test_customer_cannot_request_an_agent_draft(self):
        from helpdesk.api.capabilities import draft_ticket_reply
        from helpdesk.test_utils import make_ticket, create_user
        ticket = make_ticket()
        user = create_user(unique_email("draft-customer"))
        with self.set_user(user.name), patch("helpdesk.api.capabilities.client") as factory, self.assertRaises(frappe.PermissionError):
            draft_ticket_reply(ticket.name)
        factory.assert_not_called()


class TestAttachmentOutcomeReview(IntegrationTestCase):
    def setUp(self):
        from helpdesk.test_utils import make_ticket, make_outcome_attachment
        from helpdesk.api import outcome_reviews
        self.actions = outcome_reviews
        frappe.set_user("Administrator")
        self.ticket = make_ticket()
        self.file = make_outcome_attachment(self.ticket)
        factory_patch = patch("helpdesk.api.outcome_reviews.client")
        factory = factory_patch.start()
        self.addCleanup(factory_patch.stop)
        commit_patch = patch.object(frappe.db, "commit")
        commit_patch.start()
        self.addCleanup(commit_patch.stop)
        self.client = factory.return_value
        self.client.outcome_get.return_value = {"available": True, "effect_class": "read_only",
            "steps": [{"capability": "document.parse"}, {"capability": "llm.complete"}]}
        self.client.outcome_estimate.return_value = {"plan": "estimated-plan", "can_run": True,
            "price_max_micro": 12345, "steps": [{"capability": "document.parse"}, {"capability": "llm.complete"}]}
        self.client.outcome_run.return_value = {"status": "done", "completeness": "complete",
            "result": {"summary": "A useful summary.", "points": [{"text": "One key point."}], "truncated": False}, "steps": []}

    def test_private_bytes_are_estimated_then_only_run_after_approval(self):
        import base64
        review = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        self.assertEqual(review["state"], "Ready")
        self.assertEqual(review["price_max_micro"], 12345)
        self.assertEqual(len(review["steps"]), 2)
        self.client.outcome_run.assert_not_called()
        body = self.client.outcome_estimate.call_args.args[1]
        self.assertEqual(base64.b64decode(body["input"]["content"]), self.file.get_content())
        self.assertNotIn("url", body["input"])
        with self.assertRaises(frappe.ValidationError):
            self.actions.run(review["review_id"])
        result = self.actions.run(review["review_id"], approved=True)
        self.assertEqual(result["summary"], "A useful summary.")
        self.assertEqual(self.client.outcome_run.call_args.args, ("document.summarize", body))
        self.assertEqual(self.client.outcome_run.call_args.kwargs["plan"], "estimated-plan")
        self.assertEqual(frappe.db.count("Comment", {"reference_doctype": "HD Ticket", "reference_name": self.ticket.name, "comment_type": "Comment"}), 0)
        self.assertFalse(frappe.db.get_value("Pramaan Outcome Review", review["review_id"], "body"))
        self.actions.run(review["review_id"], approved=True)
        self.client.outcome_run.assert_called_once()

    def test_unavailable_is_clear_and_does_not_estimate_or_run(self):
        self.client.outcome_get.return_value = {"available": False}
        result = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        self.assertEqual(result["state"], "Unavailable")
        self.assertIn("unavailable", result["message"])
        self.client.outcome_estimate.assert_not_called()
        self.client.outcome_run.assert_not_called()

    def test_changed_attachment_requires_new_estimate(self):
        review = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        with patch.object(type(self.file), "get_content", return_value=b"Changed attachment"):
            result = self.actions.run(review["review_id"], approved=True)
        self.assertEqual(result["state"], "Expired")
        self.client.outcome_run.assert_not_called()

    def test_expired_plan_requires_new_approval(self):
        with self.freeze_time("2026-10-12 10:00:00"):
            review = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        with self.freeze_time("2026-10-12 10:16:00"):
            result = self.actions.run(review["review_id"], approved=True)
        self.assertEqual(result["state"], "Expired")
        self.client.outcome_run.assert_not_called()

    def test_wrong_ticket_attachment_is_refused_before_estimate(self):
        from helpdesk.test_utils import make_ticket
        other = make_ticket()
        with self.assertRaises(frappe.PermissionError):
            self.actions.prepare("Summary", other.name, file_name=self.file.name)
        self.client.outcome_estimate.assert_not_called()

    def test_customer_cannot_prepare_run_poll_or_save(self):
        from helpdesk.test_utils import create_user, unique_email
        review = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        customer = create_user(unique_email("summary-customer"))
        with self.set_user(customer.name):
            for action, args in ((self.actions.prepare, {"kind": "Summary", "ticket": self.ticket.name, "file_name": self.file.name}),
                                 (self.actions.run, {"review_id": review["review_id"], "approved": True}),
                                 (self.actions.status, {"review_id": review["review_id"]}),
                                 (self.actions.save_call_note, {"review_id": review["review_id"], "confirmed": True})):
                with self.subTest(action=action.__name__), self.assertRaises(frappe.PermissionError):
                    action(**args)
        self.client.outcome_run.assert_not_called()

    def test_another_agent_cannot_use_the_plan(self):
        from helpdesk.test_utils import create_agent, unique_email
        review = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        other = create_agent(unique_email("other-review-agent"))
        with self.set_user(other.name), self.assertRaises(frappe.PermissionError):
            self.actions.run(review["review_id"], approved=True)
        self.client.outcome_run.assert_not_called()

    def test_size_and_empty_file_limits_are_checked_before_estimate(self):
        for content in (b"", b"x" * (10 * 1024 * 1024 + 1)):
            with self.subTest(size=len(content)), patch.object(type(self.file), "get_content", return_value=content):
                with self.assertRaises(frappe.ValidationError):
                    self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        self.client.outcome_estimate.assert_not_called()

    def test_uncertain_run_blocks_repeat_and_fresh_preparation(self):
        from helpdesk.pramaan import PramaanError
        first = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        second = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        self.client.outcome_run.side_effect = PramaanError("unavailable", uncertain=True)
        result = self.actions.run(first["review_id"], approved=True)
        self.assertEqual(result["state"], "Uncertain")
        self.actions.run(first["review_id"], approved=True)
        blocked = self.actions.run(second["review_id"], approved=True)
        self.assertEqual(blocked["review_id"], first["review_id"])
        again = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        self.assertEqual(again["review_id"], first["review_id"])
        self.client.outcome_run.assert_called_once()
        self.assertEqual(self.client.outcome_estimate.call_count, 2)

    def test_pending_job_can_finish_without_a_second_run(self):
        from helpdesk.pramaan import PramaanError
        review = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        report = self.client.outcome_run.return_value
        self.client.outcome_run.side_effect = PramaanError("job_pending", uncertain=True, job_id="saved-job")
        self.assertEqual(self.actions.run(review["review_id"], approved=True)["state"], "Pending")
        self.client.job.return_value = {"status": "done", "result": report}
        result = self.actions.status(review["review_id"])
        self.assertEqual(result["state"], "Completed")
        self.client.job.assert_called_once_with("saved-job")
        self.client.outcome_run.assert_called_once()

    def test_partial_summary_is_marked_and_cannot_be_saved_as_call_note(self):
        self.client.outcome_run.return_value["completeness"] = "partial"
        self.client.outcome_run.return_value["result"]["truncated"] = True
        review = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        result = self.actions.run(review["review_id"], approved=True)
        self.assertTrue(result["partial"])
        self.assertTrue(result["truncated"])
        with self.assertRaises(frappe.ValidationError):
            self.actions.save_call_note(review["review_id"], confirmed=True)

    def test_run_refusals_are_clear_without_capability_fallback(self):
        from helpdesk.pramaan import PramaanError
        for code, state in (("approval_required", "Failed"), ("plan_changed", "Failed"),
                            ("try_later", "Failed"), ("upstream_unavailable", "Unavailable")):
            with self.subTest(code=code):
                review = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
                self.client.outcome_run.side_effect = PramaanError(code)
                result = self.actions.run(review["review_id"], approved=True)
                self.assertEqual(result["state"], state)
                self.assertTrue(result["message"])
        self.client.call.assert_not_called()

    def test_runtime_availability_and_recipe_changes_block_the_run(self):
        description = self.client.outcome_get.return_value.copy()
        for change in ({"available": False}, {"effect_class": "external_reversible"}, {"steps": [{"capability": "email.send"}]}):
            self.client.outcome_get.return_value = description
            review = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
            self.client.outcome_get.return_value = {**description, **change}
            result = self.actions.run(review["review_id"], approved=True)
            self.assertEqual(result["state"], "Unavailable")
        self.client.outcome_run.assert_not_called()

    def test_review_does_not_block_attachment_deletion(self):
        review = self.actions.prepare("Summary", self.ticket.name, file_name=self.file.name)
        frappe.delete_doc("File", self.file.name)
        with self.assertRaises(frappe.DoesNotExistError):
            self.actions.run(review["review_id"], approved=True)
        self.client.outcome_run.assert_not_called()
