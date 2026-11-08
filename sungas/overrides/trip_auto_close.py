"""Patch 0019 -- natural auto-close for Daily Loading Schedule trips.

A Dispatched trip closes itself once it is fully reconciled:
  * the dispatch Stock Entry is submitted,
  * every drop's receipt Stock Entry is submitted (or the drop was marked
    Rejected / Rescheduled), and
  * no Draft receipt is still hanging off the dispatch.
Shortfalls are already owned by the IOVC opened on the last receipt, so
nothing is force-closed here. If Patch 0016 requires trip-cost settlement,
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
    if _settlement_pending(doc):
        _task(FINANCE_ROLES, doc, TAG_SETTLE,
              f"Trip {doc.name} is fully delivered - settle trip costs so it can close",
              f"<p>Every drop on <b>{doc.name}</b> ({doc.get('truck_no')}) is received. Open the trip and "
              "click <b>Actions &rarr; Settle Trip Costs</b>; it will close itself straight after.</p>")
        return {"closed": False, "pending": ["trip costs not settled"]}
    doc.state = "Closed"
    doc.auto_closed_at = now_datetime()
    doc.save(ignore_permissions=True)
    doc.add_comment("Info", "<b>[Trip Auto-Close]</b> Every drop received and reconciled -- trip closed automatically.")
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


def on_dls_update(doc, method=None):
    if doc.get("state") == "Dispatched":
        _enqueue(doc.name)


def sweep():
    """Hourly: close any reconciled trip that was missed, flag stale ones to HoO."""
    cutoff = add_to_date(now_datetime(), hours=-STALE_HOURS)
    for row in frappe.get_all(DLS, filters={"state": "Dispatched"},
                              fields=["name", "dispatched_at", "modified"]):
        res = _safe_try(row.name) or {}
        if res.get("closed"):
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
