"""Explicit agent reviews; estimates and run intent remain owned server records."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
from html import escape
import ipaddress
import json
from pathlib import PurePath
import re
from urllib.parse import urlparse

import frappe
from helpdesk.integrations.pramaan_mail import client, requires_pramaan
from helpdesk.pramaan import PramaanError
from helpdesk.utils import agent_only


KINDS = {"Summary": "document.summarize", "Call": "call.review"}
STEPS = {"document.parse": "Read the attachment text", "llm.complete": "Prepare the suggested result",
         "audio.transcription.create": "Transcribe the recording"}
EXPECTED_STEPS = {"Summary": {"document.parse", "llm.complete"}, "Call": {"audio.transcription.create", "llm.complete"}}
UNAVAILABLE = {"Summary": "Attachment summarising is unavailable. You can still open or download the attachment.",
               "Call": "Call review is not available yet. Your call record has not changed."}


def _available(boundary, kind):
    description = boundary.outcome_get(KINDS[kind])
    steps = description.get("steps")
    return (description.get("available") is True and description.get("effect_class") == "read_only"
            and isinstance(steps, list) and len(steps) == 2
            and all(isinstance(step, dict) for step in steps)
            and {step.get("capability") for step in steps} == EXPECTED_STEPS[kind])


def _source(kind, ticket, file_name=None, call_name=None):
    doc = frappe.get_doc("HD Ticket", ticket)
    doc.check_permission("read")
    if kind == "Summary":
        source = frappe.get_doc("File", file_name)
        source.check_permission("read")
        if source.attached_to_doctype != "HD Ticket" or str(source.attached_to_name) != str(ticket):
            frappe.throw("Choose an attachment on this ticket.", frappe.PermissionError)
    elif kind == "Call":
        source = frappe.get_doc("Pramaan Call", call_name)
        source.check_permission("read")
        if str(source.ticket) != str(ticket):
            frappe.throw("Choose a call on this ticket.", frappe.PermissionError)
        if source.state != "Ended" or not source.recording_enabled or not source.result_ref:
            frappe.throw("Choose a completed call with a recording requested.")
    else:
        frappe.throw("Choose a supported review.")
    return doc, source


def _file_input(source):
    content = source.get_content()
    if isinstance(content, str):
        content = content.encode()
    if not content or len(content) > 10 * 1024 * 1024:
        frappe.throw("Choose a nonempty attachment up to 10 MB (10,485,760 bytes).")
    extension = PurePath(source.file_name).suffix.lstrip(".").lower() or "txt"
    if not re.fullmatch(r"[a-z0-9]{1,8}", extension):
        frappe.throw("This attachment's file type cannot be summarised.")
    return {"content": base64.b64encode(content).decode(), "extension": extension}, hashlib.sha256(content).hexdigest(), len(content)


def _recording_usable(recording):
    """Only the owned platform link, never a newly published local recording."""
    if not isinstance(recording, dict) or not isinstance(recording.get("url"), str) or not isinstance(recording.get("expiresAt"), str):
        return False
    try:
        parsed = urlparse(recording["url"])
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment
            or host == "localhost" or host.endswith((".localhost", ".local"))
            or len(recording.get("url", "")) > 2048
            or recording.get("contentType") not in {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav"}
            or not isinstance(recording.get("sizeBytes"), (int, float))
            or not 0 < recording["sizeBytes"] <= 10_000_000):
        return False
    try:
        if not ipaddress.ip_address(host).is_global:
            return False
    except ValueError:
        pass
    try:
        expiry = datetime.fromisoformat(recording["expiresAt"].replace("Z", "+00:00"))
        return expiry.tzinfo is not None and expiry >= datetime.now(timezone.utc) + timedelta(minutes=35)
    except (KeyError, TypeError, ValueError):
        return False


def _owned(name, lock=False):
    if lock:
        frappe.db.sql("select name from `tabPramaan Outcome Review` where name=%s for update", name)
    review = frappe.get_doc("Pramaan Outcome Review", name)
    if review.owner != frappe.session.user:
        frappe.throw("This review belongs to another agent.", frappe.PermissionError)
    _source(review.review_kind, review.ticket, review.file_name, review.call_record)
    return review


def _view(review):
    response = {"review_id": review.name, "kind": review.review_kind, "state": review.state,
                "message": review.message or "", "can_poll": bool(review.job_id), "saved": bool(review.note and frappe.db.exists("Comment", review.note))}
    if review.state == "Ready":
        body = json.loads(review.body)
        if review.get("price_typical_micro") not in (None, ""):
            response["price_typical_micro"] = int(review.price_typical_micro)
        response.update(steps=json.loads(review.steps), price_max_micro=review.price_max_micro,
                        source_label=review.source_label, source_size=review.source_size,
                        criteria=[criterion["text"] for criterion in body["input"].get("criteria", [])],
                        basis=body.get("basis", {}).get("ground"), expires_in_minutes=15)
    if review.result:
        report = json.loads(review.result)
        result = report.get("result") or {}
        response.update(partial=report.get("completeness") == "partial", truncated=bool(result.get("truncated")))
        if review.review_kind == "Summary":
            response.update(summary=result.get("summary") or "", points=result.get("points") or [])
        else:
            response["findings"] = result.get("findings") or []
        # The signed audio URL, body and plan never enter a browser response.
    return response


def _mark_error(review, error):
    if error.uncertain:
        state = "Pending" if error.job_id else "Uncertain"
        message = "The run may still be in progress. Check its status; do not start another run."
    else:
        state = "Unavailable" if error.code == "upstream_unavailable" else "Failed"
        message = {"upstream_unavailable": UNAVAILABLE[review.review_kind],
                   "approval_required": "Approval was refused. Get a new estimate before approving again.",
                   "plan_changed": "The plan changed or expired. Get a new estimate and approve it again.",
                   "try_later": "Pramaan is busy. Try a new estimate later."}.get(error.code, "The review could not be completed.")
    review.db_set({"state": state, "message": message, "job_id": error.job_id or review.job_id or "", "body": ""})


def _finish(review, report):
    if not isinstance(report, dict) or report.get("status") not in {"done", "failed", "declined"}:
        _mark_error(review, PramaanError("invalid_response", uncertain=True))
        return
    done = report.get("status") == "done" and isinstance(report.get("result"), dict)
    review.db_set({"state": "Completed" if done else "Failed", "result": json.dumps(report), "body": "",
                   "message": "" if done else "The run did not complete. Check the result before requesting another review."})
    if not done and any(step.get("effect") == "unknown" for step in report.get("steps", [])):
        review.db_set({"state": "Uncertain", "message": "The run could not be confirmed. Do not start another run."})


@frappe.whitelist(methods=["POST"])
@agent_only
@requires_pramaan
def prepare(kind: str, ticket: str, file_name: str | None = None, call_name: str | None = None,
            criteria: str | list | None = None, basis: str = "contract"):
    _, source = _source(kind, ticket, file_name, call_name)
    # Serialize review preparation per source, including double clicks/reloaded pages.
    table = "File" if kind == "Summary" else "Pramaan Call"
    frappe.db.sql(f"select name from `tab{table}` where name=%s for update", source.name)
    _, source = _source(kind, ticket, file_name, call_name)
    filters = {"owner": frappe.session.user, "review_kind": kind, "ticket": ticket,
               "file_name" if kind == "Summary" else "call_record": source.name,
               "state": ["in", ["Running", "Pending", "Uncertain"]]}
    active = frappe.db.get_value("Pramaan Outcome Review", filters, "name")
    if active:
        return _view(_owned(active))
    boundary = client()
    try:
        if not _available(boundary, kind):
            return {"state": "Unavailable", "message": UNAVAILABLE[kind]}
        recording_expires = ""
        if kind == "Summary":
            inputs, fingerprint, source_size = _file_input(source)
            body = {"input": inputs, "options": {"maxPoints": 5}}
        else:
            criteria = json.loads(criteria) if isinstance(criteria, str) else criteria
            if (not isinstance(criteria, list) or not 1 <= len(criteria) <= 10
                    or any(not isinstance(text, str) or not text.strip() or len(text.strip()) > 400 for text in criteria)):
                frappe.throw("Enter 1–10 checks about what was said or done, up to 400 characters each.")
            if basis not in {"consent", "contract", "legitimate_interest"}:
                frappe.throw("Choose the basis for processing the recording.")
            recording = boundary.call("voice.call.recording.get", {"ref": source.result_ref}).get("recording", {})
            if not _recording_usable(recording):
                return {"state": "Unavailable", "message": "Call review needs an owned HTTPS recording link valid for at least 35 minutes, up to 10 MB. This recording cannot be reviewed."}
            recording_expires = recording["expiresAt"]
            source_size = recording["sizeBytes"]
            fingerprint = source.result_ref
            body = {"input": {"audioUrl": recording["url"], "criteria": [
                {"id": str(index + 1), "text": text.strip()} for index, text in enumerate(criteria)]},
                "options": {}, "basis": {"ground": basis}}
        estimate = boundary.outcome_estimate(KINDS[kind], body)
    except PramaanError as error:
        if error.code == "not_available_yet":
            return {"state": "Unavailable", "message": str(error)}
        return {"state": "Unavailable" if error.code == "upstream_unavailable" else "Failed",
                "message": UNAVAILABLE[kind] if error.code == "upstream_unavailable" else "The estimate could not be prepared. Check the input and try later."}
    if (estimate.get("can_run") is not True or not isinstance(estimate.get("plan"), str)
            or not estimate["plan"] or not isinstance(estimate.get("price_max_micro"), int)
            or estimate["price_max_micro"] < 0 or not isinstance(estimate.get("steps"), list)):
        return {"state": "Failed", "message": "An estimate could not be prepared. Check the input and try later."}
    if (any(not isinstance(step, dict) for step in estimate["steps"])
            or {step.get("capability") for step in estimate["steps"]} != EXPECTED_STEPS[kind]):
        return {"state": "Unavailable", "message": UNAVAILABLE[kind]}
    steps = [STEPS[step["capability"]] for step in estimate["steps"] if step.get("status") != "skipped"]
    review = frappe.get_doc({"doctype": "Pramaan Outcome Review", "review_kind": kind, "ticket": ticket,
        "file_name": source.name if kind == "Summary" else None, "call_record": source.name if kind == "Call" else None,
        "outcome_id": KINDS[kind], "body": json.dumps(body), "source_hash": fingerprint,
        "source_label": source.file_name if kind == "Summary" else f"Call on ticket {ticket} ({source.creation})",
        "source_size": source_size,
        "plan": estimate["plan"], "steps": json.dumps(steps), "price_max_micro": estimate["price_max_micro"],
        "price_typical_micro": str(estimate["price_typical_micro"]) if estimate.get("price_typical_micro") is not None else None,
        "state": "Ready", "recording_expires": recording_expires}).insert(ignore_permissions=True)
    frappe.db.commit()
    return _view(review)


@frappe.whitelist(methods=["POST"])
@agent_only
@requires_pramaan
def run(review_id: str, approved: bool = False):
    review = _owned(review_id, lock=True)
    if review.state != "Ready":
        return _view(review)
    if not frappe.utils.cint(approved):
        frappe.throw("Approve the estimate before running this review.")
    if frappe.utils.get_datetime(review.creation) + timedelta(minutes=15) <= frappe.utils.now_datetime():
        review.db_set({"state": "Expired", "body": "", "message": "This estimate expired. Get a new estimate and approve it again."})
        return _view(review)
    _, source = _source(review.review_kind, review.ticket, review.file_name, review.call_record)
    table = "File" if review.review_kind == "Summary" else "Pramaan Call"
    frappe.db.sql(f"select name from `tab{table}` where name=%s for update", source.name)
    _, source = _source(review.review_kind, review.ticket, review.file_name, review.call_record)
    active = frappe.db.get_value("Pramaan Outcome Review", {
        "owner": frappe.session.user, "review_kind": review.review_kind, "ticket": review.ticket,
        "file_name" if review.review_kind == "Summary" else "call_record": source.name,
        "name": ["!=", review.name], "state": ["in", ["Running", "Pending", "Uncertain"]]}, "name")
    if active:
        return _view(_owned(active))
    body = json.loads(review.body)
    if review.review_kind == "Summary":
        inputs, fingerprint, source_size = _file_input(source)
        changed = fingerprint != review.source_hash or inputs != body["input"]
    else:
        changed = source.result_ref != review.source_hash or not _recording_usable({
            "url": body["input"]["audioUrl"], "expiresAt": review.recording_expires,
            "contentType": "audio/mpeg", "sizeBytes": 1})
    if changed:
        review.db_set({"state": "Expired", "body": "", "message": "The source changed or its link expired. Get a new estimate and approve it again."})
        return _view(review)
    review.db_set("state", "Running")
    frappe.db.commit()  # Durable intent before any run, never a second POST after uncertainty.
    try:
        boundary = client()
        if not _available(boundary, review.review_kind):
            raise PramaanError("upstream_unavailable")
        report = boundary.outcome_run(review.outcome_id, body, plan=review.plan, idempotency_key=review.name)
        _finish(review, report)
    except PramaanError as error:
        _mark_error(review, error)
    except Exception:
        _mark_error(review, PramaanError("unavailable", uncertain=True))
    frappe.db.commit()
    return _view(review)


@frappe.whitelist(methods=["POST"])
@agent_only
@requires_pramaan
def status(review_id: str):
    review = _owned(review_id, lock=True)
    if review.state == "Pending" and review.job_id:
        try:
            job = client().job(review.job_id)
            if job.get("status") in {"done", "failed", "cancelled"}:
                _finish(review, job.get("result"))
        except PramaanError:
            review.db_set("message", "The run's status could not be checked yet. Do not start another run.")
    return _view(review)


@frappe.whitelist(methods=["POST"])
@agent_only
def save_call_note(review_id: str, confirmed: bool = False):
    review = _owned(review_id, lock=True)
    if review.review_kind != "Call" or review.state != "Completed" or not frappe.utils.cint(confirmed):
        frappe.throw("Review the completed call result and confirm saving an internal note.")
    ticket = frappe.get_doc("HD Ticket", review.ticket)
    ticket.check_permission("write")
    if not review.note or not frappe.db.exists("Comment", review.note):
        report = json.loads(review.result)
        result = report["result"]
        if not result.get("findings"):
            frappe.throw("No usable call findings were returned. Nothing was saved.")
        lines = ["Call review (suggestion; check the quoted words)"]
        if report.get("completeness") == "partial" or result.get("truncated"):
            lines.append("Only part of the call was checked. Unchecked criteria are not a negative finding.")
        for finding in result.get("findings", []):
            lines.append(f'{finding.get("criterion", "")}: {finding.get("outcome", "not_checked").replace("_", " ")}')
            if finding.get("quote"):
                lines.append(f'Quote: {finding["quote"]}')
            if finding.get("start") is not None:
                lines.append(f'At {finding["start"]} seconds')
            if finding.get("note"):
                lines.append(finding["note"])
        note = ticket.add_comment("Comment", "<p>" + "<br>".join(escape(line) for line in lines) + "</p>")
        review.db_set("note", note.name)
        frappe.db.commit()
    return _view(review)
