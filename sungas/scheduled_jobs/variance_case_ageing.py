"""Patch 0023 -- overdue alert for open variance cases (TLVC + IOVC).

Daily: any Transit Loss / Inter-Outlet Variance Case still not submitted
OVERDUE_DAYS after it was opened gets one Open ToDo per Head of Operations
and Head of Finance user (bell via Patch 0018) plus one email. Idempotent.
"""
from __future__ import annotations

import frappe
from frappe.utils import add_days, date_diff, nowdate

OVERDUE_DAYS = 13
DOCTYPES = ("Transit Loss Variance Case", "Inter-Outlet Variance Case")
ROLES = ("LPG Head of Operations", "LPG Head of Finance")
TAG = "[Variance Case Overdue]"


def overdue(created_on: str, today: str) -> bool:
    return date_diff(today, created_on) >= OVERDUE_DAYS


def _users():
    users = frappe.get_all("Has Role", filters={"role": ["in", list(ROLES)], "parenttype": "User"},
                           pluck="parent", distinct=True)
    return [u for u in users if u not in ("Administrator", "Guest") and frappe.db.get_value("User", u, "enabled")]


def run() -> dict:
    today = nowdate()
    cutoff = add_days(today, -OVERDUE_DAYS)
    summary = {"checked": 0, "flagged": 0}
    users = _users()
    for dt in DOCTYPES:
        if not frappe.db.exists("DocType", dt):
            continue
        for case in frappe.get_all(dt, filters={"docstatus": 0, "creation": ["<=", f"{cutoff} 23:59:59"]},
                                   fields=["name", "creation", "workflow_state"]):
            summary["checked"] += 1
            age = date_diff(today, str(case.creation)[:10])
            new = []
            for user in users:
                if frappe.db.exists("ToDo", {"reference_type": dt, "reference_name": case.name, "allocated_to": user,
                                             "status": "Open", "description": ["like", f"%{TAG}%"]}):
                    continue
                frappe.get_doc({"doctype": "ToDo", "reference_type": dt, "reference_name": case.name,
                                "allocated_to": user, "priority": "High", "status": "Open",
                                "description": f"<p><b>{TAG}</b> {dt} {case.name} is still "
                                               f"'{case.workflow_state or 'Draft'}' after {age} days.</p>"
                                }).insert(ignore_permissions=True)
                new.append(user)
            if new:
                summary["flagged"] += 1
                try:
                    frappe.sendmail(recipients=new, subject=f"[SCL] {dt} {case.name} overdue ({age} days)",
                                    message=f"<p>{dt} <b>{case.name}</b> has been "
                                            f"'{case.workflow_state or 'Draft'}' for {age} days. Resolve and "
                                            "submit it so the variance leaves the suspense account.</p>",
                                    reference_doctype=dt, reference_name=case.name, now=False)
                except Exception:
                    frappe.log_error(frappe.get_traceback(), "sungas.variance_case_ageing email")
            frappe.db.commit()
    return summary


def fix_iovc_writeoff_account():
    """after_migrate: move the IOVC write-off off the 1609 asset account onto 8600 (P&L)."""
    try:
        acc = frappe.db.get_single_value("Sungas Close Policy", "it_writeoff_account")
        target = "8600 - COS - Transit Loss (LPG) - SCL"
        if acc and frappe.db.get_value("Account", acc, "root_type") != "Expense" \
                and frappe.db.exists("Account", target):
            frappe.db.set_single_value("Sungas Close Policy", "it_writeoff_account", target)
            frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.fix_iovc_writeoff_account")
