"""Local review server with a fake outcome transport; never makes service calls.

Run from .runtime/bench/sites with the project Python and --site/serve arguments.
This is a test process only; normal app startup never imports it.
"""
import json
from pathlib import Path
from urllib.parse import urlparse

from helpdesk.api import outcome_reviews, auth
from helpdesk.pramaan import PramaanClient
from frappe.utils.bench_helper import main

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / ".runtime" / "outcomes-browser-requests.json"
requests = []
estimates = {}


def transport(method, url, headers, body):
    path = urlparse(url).path
    requests.append({"method": method, "path": path})
    EVENTS.write_text(json.dumps(requests))
    if method == "GET" and path == "/v1/outcomes/document.summarize":
        return 200, {"available": True, "effect_class": "read_only",
                     "steps": [{"capability": "document.parse"}, {"capability": "llm.complete"}]}
    if method == "POST" and path == "/v1/outcomes/document.summarize/estimate":
        estimates["headless-plan"] = body
        return 200, {"plan": "headless-plan", "can_run": True, "price_max_micro": 12345,
                     "steps": [{"capability": "document.parse"}, {"capability": "llm.complete"}]}
    if method == "POST" and path == "/v1/outcomes/document.summarize":
        if body != estimates.get(headers.get("Pramaan-Plan")):
            return 409, {"error": {"code": "conflict"}}
        return 200, {"status": "done", "completeness": "complete", "steps": [],
                     "result": {"summary": "The private attachment describes the support request.",
                                "points": [{"text": "Check the supplied details."}], "truncated": False}}
    return 502, {"error": {"code": "upstream_unavailable"}}


EVENTS.write_text("[]")
outcome_reviews.client = lambda: PramaanClient(api_key="fake", transport=transport, sleep=lambda _: None)
auth.PramaanClient = lambda: PramaanClient(api_key="fake", transport=transport)
main()
