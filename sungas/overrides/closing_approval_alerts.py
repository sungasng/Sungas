"""Patch 0044 -- tell the next approver of a closing-shift variance (bell + WhatsApp), and the cashier of the outcome.

Before: the workflow moved (Pending Plant Manager -> HOD Operations -> HOD Finance) but nobody was told -- the
Head of Finance never saw POSA-CS-26-0000018. One alert per closing shift and state (deduped on the bell subject).
"""
from __future__ import annotations

import frappe

STATE_ROLES = {"Pending HOD Operations": ("LPG Head of Operations",), "Pending HOD Finance": ("LPG Head of Finance",),
               "Pending COO": ("COO",)}
WATCHERS = {"Pending HOD Finance": ("Internal Control",)}
SKIP = ("Administrator", "lmd-bot@sungas.org")


def _users(roles):
    return [u for u in frappe.get_all("Has Role", filters={"role": ["in", list(roles)], "parenttype": "User"},
                                      pluck="parent", distinct=True)
            if u not in SKIP and frappe.db.get_value("User", u, "enabled")]


def approvers(doc, state):
    if state == "Pending Plant Manager":
        from sungas.shift_controls import _plant_manager

        wh = frappe.db.get_value("POS Profile", doc.pos_profile, "warehouse")
        pm = _plant_manager(doc.pos_profile, wh)
        return [pm] if pm else _users(("LPG Plant Manager",))
    return _users(STATE_ROLES.get(state, ()))


def on_update(doc, method=None):
    if frappe.flags.in_import or not doc.has_value_changed("workflow_state"):
        return
    frappe.enqueue("sungas.overrides.closing_approval_alerts.send", queue="short", enqueue_after_commit=True,
                   name=doc.name, state=doc.workflow_state)


def send(name, state):
    from sungas.utils import whatsapp
    from sungas.utils.bell import ring

    doc = frappe.get_doc("POS Closing Shift", name)
    if doc.workflow_state != state:
        return
    who = frappe.db.get_value("User", doc.user, "full_name") or doc.user
    plant = (doc.pos_profile or "").replace("POS - ", "")
    diff = sum(frappe.utils.flt(r.closing_amount) - frappe.utils.flt(r.expected_amount)
               for r in doc.payment_reconciliation or [])
    label = f"{who}'s shift close {name} ({plant}, difference NGN {diff:+,.0f}, {doc.variance_severity or '-'})"
    link = whatsapp.doc_url("POS Closing Shift", name)
    if state in ("Approved", "Rejected"):
        subject = f"Your shift close {name} was {state.lower()}"
        if not frappe.db.exists("Notification Log", {"for_user": doc.user, "subject": subject}):
            ring([doc.user], subject, f"<p>{label}: {state}. {'You can open a new shift.' if state == 'Approved' else 'See your Plant Manager.'}</p>",
                 "POS Closing Shift", name)
        return
    subject = f"Approval needed - {label}"
    users = [u for u in approvers(doc, state) if not frappe.db.exists("Notification Log", {"for_user": u, "subject": subject})]
    body = (f"<p>{label} is waiting for you (<b>{state}</b>). The till is locked until it is decided.</p>"
            f"<p>Remarks: {frappe.utils.escape_html(doc.get('variance_remarks') or '-')}</p>"
            f"<p><a href=\"{link}\">Open the closing shift</a> and use <b>Actions</b> to approve, escalate or reject.</p>")
    if users:
        ring(users, subject, body, "POS Closing Shift", name)
        for u in users:
            if whatsapp.phone_for(u):
                whatsapp.send([u], "sungas_approval_needed", {
                    "approver_name": whatsapp.first_name(u), "doc_label": f"Shift close {name}",
                    "summary": f"{who}, {plant}, difference NGN {diff:+,.0f} ({doc.variance_severity})",
                    "state": f"{state} - tap the link, then Actions", "link": link}, ref=f"CS:{name}:{state}")
    watch = [u for u in _users(WATCHERS.get(state, ())) if u not in users]
    if watch:
        ring(watch, f"FYI - {label} now {state}", body, "POS Closing Shift", name)


def backfill():
    """after_migrate: alert approvers of closes already waiting (deduped)."""
    try:
        for r in frappe.get_all("POS Closing Shift", filters={"docstatus": 0, "workflow_state": ["like", "Pending%"]},
                                fields=["name", "workflow_state"]):
            send(r.name, r.workflow_state)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.closing_approval_alerts.backfill")
