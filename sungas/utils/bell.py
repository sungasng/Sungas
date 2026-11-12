"""Patch 0018 -- in-app bell alerts (Notification Log, type "Alert").

Every Sungas alert that already goes out by email now also lands in the
ERPNext bell (desktop + mobile pop-up via realtime). Type "Alert" never
sends its own email, so existing email delivery is unchanged.

Entry points:
  ring()               -- explicit alert to users / emails / {"email":..} dicts
  on_todo_insert()     -- ToDo after_insert: bell for direct ToDo inserts
  on_workflow_change() -- "*" doc hook: bell next approvers on workflow moves
"""
from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now_datetime, strip_html

SKIP_USERS = {"Administrator", "Guest", ""}
DEDUPE_MINUTES = 10


def _user_ids(recipients) -> list[str]:
    out: list[str] = []
    for r in recipients or []:
        key = (r.get("email") if isinstance(r, dict) else r) or ""
        key = key.strip()
        if key in SKIP_USERS:
            continue
        row = frappe.db.get_value(
            "User", key, ["name", "enabled", "user_type"], as_dict=True
        ) or frappe.db.get_value(
            "User", {"email": key}, ["name", "enabled", "user_type"], as_dict=True
        )
        if row and row.enabled and row.user_type == "System User" and row.name not in out:
            out.append(row.name)
    return out


def _recent(user, subject, doctype, docname, any_subject=False) -> bool:
    filters = {"for_user": user, "creation": (">", add_to_date(now_datetime(), minutes=-DEDUPE_MINUTES))}
    if doctype and docname:
        filters.update({"document_type": doctype, "document_name": docname})
    if not any_subject or not (doctype and docname):
        filters["subject"] = subject
    return bool(frappe.db.exists("Notification Log", filters))


def _short(text: str, n: int = 240) -> str:
    text = " ".join(strip_html(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "\u2026"


def ring(recipients, subject, message="", doctype=None, docname=None,
         from_user=None, any_subject_dedupe=False) -> int:
    """Create one bell alert per resolved user. Never raises."""
    sent = 0
    try:
        subject = _short(subject, 140)
        for user in _user_ids(recipients):
            if user == from_user or _recent(user, subject, doctype, docname, any_subject_dedupe):
                continue
            frappe.get_doc({
                "doctype": "Notification Log",
                "type": "Alert",
                "for_user": user,
                "from_user": from_user if from_user not in SKIP_USERS else None,
                "subject": subject,
                "email_content": message or subject,
                "document_type": doctype,
                "document_name": docname,
            }).insert(ignore_permissions=True)
            sent += 1
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.bell.ring")
    return sent


# -- ToDo -------------------------------------------------------------------

def _from_assign_to() -> bool:
    import inspect

    return any(f.filename.replace("\\", "/").endswith("desk/form/assign_to.py")
               for f in inspect.stack(0)[:15])


def on_todo_insert(doc, method=None):
    if frappe.flags.in_migrate or frappe.flags.in_install or frappe.flags.in_import:
        return
    if _from_assign_to():
        return  # frappe.desk.form.assign_to already notifies the assignee
    frappe.enqueue("sungas.utils.bell.ring_for_todo", queue="short",
                   todo=doc.name, enqueue_after_commit=True)


def ring_for_todo(todo: str):
    t = frappe.db.get_value(
        "ToDo", todo,
        ["allocated_to", "reference_type", "reference_name", "description", "status", "assigned_by"],
        as_dict=True,
    )
    if not t or t.status != "Open" or not t.allocated_to:
        return
    ref = f"{t.reference_type} {t.reference_name}" if t.reference_type else "Task"
    # any_subject dedupe: assign_to.add() already rang the bell for this doc.
    ring([t.allocated_to], f"New task \u2014 {ref}: {_short(t.description, 90)}",
         t.description, t.reference_type, t.reference_name,
         from_user=t.assigned_by, any_subject_dedupe=True)


# -- Workflow ---------------------------------------------------------------

def on_workflow_change(doc, method=None):
    if frappe.flags.in_migrate or frappe.flags.in_install or frappe.flags.in_import \
            or frappe.flags.in_patch:
        return
    if doc.doctype in ("Notification Log", "ToDo", "Version", "Comment", "Workflow Action"):
        return
    state = doc.get("workflow_state")
    if not state or not doc.has_value_changed("workflow_state"):
        return
    frappe.enqueue("sungas.utils.bell.ring_workflow", queue="short",
                   doctype=doc.doctype, name=doc.name, state=state,
                   actor=frappe.session.user, enqueue_after_commit=True)


def ring_workflow(doctype: str, name: str, state: str, actor: str):
    from frappe.model.workflow import get_workflow_name
    from frappe.workflow.doctype.workflow_action.workflow_action import (
        get_next_possible_transitions,
        get_users_next_action_data,
    )

    if not frappe.db.exists(doctype, name):
        return
    doc = frappe.get_doc(doctype, name)
    if doc.get("workflow_state") != state:
        return
    workflow = get_workflow_name(doctype)
    if not workflow:
        return
    transitions = get_next_possible_transitions(workflow, state, doc)
    label = f"{doctype} {name}"
    from sungas.utils import whatsapp

    if transitions:
        for user, data in get_users_next_action_data(transitions, doc).items():
            actions = sorted({a.action_name for a in data.possible_actions})
            ring([user], f"Action needed \u2014 {label} is '{state}' ({' / '.join(actions)})",
                 f"<p><b>{label}</b> moved to <b>{state}</b>. You can: {', '.join(actions)}.</p>",
                 doctype, name, from_user=actor)
            if user != actor:
                whatsapp.workflow_alert(doctype, name, [user], state, actions, actor)
    elif doc.owner and doc.owner != actor:
        ring([doc.owner], f"Update \u2014 your {label} is now '{state}'",
             f"<p><b>{label}</b> reached <b>{state}</b>.</p>", doctype, name, from_user=actor)
        whatsapp.workflow_update(doctype, name, doc.owner, state)
