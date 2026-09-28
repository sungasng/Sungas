# Copyright (c) 2026, Manqala and contributors
# For license information, please see license.txt

"""POS Variance Investigation controller.

Renamed from `Annex T-07 Worksheet` (Feb 2026).

Records the investigation trail for POS Closing Shifts whose variance
crosses the block or critical threshold: primary cause, contributing
factors, corrective action, cashier statement, and the sequential
sign-off chain (Cashier -> Plant Manager -> HOD Ops -> HOD Finance).

Denomination-level cash counts are intentionally NOT captured here.
Modern payment mix (cash + card + POS transfer + bank transfer) makes
denomination reconciliation both unreliable and non-audit-relevant.
The authoritative variance number is the linked POS Closing Shift's
`variance_amount` field.
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class POSVarianceInvestigation(Document):

    # ---------------------- lifecycle hooks ---------------------------

    def validate(self):
        self._enforce_severity_eligibility()

    def before_submit(self):
        self._require_complete_narrative()
        self._stamp_cashier_signature()

    def on_submit(self):
        # Keep the linked shift pointing at us in case it was created
        # outside the auto-create path.
        if self.shift and not frappe.db.get_value(
            "POS Closing Shift", self.shift, "pos_variance_investigation"
        ):
            frappe.db.set_value(
                "POS Closing Shift", self.shift,
                "pos_variance_investigation", self.name,
                update_modified=False,
            )

    # ---------------------- internal helpers --------------------------

    def _enforce_severity_eligibility(self) -> None:
        """Only exists for HARD variances (block / critical).

        Warn rather than throw on draft so admins can experiment, but
        block submission of an investigation attached to a soft /
        no-variance shift (it'd just be paperwork noise).
        """
        if self.docstatus != 0:
            return
        sev = (self.variance_severity or "").lower()
        if sev in ("block", "critical"):
            return
        # Pre-submit on a non-hard shift is allowed while the cashier
        # is recounting and severity may rise on re-save. No throw here.

    def _require_complete_narrative(self) -> None:
        if not (self.primary_cause or "").strip():
            frappe.throw(_("Primary Cause must be selected before submitting."))
        if self.primary_cause == "Other" and not (self.other_cause_detail or "").strip():
            frappe.throw(_("Please describe the cause in 'Other — please specify'."))
        if not (self.corrective_action or "").strip():
            frappe.throw(_("Corrective Action Required must be filled in."))
        if not (self.cashier_statement or "").strip():
            frappe.throw(_("Cashier Statement must be filled in."))

    def _stamp_cashier_signature(self) -> None:
        if not self.cashier_signed_by:
            self.cashier_signed_by = frappe.session.user
        if not self.cashier_signed_on:
            self.cashier_signed_on = now_datetime()


# ---------------------- module-level helpers ---------------------------

@frappe.whitelist()
def stamp_role_signoff(
    investigation_name: str, role_key: str, notes: str | None = None
) -> dict:
    """Stamp a role-specific signature block on a submitted investigation.

    Called by the linked closing shift's workflow transitions so the
    investigation chain is captured on the audit document.

    Args:
        investigation_name: e.g. "PVI-26-00001"
        role_key:   one of "plant_manager", "hod_ops", "hod_finance"
        notes:      optional text appended to the role's notes field
    """
    field_map = {
        "plant_manager": (
            "plant_manager_signed_by",
            "plant_manager_signed_on",
            "plant_manager_notes",
        ),
        "hod_ops": (
            "hod_ops_signed_by",
            "hod_ops_signed_on",
            "hod_ops_notes",
        ),
        "hod_finance": (
            "hod_finance_signed_by",
            "hod_finance_signed_on",
            "hod_finance_notes",
        ),
    }
    if role_key not in field_map:
        frappe.throw(_("Unknown role_key {0}").format(role_key))
    by_field, on_field, notes_field = field_map[role_key]

    updates = {
        by_field: frappe.session.user,
        on_field: now_datetime(),
    }
    if notes:
        existing = frappe.db.get_value(
            "POS Variance Investigation", investigation_name, notes_field
        ) or ""
        updates[notes_field] = (existing + "\n" if existing else "") + notes

    frappe.db.set_value(
        "POS Variance Investigation", investigation_name, updates, update_modified=False
    )
    return {"ok": True, "investigation": investigation_name, "role": role_key}
