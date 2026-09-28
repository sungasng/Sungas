"""sungas.overrides.pos_variance_investigation_integration
=============================================================

Renamed from `annex_t07_integration` (Feb 2026).

Glue between POS Closing Shift and the POS Variance Investigation
doctype. Provides two hooks:

    auto_create_variance_investigation(doc, method=None)
        Runs on `on_update` of POS Closing Shift. When a shift's
        variance_severity hits "block" or "critical" and no
        investigation is linked yet, spawn an empty draft and stamp
        the link back onto the shift. Idempotent.

    require_investigation_for_hard_variance(doc, method=None)
        Runs on `before_submit` of POS Closing Shift. Blocks final
        submission of a hard variance until the linked investigation
        has been submitted (docstatus=1). Soft / no-variance shifts
        submit freely (no investigation needed).
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe import _


HARD_SEVERITIES = ("block", "critical")

# Custom Field on POS Closing Shift that points to the investigation.
LINK_FIELD = "pos_variance_investigation"


def auto_create_variance_investigation(doc, method=None) -> None:
    """Spawn a POS Variance Investigation draft on hard variance.

    Uses ignore_mandatory on insert because the investigation has
    reqd=1 narrative fields (primary_cause, corrective_action,
    cashier_statement) that get filled at submit time -- not now.
    """
    if doc.docstatus != 0:
        return  # only relevant pre-submit
    sev = (doc.get("variance_severity") or "").lower()
    if sev not in HARD_SEVERITIES:
        return
    if doc.get(LINK_FIELD):
        return  # already linked
    # If a worksheet exists from a previous attempt, adopt it.
    existing = frappe.db.get_value(
        "POS Variance Investigation",
        {"shift": doc.name, "docstatus": ["!=", 2]},
        "name",
    )
    if existing:
        frappe.db.set_value(
            "POS Closing Shift", doc.name, LINK_FIELD, existing, update_modified=False
        )
        return

    try:
        investigation = frappe.get_doc({
            "doctype": "POS Variance Investigation",
            "shift": doc.name,
            "variance_severity": doc.get("variance_severity"),
            "variance_amount": doc.get("variance_amount"),
            "pos_profile": doc.get("pos_profile"),
            "cashier": doc.get("user"),
            "period_end_date": doc.get("period_end_date"),
        }).insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.db.set_value(
            "POS Closing Shift", doc.name, LINK_FIELD,
            investigation.name, update_modified=False,
        )
    except Exception as exc:
        frappe.log_error(
            title="Sungas POS Variance Investigation",
            message=(
                f"auto_create_variance_investigation failed for "
                f"{doc.name}: {exc}\n\n{frappe.get_traceback()}"
            ),
        )


def require_investigation_for_hard_variance(doc, method=None) -> None:
    """Block POS Closing Shift submit until investigation is submitted.

    Self-heals: if the link is missing at approval time, retry
    auto-create once before throwing.
    """
    sev = (doc.get("variance_severity") or "").lower()
    if sev not in HARD_SEVERITIES:
        return

    investigation = doc.get(LINK_FIELD)
    if not investigation:
        auto_create_variance_investigation(doc)
        investigation = frappe.db.get_value(
            "POS Closing Shift", doc.name, LINK_FIELD
        )

    if not investigation:
        frappe.throw(
            _(
                "This shift has a {severity} variance. A POS Variance "
                "Investigation must be created and submitted before the "
                "shift can be approved. The auto-create hook could not "
                "spawn one -- ask an ERP admin to check the Error Log "
                "for 'Sungas POS Variance Investigation'."
            ).format(severity=sev),
            title=_("Investigation Required"),
        )

    docstatus = frappe.db.get_value(
        "POS Variance Investigation", investigation, "docstatus"
    )
    if docstatus != 1:
        frappe.throw(
            _(
                "POS Variance Investigation "
                "<a href='/app/pos-variance-investigation/{name}'>{name}</a> "
                "must be SUBMITTED before this shift can be approved. "
                "Current docstatus = {ds}. Open the investigation, fill in "
                "Primary Cause, Corrective Action, Cashier Statement, then "
                "click Submit."
            ).format(name=investigation, ds=docstatus),
            title=_("Investigation Not Yet Submitted"),
        )
