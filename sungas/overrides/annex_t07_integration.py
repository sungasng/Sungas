"""sungas.overrides.annex_t07_integration
==========================================

Wave D-5: glue between POS Closing Shift and the Annex T-07 Worksheet.

Provides two hooks:

    auto_create_t07(doc, method=None)
        Runs on `on_update` of POS Closing Shift. When a shift's
        variance_severity hits "block" or "critical" and no T-07 is
        linked yet, spawn an empty draft worksheet and stamp the link
        back onto the shift. Idempotent.

    require_t07_for_hard_variance(doc, method=None)
        Runs on `before_submit` of POS Closing Shift. Blocks final
        submission of a hard variance until the linked T-07 worksheet
        has been submitted (docstatus=1). Allows soft / no-variance
        shifts to submit freely (no T-07 needed).
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe import _


HARD_SEVERITIES = ("block", "critical")


def auto_create_t07(doc, method=None) -> None:
    """Spawn an Annex T-07 draft if the variance has just become hard.

    Uses ignore_mandatory on insert because the Annex T-07 has several
    reqd=1 narrative fields (primary_cause, corrective_action,
    cashier_statement) that will be filled in by the cashier /
    investigator AT SUBMIT time -- not now. Without ignore_mandatory the
    insert throws MandatoryError silently (caught below) and the shift
    ends up with no linked worksheet, breaking the T-07 gate at approval.
    """
    if doc.docstatus != 0:
        return  # only relevant pre-submit
    sev = (doc.get("variance_severity") or "").lower()
    if sev not in HARD_SEVERITIES:
        return
    if doc.get("annex_t07"):
        return  # already linked
    # Avoid spawning if a worksheet exists from a previous attempt
    # (e.g. cashier saved + walked away; auto-create ran; then the
    # shift name was reused via amend). Search by shift link.
    existing = frappe.db.get_value(
        "Annex T-07 Worksheet",
        {"shift": doc.name, "docstatus": ["!=", 2]},
        "name",
    )
    if existing:
        frappe.db.set_value(
            "POS Closing Shift", doc.name, "annex_t07", existing, update_modified=False
        )
        return

    try:
        worksheet = frappe.get_doc({
            "doctype": "Annex T-07 Worksheet",
            "shift": doc.name,
            # Stamp fetched values explicitly so they land on the draft
            # even before the linked-doc fetch runs.
            "variance_severity": doc.get("variance_severity"),
            "variance_amount": doc.get("variance_amount"),
            "pos_profile": doc.get("pos_profile"),
            "cashier": doc.get("user"),
            "period_end_date": doc.get("period_end_date"),
        }).insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.db.set_value(
            "POS Closing Shift", doc.name, "annex_t07", worksheet.name, update_modified=False
        )
        # Defer commit to the surrounding save; on_update is inside the
        # transaction so explicit commit here would be premature.
    except Exception as exc:
        frappe.log_error(
            f"auto_create_t07 failed for {doc.name}: {exc}\n{frappe.get_traceback()}",
            "Sungas Annex T-07",
        )


def require_t07_for_hard_variance(doc, method=None) -> None:
    """Block POS Closing Shift submit until T-07 is submitted (hard variance only).

    Includes a self-healing retry: if the T-07 link is missing when
    submit is attempted, try to auto-create it one more time before
    throwing. This handles shifts saved before the ignore_mandatory
    fix landed (their auto-create silently failed and left annex_t07
    blank).
    """
    sev = (doc.get("variance_severity") or "").lower()
    if sev not in HARD_SEVERITIES:
        return  # soft / no-variance: nothing to enforce

    annex = doc.get("annex_t07")
    if not annex:
        # Self-heal: attempt auto-create one more time (uses the fixed
        # ignore_mandatory=True path). If successful, refresh annex.
        auto_create_t07(doc)
        annex = frappe.db.get_value("POS Closing Shift", doc.name, "annex_t07")

    if not annex:
        frappe.throw(
            _(
                "This shift has a {severity} variance. Annex T-07 worksheet "
                "must be created and submitted before the shift can be "
                "approved. The auto-create hook could not spawn one -- ask "
                "an ERP admin to check the Error Log for 'Sungas Annex T-07'."
            ).format(severity=sev),
            title=_("Annex T-07 Required"),
        )

    docstatus = frappe.db.get_value("Annex T-07 Worksheet", annex, "docstatus")
    if docstatus != 1:
        frappe.throw(
            _(
                "Annex T-07 worksheet <a href='/app/annex-t-07-worksheet/{annex}'>"
                "{annex}</a> must be SUBMITTED before this shift can be approved. "
                "Current docstatus = {ds}. Open the worksheet, fill in Primary "
                "Cause, Corrective Action, Cashier Statement, and at least one "
                "denomination row, then click Submit."
            ).format(annex=annex, ds=docstatus),
            title=_("Annex T-07 Not Yet Submitted"),
        )
