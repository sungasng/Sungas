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
    # Patch 0043: POS Awesome stores the shift in posa_pos_opening_shift -- the seal never fired before.
    opening_shift = (
        doc.get("posa_pos_opening_shift")
        or doc.get("pos_opening_entry")
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
        _block_old_shift(opening_shift)
        return

    # Patch 0044: plain words for the cashier.
    frappe.throw(
        _("Your last shift close ({0}) has a cash difference that is waiting for approval ({1}). "
          "You cannot sell until it is approved.<br><br>"
          "Please tell your Plant Manager. To keep the outlet selling, another cashier can log in and open "
          "their own shift.").format(pending_close.name, pending_close.workflow_state.replace("Pending ", "with ")),
        title=_("Till locked - waiting for approval"),
    )


def _block_old_shift(opening_shift):
    """Patch 0043: a shift sells only on the business day it was opened."""
    start = frappe.db.get_value("POS Opening Shift", opening_shift, "period_start_date")
    if start and frappe.utils.getdate(start) < frappe.utils.getdate(frappe.utils.nowdate()):
        frappe.throw(
            _("This shift ({0}) was opened on {1}. A shift can only sell on the day it was opened - close it "
              "(Menu > Close Shift) and open today's shift.").format(
                opening_shift, frappe.utils.formatdate(start)),
            title=_("Close yesterday's shift first"),
        )
