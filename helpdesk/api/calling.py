"""Browser phone: sessions, call control and ticket activity.

The browser never holds an API key. It gets a short-lived Pramaan session
credential from this app, talks audio to Pramaan's relay, and every call
action rides this server boundary with a saved idempotency key.
"""
import re
import uuid
from urllib.parse import urlsplit

import frappe
from frappe import _

from helpdesk.integrations.pramaan_mail import client, requires_pramaan
from helpdesk.pramaan import PramaanError
from helpdesk.utils import agent_only

E164 = re.compile(r"\+[1-9][0-9]{7,14}")
SESSION_LIFETIME = 900
CALL_MAX_DURATION = 1800


def request_origin() -> str:
    parts = urlsplit(frappe.utils.get_url())
    return f"{parts.scheme}://{parts.netloc}".lower()


def calling_number() -> str:
    number = frappe.db.get_single_value("HD Settings", "pramaan_calling_number")
    if not number:
        frappe.throw(_("Set the calling number in Calling settings first."), frappe.ValidationError)
    return number


def open_record(doctype, filters):
    return frappe.db.get_value(doctype, filters, "*", as_dict=True)


def open_doc(doctype, filters):
    """A mutable Document for filters, else None."""
    name = frappe.db.get_value(doctype, filters)
    return frappe.get_doc(doctype, name) if name else None


def _expired(record) -> bool:
    return bool(record.expires_at and frappe.utils.get_datetime(record.expires_at) <= frappe.utils.now_datetime())


@frappe.whitelist(methods=["POST"])
@agent_only
@requires_pramaan
def session():
    """Open or renew this agent's browser phone session; return its credential."""
    origin = request_origin()
    number = calling_number()
    record = open_doc("Pramaan Browser Session", {"agent": frappe.session.user, "enabled": 1})
    boundary = client()
    if record and record.session_ref and record.origin == origin and not _expired(record):
        result = boundary.call("voice.browser-session.refresh",
                               {"ref": record.session_ref, "lifetimeSeconds": SESSION_LIFETIME},
                               idempotency_key=str(uuid.uuid4()))
        record.db_set({"expires_at": result["expiresAt"]})
        return {"name": record.name, **result, "number": number}
    request_id = str(uuid.uuid4())
    if not record:
        record = frappe.get_doc({"doctype": "Pramaan Browser Session", "agent": frappe.session.user,
                                 "origin": origin, "request_id": request_id}).insert(ignore_permissions=True)
    else:
        record.db_set({"origin": origin, "request_id": request_id, "session_ref": "", "expires_at": None})
    # The durable record holds the action key before the outside call.
    frappe.db.commit()
    try:
        result = boundary.call("voice.browser-session.create",
                               {"agent": frappe.session.user, "from": number, "origin": origin,
                                "lifetimeSeconds": SESSION_LIFETIME},
                               idempotency_key=request_id, approved_by=frappe.session.user)
    except PramaanError as error:
        record.db_set({"enabled": 0, "cursor": ""})
        frappe.db.commit()
        raise
    record.db_set({"session_ref": result["ref"], "expires_at": result["expiresAt"], "enabled": 1})
    return {"name": record.name, **result, "number": number}


@frappe.whitelist(methods=["POST"])
@agent_only
@requires_pramaan
def close_session():
    record = open_doc("Pramaan Browser Session", {"agent": frappe.session.user, "enabled": 1})
    if not record or not record.session_ref:
        return {"closed": True}
    client().call("voice.browser-session.close", {"ref": record.session_ref},
                  idempotency_key=str(uuid.uuid4()))
    record.db_set({"enabled": 0, "session_ref": "", "cursor": ""})
    return {"closed": True}


def _ticket_for(correlation_id: str | None) -> str:
    if correlation_id and frappe.db.exists("HD Ticket", correlation_id):
        return correlation_id
    return ""


EVENT_ORDER = {"Starting": 0, "Running": 1, "Ended": 2, "Failed": 2}


def apply_event(record, event: dict) -> None:
    """Mirror one relay event into owned call records and ticket activity.

    Event ids are stable and increase within a session, so the stored cursor
    makes replays harmless: a re-read never rewinds a call or duplicates its
    ticket activity.
    """
    event_id = event.get("id") or ""
    if not event_id:
        return
    etype = event.get("type", "")
    call_ref = event.get("callRef") or ""
    row = None
    if call_ref:
        row = open_doc("Pramaan Call", {"result_ref": call_ref, "source": "browser"})
        if not row:
            row = frappe.get_doc({"doctype": "Pramaan Call", "source": "browser",
                                  "direction": event.get("direction"),
                                  "result_ref": call_ref,
                                  "ticket": _ticket_for(event.get("correlationId")),
                                  "request_id": str(uuid.uuid4()),
                                  "state": "Starting"}).insert(ignore_permissions=True)
    state_for = {"call.dialing": "Starting", "call.ringing": "Starting", "call.connected": "Running",
                 "call.rejected": "Ended", "call.failed": "Failed", "call.ended": "Ended"}
    if row and etype in state_for:
        new_state = state_for[etype]
        if EVENT_ORDER.get(new_state, 0) >= EVENT_ORDER.get(row.state, 0):
            first_end = new_state == "Ended" and row.state != "Ended"
            row.db_set({"state": new_state, "last_event": event_id})
            if first_end and row.ticket:
                reason = event.get("reason") or "completed"
                ticket = frappe.get_doc("HD Ticket", row.ticket)
                ticket.add_comment("Comment", _("Call ended ({0}).").format(reason),
                                   comment_email="Administrator")


@frappe.whitelist()
@agent_only
def ingest():
    """Read this agent's session events since the cursor and mirror them."""
    record = open_doc("Pramaan Browser Session", {"agent": frappe.session.user, "enabled": 1})
    if not record or not record.session_ref:
        return {"events": 0}
    page = client().call("voice.browser-session.events",
                         {"ref": record.session_ref, **({"cursor": record.cursor} if record.cursor else {})})
    events = page.get("events", [])
    for event in events:
        apply_event(record, event)
    if page.get("nextCursor") or events:
        record.db_set("cursor", page.get("nextCursor") or events[-1]["id"])
    return {"events": len(events)}


def ingest_all():
    """Scheduler mirror for every open session, so history never waits on a tab."""
    if not frappe.db.get_single_value("HD Settings", "pramaan_calling_number"):
        return
    for name in frappe.get_all("Pramaan Browser Session", filters={"enabled": 1, "session_ref": ("is", "set")},
                               pluck="name"):
        record = frappe.get_doc("Pramaan Browser Session", name)
        if _expired(record):
            continue
        try:
            page = client().call("voice.browser-session.events",
                                 {"ref": record.session_ref, **({"cursor": record.cursor} if record.cursor else {})})
        except PramaanError:
            continue
        for event in page.get("events", []):
            apply_event(record, event)
        if page.get("nextCursor") or page.get("events"):
            record.db_set("cursor", page.get("nextCursor") or page["events"][-1]["id"])
        frappe.db.commit()


def _browser_call_record(request_id: str, **fields):
    """The saved record for this action key, else a new one. Replays never dial again."""
    previous = open_doc("Pramaan Call", {"request_id": request_id, "source": "browser"})
    if previous:
        return previous, True
    record = frappe.get_doc({"doctype": "Pramaan Call", "source": "browser", "request_id": request_id,
                             "state": "Starting", **fields}).insert(ignore_permissions=True)
    return record, False


@frappe.whitelist(methods=["POST"])
@agent_only
@requires_pramaan
def start_call(ticket: str = "", number: str = "", request_id: str = ""):
    if not E164.fullmatch(number):
        frappe.throw(_("Enter the number with its country code, like +441234567890."))
    if ticket:
        frappe.get_doc("HD Ticket", ticket).check_permission("write")
    session_record = open_doc("Pramaan Browser Session", {"agent": frappe.session.user, "enabled": 1})
    if not session_record or not session_record.session_ref or _expired(session_record):
        frappe.throw(_("Open your phone first."), frappe.ValidationError)
    record, replayed = _browser_call_record(request_id, ticket=ticket, direction="outbound")
    if replayed:
        return {"name": record.name, "state": record.state}
    # Durable before dialing; a repeated request returns the same call.
    frappe.db.commit()
    try:
        result = client().call("voice.browser-call.start",
                               {"ref": session_record.session_ref, "to": number,
                                **({"correlationId": ticket} if ticket else {}),
                                "maxDurationSeconds": CALL_MAX_DURATION},
                               idempotency_key=request_id, approved_by=frappe.session.user)
        record.db_set({"state": "Running", "result_ref": result["callRef"]})
    except PramaanError as error:
        record.db_set("state", "Uncertain" if error.uncertain else "Failed")
        frappe.db.commit()
        raise
    return {"name": record.name, "state": record.state}


@frappe.whitelist(methods=["POST"])
@agent_only
@requires_pramaan
def accept_call(call_ref: str, request_id: str, ticket: str = ""):
    if ticket:
        frappe.get_doc("HD Ticket", ticket).check_permission("write")
    record, replayed = _browser_call_record(request_id, direction="inbound", ticket=ticket)
    if replayed:
        return {"name": record.name, "state": record.state}
    record.db_set("result_ref", call_ref)
    frappe.db.commit()
    try:
        result = client().call("voice.browser-call.accept",
                               {"ref": call_ref, "maxDurationSeconds": CALL_MAX_DURATION,
                                **({"correlationId": ticket} if ticket else {})},
                               idempotency_key=request_id, approved_by=frappe.session.user)
        record.db_set("state", "Running")
    except PramaanError as error:
        record.db_set("state", "Uncertain" if error.uncertain else "Failed")
        frappe.db.commit()
        raise
    return {"name": record.name, "state": record.state}


@frappe.whitelist(methods=["POST"])
@agent_only
@requires_pramaan
def reject_call(call_ref: str, request_id: str):
    record, replayed = _browser_call_record(request_id, direction="inbound")
    if replayed:
        return {"name": record.name, "state": record.state}
    record.db_set("result_ref", call_ref)
    frappe.db.commit()
    try:
        client().call("voice.browser-call.reject", {"ref": call_ref},
                      idempotency_key=request_id, approved_by=frappe.session.user)
        record.db_set("state", "Ended")
    except PramaanError as error:
        record.db_set("state", "Uncertain" if error.uncertain else "Failed")
        frappe.db.commit()
        raise
    return {"name": record.name, "state": record.state}


def _hangup_record(record) -> dict:
    if record.state in {"Ended", "Failed"} or not record.result_ref:
        return {"state": record.state}
    result = client().call("voice.call.end", {"ref": record.result_ref},
                           idempotency_key=record.request_id + "-end")
    if result.get("status") == "ended":
        record.db_set("state", "Ended")
    return {"state": record.state}


@frappe.whitelist(methods=["POST"])
@agent_only
def hangup(name: str):
    record = frappe.get_doc("Pramaan Call", name)
    if record.owner != frappe.session.user:
        record.check_permission("read")
        if record.ticket:
            frappe.get_doc("HD Ticket", record.ticket).check_permission("write")
    return _hangup_record(record)


@frappe.whitelist(methods=["POST"])
@agent_only
@requires_pramaan
def hangup_by_ref(call_ref: str):
    record = open_doc("Pramaan Call", {"result_ref": call_ref, "source": "browser"})
    if not record:
        frappe.throw(_("This call is not in the call log yet."), frappe.DoesNotExistError)
    return _hangup_record(record)
