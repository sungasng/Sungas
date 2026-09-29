"""GIT Ageing Cron (Wave P-2, Feb 2026).

Runs hourly. Finds Draft Material Receipt Stock Entries that were
spawned from a GIT warehouse but haven't been submitted within
`Sungas Procurement Policy.git_stale_hours` (default 72).

For each stale SE, opens a High-priority ToDo for a holder of the
`git_reviewer_role` (default: LPG Head of Operations). Idempotent -- if
a ToDo already exists for the same SE it is not re-opened.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime


_POLICY_DOCTYPE = "Sungas Procurement Policy"


def run() -> None:
    """Cron entry point. Never throws."""
    try:
        _run()
    except Exception:
        frappe.log_error(
            title="git_ageing cron failed",
            message=frappe.get_traceback(),
        )


def _run() -> None:
    if not frappe.db.exists("DocType", _POLICY_DOCTYPE):
        return

    cfg = frappe.get_single(_POLICY_DOCTYPE).get_git()
    if not cfg["enabled"]:
        return

    stale_before = add_to_date(now_datetime(), hours=-cfg["stale_hours"])

    stale = _find_stale(stale_before)
    if not stale:
        return

    reviewer = _pick_reviewer(cfg["reviewer_role"])
    if not reviewer:
        frappe.log_error(
            title="git_ageing: no reviewer available",
            message=f"Found {len(stale)} stale GIT SE(s) but no user "
                    f"holds role '{cfg['reviewer_role']}'.",
        )
        return

    for se_name in stale:
        _open_todo_if_new(se_name, reviewer, cfg["stale_hours"])


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #

def _find_stale(stale_before) -> list[str]:
    """Return Draft SE names whose GIT source has been idle past threshold.

    Query: Stock Entry that is Draft (docstatus=0) with any item row
    whose source warehouse name contains 'GIT' AND was created before
    the stale_before cutoff.
    """
    rows = frappe.db.sql(
        """
        SELECT DISTINCT se.name
        FROM `tabStock Entry` se
        JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
        WHERE se.docstatus = 0
          AND se.creation < %s
          AND (
            sed.s_warehouse LIKE '%%GIT%%'
            OR se.from_warehouse LIKE '%%GIT%%'
          )
        """,
        (stale_before,),
    )
    return [r[0] for r in rows]


def _pick_reviewer(role: str) -> str | None:
    users = frappe.get_all(
        "Has Role",
        filters={"role": role, "parenttype": "User"},
        fields=["parent"],
        limit=1,
    )
    return users[0].parent if users else None


# --------------------------------------------------------------------------- #
# ToDo creation (idempotent)
# --------------------------------------------------------------------------- #

def _open_todo_if_new(se_name: str, reviewer: str, threshold_hours: int) -> None:
    already = frappe.db.exists(
        "ToDo",
        {
            "reference_type": "Stock Entry",
            "reference_name": se_name,
            "status": "Open",
            "allocated_to": reviewer,
        },
    )
    if already:
        return

    description = _(
        "Stock Entry <b>{se}</b> has been sitting in Draft for over "
        "<b>{hrs} hours</b> with stock parked in a GIT warehouse. "
        "Please investigate and either submit the receipt or cancel "
        "and reconcile the source."
    ).format(se=se_name, hrs=threshold_hours)

    frappe.get_doc({
        "doctype": "ToDo",
        "reference_type": "Stock Entry",
        "reference_name": se_name,
        "allocated_to": reviewer,
        "description": description,
        "priority": "High",
        "status": "Open",
    }).insert(ignore_permissions=True)

    frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Info",
        "reference_doctype": "Stock Entry",
        "reference_name": se_name,
        "content": _("[GIT Ageing] Flagged after {hrs}h idle. "
                     "ToDo assigned to {user}.").format(
            hrs=threshold_hours, user=reviewer,
        ),
    }).insert(ignore_permissions=True)
