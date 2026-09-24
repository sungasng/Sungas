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

    severity = (doc.get("variance_severity") or "").lower()

    # Block/Critical branch: do NOT attempt submit. Instead, transition
    # the Draft to `Pending Plant Manager` via the workflow API. This is
    # equivalent to a Plant Manager clicking "Submit for Approval" on the
    # Desk workflow bar, and it is the ONLY safe way to move workflow
    # state -- direct assignment throws "Workflow State transition not
    # allowed". apply_workflow persists the new state (also docstatus=0)
    # and the workflow then drives the doc through the approval chain
    # (Plant Manager -> HOD Ops -> HOD Finance -> COO -> Approved).
    if severity in ("block", "critical"):
        from frappe.model.workflow import apply_workflow
        tier = "critical" if severity == "critical" else "block"
        # Reload to get the freshly-persisted state before applying the
        # workflow action.
        doc = frappe.get_doc("POS Closing Shift", doc.name)
        doc.flags.ignore_permissions = True
        try:
            apply_workflow(doc, "Submit for Approval")
        except Exception:
            # If the transition fails (e.g. cashier lacks LPG POS User
            # role, or workflow condition rejected), the Draft is still
            # persisted from the commit above -- Plant Manager can open
            # it in Desk and drive it manually.
            frappe.log_error(
                frappe.get_traceback(),
                "sungas.submit_closing_shift apply_workflow failed",
            )
            frappe.msgprint(
                frappe._(
                    "Variance on this shift exceeds the {0} threshold. "
                    "Draft <b>{1}</b> has been saved but the automatic "
                    "workflow submission failed. Please ask your Plant "
                    "Manager to open "
                    "<a href='/app/pos-closing-shift/{1}'>{1}</a> and "
                    "click 'Submit for Approval'."
                ).format(tier, doc.name),
                title=frappe._("Shift Saved -- Manual Routing Required"),
                indicator="orange",
            )
            return doc.name
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

    return doc.name
