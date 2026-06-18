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
    """Spawn an Annex T-07 draft if the variance has just become hard."""
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
        }).insert(ignore_permissions=True)
        frappe.db.set_value(
            "POS Closing Shift", doc.name, "annex_t07", worksheet.name, update_modified=False
        )
        # Defer commit to the surrounding save; on_update is inside the
        # transaction so explicit commit here would be premature.
    except Exception as exc:
        frappe.log_error(
            f"auto_create_t07 failed for {doc.name}: {exc}",
            "Sungas Annex T-07",
        )


def require_t07_for_hard_variance(doc, method=None) -> None:
    """Block POS Closing Shift submit until T-07 is submitted (hard variance only)."""
    sev = (doc.get("variance_severity") or "").lower()
    if sev not in HARD_SEVERITIES:
        return  # soft / no-variance: nothing to enforce

    annex = doc.get("annex_t07")
    if not annex:
        frappe.throw(
            _(
                "This shift has a {severity} variance. Annex T-07 worksheet must be "
                "created and submitted before the shift can be approved. "
                "The worksheet is normally auto-created when the variance is detected; "
                "re-save the shift to spawn one if it's missing."
            ).format(severity=sev),
            title=_("Annex T-07 Required"),
        )

    docstatus = frappe.db.get_value("Annex T-07 Worksheet", annex, "docstatus")
    if docstatus != 1:
        frappe.throw(
            _(
                "Annex T-07 worksheet {annex} must be SUBMITTED (docstatus=1) before "
                "this shift can be approved. Current docstatus = {ds}."
            ).format(annex=annex, ds=docstatus),
            title=_("Annex T-07 Not Yet Submitted"),
        )
