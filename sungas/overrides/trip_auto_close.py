"""Patch 0019 -- natural auto-close for Daily Loading Schedule trips.

A Dispatched trip closes itself once it is fully reconciled:
  * the dispatch Stock Entry is submitted,
  * every drop's receipt Stock Entry is submitted (or the drop was marked
    Rejected / Rescheduled), and
  * no Draft receipt is still hanging off the dispatch.
Patch 0058: a trip with an open shortage case (IOVC / TLVC) on any of its
stock entries waits for that case and closes itself the moment the case is
approved; while it waits it is tagged 'Waiting on case' and is not chased as a
stale trip (the case has its own time limits). If Patch 0016 requires trip-cost settlement,
Finance gets a task first. Trips still open 24h after dispatch are flagged
to the Head of Operations (ToDo + bell + email), never closed.
"""
from __future__ import annotations

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

DLS = "Daily Loading Schedule"
STALE_HOURS = 24
RECONCILED_DROP_STATES = {"Rejected", "Rescheduled"}
HOO_ROLES = ("LPG Head of Operations",)
FINANCE_ROLES = ("LPG Head of Finance", "Accounts Manager")
TAG_STALE = "[Trip Still Open]"
TAG_SETTLE = "[Trip Ready - Settle Costs]"
CASE_LINKS = (("Inter-Outlet Variance Case", ("dispatch_entry", "receipt_entry")),
              ("Transit Loss Variance Case", ("outlet_receipt_se",)))


def _docstatus(se):
    return frappe.db.get_value("Stock Entry", se, "docstatus") if se else None


def reconcile_status(doc) -> dict:
    pending = []
    if doc.get("state") != "Dispatched":
        pending.append(f"trip is '{doc.get('state')}', not Dispatched")
    disp = doc.get("dispatch_stock_entry")
    if _docstatus(disp) != 1:
        pending.append("dispatch Stock Entry is not submitted")
    for d in doc.get("drops") or []:
        if d.get("state") in RECONCILED_DROP_STATES:
            continue
        label = f"drop {d.get('idx')} ({d.get('destination_outlet')})"
        se = d.get("receipt_stock_entry")
        if not se:
            pending.append(f"{label} has no receipt")
        elif _docstatus(se) != 1:
            pending.append(f"{label} receipt {se} is not submitted")
    if disp and frappe.db.count("Stock Entry", {"outgoing_stock_entry": disp, "docstatus": 0}):
        pending.append("a Draft receipt is still open on the dispatch")
    return {"ready": not pending, "pending": pending}


def _trip_entries(doc) -> list[str]:
    ses = [doc.get("dispatch_stock_entry")] + [d.get("receipt_stock_entry") for d in doc.get("drops") or []]
    return [se for se in ses if se]


def open_cases(doc) -> list[str]:
    ses = _trip_entries(doc)
    found = set()
    for dt, fields in CASE_LINKS if ses else ():
        for f in fields:
            found.update(frappe.get_all(dt, filters={f: ["in", ses], "docstatus": 0}, pluck="name"))
    return sorted(found)


def _mark_waiting(doc, cases):
    text = ", ".join(cases)
    if (doc.get("waiting_on_case") or "") == text:
        return
    frappe.db.set_value(DLS, doc.name, "waiting_on_case", text, update_modified=False)
    if text:
        doc.add_comment("Info", f"<b>[Trip Auto-Close]</b> Every drop is received. The trip closes itself once case(s) "
                                f"{text} are approved.")


def _settlement_pending(doc) -> bool:
    from sungas.overrides.haulage_costing import ensure_trip_settled

    try:
        ensure_trip_settled(doc)
        return False
    except frappe.ValidationError:
        frappe.clear_messages()
        return True


def _role_users(roles) -> list[str]:
    users = frappe.get_all("Has Role", filters={"role": ["in", list(roles)], "parenttype": "User"},
                           pluck="parent", distinct=True)
    return [u for u in users if u not in ("Administrator", "Guest")
            and frappe.db.get_value("User", u, "enabled")]


def _task(roles, doc, tag, subject, message) -> list[str]:
    """One Open ToDo per role user (bell via Patch 0018) + one email to new ones."""
    new = []
    for user in _role_users(roles):
        if frappe.db.exists("ToDo", {"reference_type": DLS, "reference_name": doc.name,
                                     "allocated_to": user, "status": "Open",
                                     "description": ["like", f"%{tag}%"]}):
            continue
        frappe.get_doc({"doctype": "ToDo", "reference_type": DLS, "reference_name": doc.name,
                        "allocated_to": user, "priority": "High", "status": "Open",
                        "description": f"<p><b>{tag}</b> {subject}</p>{message}"}).insert(ignore_permissions=True)
        new.append(user)
    if new:
        try:
            frappe.sendmail(recipients=new, subject=f"[SCL] {subject}", message=message,
                            reference_doctype=DLS, reference_name=doc.name, now=False)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "sungas.trip_auto_close email")
    return new


def _close_tasks(doc):
    for name in frappe.get_all("ToDo", filters={"reference_type": DLS, "reference_name": doc.name,
                                                "status": "Open"}, or_filters=[
            ["description", "like", f"%{TAG_STALE}%"], ["description", "like", f"%{TAG_SETTLE}%"]],
            pluck="name"):
        frappe.db.set_value("ToDo", name, "status", "Closed")


def try_auto_close(ls: str) -> dict:
    if not frappe.db.exists(DLS, ls):
        return {"closed": False, "pending": ["not found"]}
    doc = frappe.get_doc(DLS, ls)
    if doc.get("state") != "Dispatched":
        return {"closed": False, "pending": [f"state {doc.get('state')}"]}
    st = reconcile_status(doc)
    if not st["ready"]:
        return {"closed": False, "pending": st["pending"]}
    cases = open_cases(doc)
    _mark_waiting(doc, cases)
    if cases:
        return {"closed": False, "waiting_case": True, "pending": [f"case {c} still open" for c in cases]}
    if _settlement_pending(doc):
        _task(FINANCE_ROLES, doc, TAG_SETTLE,
              f"Trip {doc.name} is fully delivered - settle trip costs so it can close",
              f"<p>Every drop on <b>{doc.name}</b> ({doc.get('truck_no')}) is received. Open the trip and "
              "click <b>Actions &rarr; Settle Trip Costs</b>; it will close itself straight after.</p>")
        return {"closed": False, "pending": ["trip costs not settled"]}
    doc.state = "Closed"
    doc.auto_closed_at = now_datetime()
    doc.save(ignore_permissions=True)
    doc.add_comment("Info", "<b>[Trip Auto-Close]</b> Every drop received and every case resolved -- trip closed automatically.")
    _close_tasks(doc)
    return {"closed": True, "pending": []}


def _safe_try(ls):
    try:
        return try_auto_close(ls)
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"sungas.trip_auto_close {ls}")


def _enqueue(ls):
    frappe.enqueue("sungas.overrides.trip_auto_close.run_one", queue="short",
                   ls=ls, enqueue_after_commit=True)


def run_one(ls: str):
    _safe_try(ls)
    frappe.db.commit()


def on_stock_entry_submit(doc, method=None):
    # Patch 0066: a submitted receipt marks its drop Received (it stayed 'Dispatched').
    if doc.get("outgoing_stock_entry"):
        frappe.db.sql("""update `tabSchedule Drop` set state = 'Received'
                         where receipt_stock_entry = %s and parenttype = %s and state in ('Pending', 'Dispatched')""",
                      (doc.name, DLS))
    found = set()
    if doc.get("loading_schedule"):
        found.add(doc.loading_schedule)
    for ls in frappe.get_all("Schedule Drop", filters={"receipt_stock_entry": doc.name,
                                                      "parenttype": DLS}, pluck="parent"):
        found.add(ls)
    if doc.get("outgoing_stock_entry"):
        found.update(frappe.get_all(DLS, filters={"dispatch_stock_entry": doc.outgoing_stock_entry},
                                    pluck="name"))
    for ls in found:
        _enqueue(ls)


def on_case_closed(doc, method=None):
    """IOVC / TLVC approved or cancelled: re-check the trip(s) it belongs to."""
    ses = {doc.get(f) for _, fields in CASE_LINKS for f in fields if doc.get(f)}
    if not ses:
        return
    trips = set(frappe.get_all(DLS, filters={"dispatch_stock_entry": ["in", list(ses)]}, pluck="name"))
    trips.update(frappe.get_all("Schedule Drop", filters={"receipt_stock_entry": ["in", list(ses)], "parenttype": DLS},
                                pluck="parent"))
    for ls in trips:
        _enqueue(ls)


def on_dls_update(doc, method=None):
    if doc.get("state") == "Dispatched":
        _enqueue(doc.name)


def sweep():
    """Hourly: close any reconciled trip that was missed, flag stale ones to HoO."""
    cutoff = add_to_date(now_datetime(), hours=-STALE_HOURS)
    for row in frappe.get_all(DLS, filters={"state": "Dispatched"},
                              fields=["name", "dispatched_at", "modified"]):
        res = _safe_try(row.name) or {}
        if res.get("closed") or res.get("waiting_case"):
            frappe.db.commit()
            continue
        rolled = get_datetime(row.dispatched_at or row.modified)
        if rolled > cutoff:
            continue
        try:
            doc = frappe.get_doc(DLS, row.name)
            hours = int((now_datetime() - rolled).total_seconds() // 3600)
            items = "".join(f"<li>{p}</li>" for p in res.get("pending") or [])
            _task(HOO_ROLES, doc, TAG_STALE,
                  f"Trip {doc.name} ({doc.get('truck_no')}) still open {hours}h after dispatch",
                  f"<p>Trip <b>{doc.name}</b> from {doc.get('source_outlet')} has not reconciled:</p>"
                  f"<ul>{items}</ul><p>Chase the receipts, or use <b>Force Close Trip</b> if the "
                  "truck cannot reconcile.</p>")
            frappe.db.commit()
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"sungas.trip_auto_close sweep {row.name}")


def install():
    """after_migrate: 'Waiting on case' tag on trips (filterable in the list)."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    try:
        create_custom_fields({DLS: [{
            "fieldname": "waiting_on_case", "fieldtype": "Data", "label": "Waiting on case", "read_only": 1,
            "no_copy": 1, "in_list_view": 1, "in_standard_filter": 1, "insert_after": "auto_closed_at",
            "depends_on": "eval:doc.waiting_on_case",
            "description": "Every drop is received; the trip closes itself once these case(s) are approved (Patch 0058)."}]},
            update=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.trip_auto_close.install")
