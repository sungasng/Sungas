"""Patch 0024 -- 7 AM (Africa/Lagos) morning briefing for managers.

Each manager with something pending gets one bell alert and one email
listing the approvals waiting on them and their open tasks. Nobody gets an
empty briefing. Idempotent per user per day.
"""
from __future__ import annotations

import frappe
from frappe.utils import escape_html, get_url, nowdate

MANAGER_ROLES = ("LPG Head of Operations", "LPG Head of Finance", "LPG Plant Manager",
                 "Purchase Manager", "Accounts Manager", "Stock Manager", "COO")
TAG = "Morning briefing"
MAX_ROWS = 15


def subject(n_approvals: int, n_tasks: int) -> str:
    return f"{TAG} - {n_approvals} approval(s), {n_tasks} task(s) waiting"


def _link(doctype: str, name: str) -> str:
    return get_url(f"/app/{frappe.scrub(doctype).replace('_', '-')}/{name}")


def _section(title: str, rows: list[tuple[str, str, str]]) -> str:
    if not rows:
        return ""
    items = "".join(f'<li><a href="{_link(dt, dn)}">{escape_html(dt)} {escape_html(dn)}</a> - {escape_html(note)}</li>'
                    for dt, dn, note in rows[:MAX_ROWS])
    more = f"<p>... and {len(rows) - MAX_ROWS} more.</p>" if len(rows) > MAX_ROWS else ""
    return f"<h4>{title} ({len(rows)})</h4><ul>{items}</ul>{more}"


def _managers() -> list[str]:
    users = frappe.get_all("Has Role", filters={"role": ["in", list(MANAGER_ROLES)], "parenttype": "User"},
                           pluck="parent", distinct=True)
    return [u for u in users if u not in ("Administrator", "Guest")
            and frappe.db.get_value("User", u, ["enabled", "user_type"]) == (1, "System User")]


def _open_actions() -> list[dict]:
    acts = frappe.get_all("Workflow Action", filters={"status": "Open"},
                          fields=["name", "reference_doctype", "reference_name", "workflow_state", "user"])
    roles = {}
    for r in frappe.get_all("Workflow Action Permitted Role", filters={"parent": ["in", [a.name for a in acts] or [""]]},
                            fields=["parent", "role"]):
        roles.setdefault(r.parent, set()).add(r.role)
    for a in acts:
        a.roles = roles.get(a.name, set())
    return acts


def _approvals_for(user: str, user_roles: set, acts: list[dict]) -> list[tuple[str, str, str]]:
    out, seen = [], set()
    for a in acts:
        key = (a.reference_doctype, a.reference_name)
        if key in seen or not (a.user == user or a.roles & user_roles):
            continue
        if not frappe.db.exists(*key) or not frappe.has_permission(a.reference_doctype, "read", doc=a.reference_name, user=user):
            continue
        seen.add(key)
        out.append((a.reference_doctype, a.reference_name, f"waiting at '{a.workflow_state}'"))
    return out


def _tasks_for(user: str) -> list[tuple[str, str, str]]:
    rows = frappe.get_all("ToDo", filters={"allocated_to": user, "status": "Open"},
                          fields=["name", "reference_type", "reference_name", "description", "priority"],
                          order_by="creation asc")
    rank = {"High": 0, "Medium": 1, "Low": 2}
    rows.sort(key=lambda t: rank.get(t.priority, 1))
    return [(t.reference_type or "ToDo", t.reference_name or t.name,
             frappe.utils.strip_html(t.description or "")[:120]) for t in rows]


def _sent_today(user: str) -> bool:
    return bool(frappe.db.exists("Notification Log", {
        "for_user": user, "subject": ["like", f"{TAG}%"], "creation": [">=", f"{nowdate()} 00:00:00"]}))


def run() -> dict:
    from sungas.utils.bell import ring

    summary = {"managers": 0, "briefed": 0}
    acts = _open_actions()
    for user in _managers():
        summary["managers"] += 1
        if _sent_today(user):
            continue
        approvals = _approvals_for(user, set(frappe.get_roles(user)), acts)
        tasks = _tasks_for(user)
        if not approvals and not tasks:
            continue
        subj = subject(len(approvals), len(tasks))
        body = (f"<p>Good morning. Here is what is waiting for you today.</p>"
                f"{_section('Approvals waiting on you', approvals)}{_section('Your open tasks', tasks)}")
        ring([user], subj, body)
        try:
            frappe.sendmail(recipients=[frappe.db.get_value("User", user, "email") or user],
                            subject=f"[SCL] {subj}", message=body, now=False)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "sungas.morning_briefing email")
        summary["briefed"] += 1
        frappe.db.commit()
    return summary
