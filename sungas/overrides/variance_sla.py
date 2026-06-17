"""sungas.overrides.variance_sla
=================================

Tracks how long a `POS Closing Shift` has sat in a ``Pending *`` workflow
state, so the daily SLA breach scheduler can fire escalation emails.

We expose **one cheap hook**:

    ``track_state_entry(doc, method)`` — wired into ``doc_events["POS Closing Shift"]["on_update"]``.

The hook compares the current ``workflow_state`` to the snapshot in
``doc.get_doc_before_save()`` and, if the state changed, stamps
``variance_state_entered_at`` with ``now_datetime()`` and resets the SLA
escalation markers. This keeps the implementation O(1) per save with no
extra DB round-trips on writes that don't touch the workflow state.
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe.utils import now_datetime


# States that count as "waiting on a human" for SLA purposes.
SLA_PENDING_PREFIX = "Pending"


def track_state_entry(doc, method=None) -> None:  # type: ignore[no-untyped-def]
    """Snapshot the moment a POS Closing Shift enters a new workflow state."""
    new_state = doc.get("workflow_state") or ""
    if not new_state:
        return

    before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
    old_state = (before.get("workflow_state") if before else None) or ""

    if new_state == old_state:
        return

    # Only track entries into Pending states; clear markers on leaving them.
    if new_state.startswith(SLA_PENDING_PREFIX):
        doc.db_set("variance_state_entered_at", now_datetime(), update_modified=False)
        doc.db_set("variance_sla_escalated_at", None, update_modified=False)
        doc.db_set("variance_sla_escalation_level", 0, update_modified=False)
    else:
        # Approved / Rejected / Draft — clear the timer so we don't fire stale alerts.
        doc.db_set("variance_state_entered_at", None, update_modified=False)


def list_breached_shifts(sla_hours: int, breach_hours: int) -> list[dict]:
    """Return Pending POS Closing Shifts that have breached the SLA.

    Args:
        sla_hours: L1 breach threshold (default 48h).
        breach_hours: L2 breach threshold (default 72h).

    Returns one row per breached shift with the fields the scheduler needs.
    """
    cutoff = frappe.utils.add_to_date(now_datetime(), hours=-sla_hours, as_datetime=True)
    rows = frappe.db.sql(
        """
        SELECT name, pos_profile, workflow_state, variance_severity,
               variance_state_entered_at,
               COALESCE(variance_sla_escalation_level, 0) AS variance_sla_escalation_level
        FROM `tabPOS Closing Shift`
        WHERE docstatus = 0
          AND workflow_state LIKE %(prefix)s
          AND variance_state_entered_at IS NOT NULL
          AND variance_state_entered_at <= %(cutoff)s
        ORDER BY variance_state_entered_at ASC
        LIMIT 200
        """,
        {"prefix": f"{SLA_PENDING_PREFIX}%", "cutoff": cutoff},
        as_dict=True,
    )
    return rows
