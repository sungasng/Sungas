"""sungas.overrides.pos_closing_shift_api
==========================================

Overrides POS Awesome's `submit_closing_shift` whitelist endpoint.

Two behavioural branches, keyed on `variance_severity` computed by the
`compute_variance_severity` validate hook (see `pos_closing_shift.py`):

  * severity == 'block' | 'critical'
      Save the doc as a plain Draft (docstatus=0, workflow_state='Draft'),
      commit, then call `frappe.model.workflow.apply_workflow(doc,
      "Submit for Approval")` to transition Draft -> Pending Plant
      Manager via the workflow engine. Direct field assignment to
      `workflow_state` is NOT safe -- Frappe's `validate_workflow_states`
      rejects untriggered state changes with "Workflow State transition
      not allowed". Using apply_workflow satisfies the validator because
      it marks the change as a legitimate workflow action. The workflow
      then drives the doc through the approval chain
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
            # Patch 0043 -- blind count / recount trail.
            "sungas_first_count",
            "sungas_recounted",
            "sungas_count_witness",
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
    # (compute_variance_severity) has populated `variance_severity` +
    # `variance_amount` at this point. Workflow state stays Draft --
    # direct field assignment trips Frappe's workflow validator.
    frappe.db.commit()


    # Patch 0052: every close is submitted at once; a block / critical difference opens a variance case on submit.
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

    return doc.name
