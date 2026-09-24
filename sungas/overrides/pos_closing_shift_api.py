"""sungas.overrides.pos_closing_shift_api
==========================================

Overrides POS Awesome's `submit_closing_shift` whitelist endpoint.

Two behavioural branches, keyed on `variance_severity` computed by the
`compute_variance_severity` validate hook (see `pos_closing_shift.py`):

  * severity == 'block' | 'critical'
      Save as Draft in `Pending Plant Manager` state and RETURN. Do NOT
      call `doc.submit()`. Reason: the POS Closing Shift Variance workflow
      does not permit a direct `Draft -> Approved` transition, so any
      submit attempt from Draft throws WorkflowStateError which rolls back
      the entire request even after `frappe.db.commit()`. The draft is
      instead driven forward through the sequential workflow
      (Plant Manager -> HOD Ops -> HOD Finance -> COO -> Approved) via
      the Desk workflow bar. Cashier sees a friendly routing message.

  * severity in ('none', 'warn', 'notice') or unset
      Standard save + submit. `before_submit` (validate_variance) still
      enforces remarks/approver on warn tier; anything harder cannot land
      here because we've already forked above.

Regression: `test_sungas_pos_close_block_tier_autoroute.py`.
"""
from __future__ import annotations

import json

import frappe


@frappe.whitelist()
def submit_closing_shift(closing_shift):
    """Drop-in replacement for posawesome's submit_closing_shift.

    Returns: the doc name (either the persisted Draft awaiting approval,
    or the freshly-submitted Approved doc).
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

    # Persist the draft regardless of what happens next. The validate hook
    # (compute_variance_severity) has already populated
    # `variance_severity` + `workflow_state` at this point.
    frappe.db.commit()

    severity = (doc.get("variance_severity") or "").lower()

    # Block/Critical branch: do NOT attempt submit. The workflow forbids
    # Draft -> Approved directly, and any throw here would rollback even
    # after commit in some Frappe versions. The draft is now sitting in
    # `Pending Plant Manager` for the approval chain to pick up.
    if severity in ("block", "critical"):
        tier = "critical" if severity == "critical" else "block"
        frappe.msgprint(
            frappe._(
                "Variance on this shift exceeds the {0} threshold and cannot "
                "be closed directly. Draft <b>{1}</b> has been saved and "
                "routed to your Plant Manager for approval. "
                "Track progress at "
                "<a href='/app/pos-closing-shift/{1}'>{1}</a>."
            ).format(tier, doc.name),
            title=frappe._("Shift Routed to Plant Manager"),
            indicator="orange",
        )
        return doc.name

    # Warn / notice / none: standard submit path. `before_submit`
    # (validate_variance) still enforces remarks etc. on warn tier.
    try:
        doc.submit()
    except frappe.exceptions.ValidationError:
        # Surface a friendlier follow-up note so the cashier knows where
        # the draft went. (Warn-tier: remarks missing -> cashier retries
        # with remarks; draft above is durable via the commit.)
        frappe.msgprint(
            frappe._(
                "Draft <b>{0}</b> has been saved. Please address the "
                "validation issue above and re-submit from "
                "<a href='/app/pos-closing-shift/{0}'>{0}</a>."
            ).format(doc.name),
            title=frappe._("Shift Draft Saved"),
            indicator="orange",
        )
        raise
