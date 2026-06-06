"""sungas.overrides.pos_closing_shift_api
==========================================

Overrides POS Awesome's `submit_closing_shift` whitelist endpoint so that
the closing-shift DRAFT is committed BEFORE submit is attempted.

Why:
  Upstream POS Awesome does `save(); submit()` in a single transaction.
  When our Sungas Close Policy `before_submit` hook throws a
  ValidationError (e.g. variance > block threshold and no approver set),
  Frappe rolls back the ENTIRE transaction -- including the `save()`.
  Result: the cashier sees the variance error, but no draft is left
  behind for the approver to act on.

Fix:
  We commit after save so the draft persists. If submit then throws,
  the throw is re-raised to the frontend AS-IS (cashier sees the same
  variance message), but the draft is now visible in:
    /app/pos-closing-shift?docstatus=0
  for the approver to open, set `variance_approved_by` + `variance_remarks`,
  and save. Cashier (or anyone with submit perm) then submits the draft
  from Desk to fire on_submit and post the variance JE.
"""
from __future__ import annotations

import json

import frappe


@frappe.whitelist()
def submit_closing_shift(closing_shift):
    """Drop-in replacement for posawesome's submit_closing_shift.

    Behaviour:
      1. Parse + insert (or update if a name is provided) the doc.
      2. Commit so the draft survives any later throw.
      3. Attempt submit. Any exception (incl. before_submit variance block)
         is re-raised; draft remains intact for the approver.

    Returns: the doc name when submit succeeds.
    """
    payload = json.loads(closing_shift) if isinstance(closing_shift, str) else closing_shift

    # If a doc with this opening shift already has a draft, reuse it
    # instead of creating a duplicate. This makes the call idempotent if
    # the cashier hits Submit twice.
    existing_name = None
    opening_shift = payload.get("pos_opening_shift")
    if opening_shift and not payload.get("name"):
        existing_name = frappe.db.get_value(
            "POS Closing Shift",
            {"pos_opening_shift": opening_shift, "docstatus": 0},
            "name",
        )

    if existing_name:
        # Re-hydrate the existing draft with the new dialog values.
        doc = frappe.get_doc("POS Closing Shift", existing_name)
        # Update simple top-level fields the dialog can change.
        for f in (
            "period_end_date",
            "grand_total",
            "net_total",
            "total_quantity",
            "variance_remarks",
        ):
            if f in payload:
                doc.set(f, payload.get(f))
        # Refresh the payment_reconciliation child table.
        if "payment_reconciliation" in payload:
            doc.set("payment_reconciliation", [])
            for row in payload.get("payment_reconciliation") or []:
                doc.append("payment_reconciliation", row)
        if "pos_transactions" in payload:
            doc.set("pos_transactions", [])
            for row in payload.get("pos_transactions") or []:
                doc.append("pos_transactions", row)
        if "taxes" in payload:
            doc.set("taxes", [])
            for row in payload.get("taxes") or []:
                doc.append("taxes", row)
        doc.flags.ignore_permissions = True
        doc.save()
    else:
        doc = frappe.get_doc(payload)
        doc.flags.ignore_permissions = True
        doc.save()

    # Persist the draft regardless of what submit does next.
    frappe.db.commit()

    # Attempt to submit; any throw (variance block, etc.) bubbles up to
    # the frontend, but the draft above is now permanent.
    try:
        doc.submit()
    except frappe.exceptions.ValidationError:
        # Surface a friendlier follow-up note so the cashier knows where
        # the draft went.
        frappe.msgprint(
            frappe._(
                "Draft <b>{0}</b> has been saved and is awaiting approval. "
                "Once an approver fills the 'Variance Approved By' field "
                "via Desk, you (or a manager) can submit it from "
                "<a href='/app/pos-closing-shift/{0}'>{0}</a>."
            ).format(doc.name),
            title=frappe._("Variance Block — Draft Saved"),
            indicator="orange",
        )
        raise

    return doc.name
