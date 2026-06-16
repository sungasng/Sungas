"""sungas.overrides.pos_invoice_seal
=====================================

Refuses to create / submit a POS Invoice on an opening shift that is
currently "sealed" by a pending variance-approval closing shift.

Trigger: when a cashier tries to ring up a new sale on her till AFTER
having attempted to close it with a block/critical variance, this hook
fires and throws -- preventing further sales on the sealed shift.

This implements Path B "shift is sealed pending investigation" from the
Sungas variance protocol. The till's continuity comes from EITHER:
  - Another cashier opening a fresh shift under their own login (B.1)
  - A regional backup POS profile (B.2 -- Phase 5.8, not yet built)
  - The Manual Sales Book (B.3 -- Phase 5.9, not yet built)
"""
from __future__ import annotations

import frappe
from frappe import _


# Workflow states that indicate the shift is sealed awaiting an approver.
_SEALED_WORKFLOW_STATES = (
    "Pending Plant Manager",
    "Pending HOD Operations",
    "Pending HOD Finance",
    "Pending COO",
)


def block_sale_on_sealed_shift(doc, method=None):
    """before_insert (and validate) hook on POS Invoice.

    Reject the new invoice if its linked opening shift has a draft closing
    shift in a Pending workflow state.
    """
    opening_shift = (
        doc.get("pos_opening_entry")
        or doc.get("opening_entry")
        or doc.get("pos_opening_shift")
    )
    if not opening_shift:
        return

    pending_close = frappe.db.get_value(
        "POS Closing Shift",
        {
            "pos_opening_shift": opening_shift,
            "docstatus": 0,
            "workflow_state": ["in", list(_SEALED_WORKFLOW_STATES)],
        },
        ["name", "workflow_state", "variance_severity"],
        as_dict=True,
    )
    if not pending_close:
        return

    frappe.throw(
        _(
            "This opening shift is SEALED pending variance approval "
            "(closing shift {0} is currently in workflow state '{1}', "
            "severity '{2}'). No further sales can be rung up on this till "
            "until the variance is approved (or rejected) by the relevant "
            "manager.\n\n"
            "Outlet continuity options:\n"
            "  - Have a different cashier open a fresh shift under their "
            "own login (preferred).\n"
            "  - Use a regional backup POS profile (Phase 5.8 — not yet "
            "deployed).\n"
            "  - Fall back to the Manual Sales Book (Phase 5.9 — not yet "
            "deployed).\n\n"
            "Approvers can act on the draft at /app/pos-closing-shift/{0}"
        ).format(
            pending_close.name,
            pending_close.workflow_state,
            pending_close.variance_severity or "n/a",
        ),
        title=_("Shift Sealed — Variance Approval Pending"),
    )
