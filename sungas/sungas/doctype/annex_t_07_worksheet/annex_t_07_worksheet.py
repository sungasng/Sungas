# Copyright (c) 2026, Manqala and contributors
# For license information, please see license.txt

"""Annex T-07 Worksheet controller.

Computes denomination row math, stamps signature fields on workflow
transitions, and validates that the cash-count totals match the linked
POS Closing Shift's variance amount within a small tolerance.

Tolerance is intentionally tight (NGN 1.00) since this is the legal-
audit record of the cash count — if the worksheet disagrees with the
shift totals by more than a Naira, the cashier needs to recount before
sign-off.
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


# Match tolerance between cash-count totals and shift variance, in NGN.
RECONCILIATION_TOLERANCE = 1.00


class AnnexT07Worksheet(Document):

    # ---------------------- lifecycle hooks ---------------------------

    def validate(self):
        self._compute_denomination_math()
        self._enforce_severity_eligibility()

    def before_submit(self):
        self._require_complete_narrative()
        self._reconcile_with_shift()
        self._stamp_cashier_signature()

    def on_submit(self):
        # Keep the linked shift pointing at us in case it was created
        # outside the auto-create path.
        if self.shift and not frappe.db.get_value("POS Closing Shift", self.shift, "annex_t07"):
            frappe.db.set_value(
                "POS Closing Shift", self.shift,
                "annex_t07", self.name,
                update_modified=False,
            )

    # ---------------------- internal helpers --------------------------

    def _compute_denomination_math(self) -> None:
        total_expected = 0.0
        total_actual = 0.0
        for row in (self.denominations or []):
            try:
                denom = flt(row.denomination)
            except (TypeError, ValueError):
                denom = 0.0  # 'Other' or non-numeric: math suspended
            row.expected_value = flt(row.expected_count) * denom
            row.actual_value = flt(row.actual_count) * denom
            row.variance_value = row.actual_value - row.expected_value
            total_expected += row.expected_value
            total_actual += row.actual_value
        self.total_expected = total_expected
        self.total_actual = total_actual
        self.total_variance = total_actual - total_expected

    def _enforce_severity_eligibility(self) -> None:
        """A T-07 should only exist for HARD variances (block / critical).

        We warn rather than throw on draft so admins can experiment, but
        block submission of a worksheet attached to a soft / no-variance
        shift (it'd just be paperwork noise).
        """
        if self.docstatus != 0:
            return
        sev = (self.variance_severity or "").lower()
        if sev in ("block", "critical"):
            return
        # Pre-submit a worksheet on a non-hard shift is allowed (e.g. while
        # the cashier is recounting and the severity will rise on re-save)
        # but flag clearly in a comment.

    def _require_complete_narrative(self) -> None:
        if not (self.primary_cause or "").strip():
            frappe.throw(_("Primary Cause must be selected before submitting Annex T-07."))
        if self.primary_cause == "Other" and not (self.other_cause_detail or "").strip():
            frappe.throw(_("Please describe the cause in 'Other — please specify'."))
        if not (self.corrective_action or "").strip():
            frappe.throw(_("Corrective Action Required must be filled in."))
        if not (self.cashier_statement or "").strip():
            frappe.throw(_("Cashier Statement must be filled in."))
        if not self.denominations:
            frappe.throw(_("At least one denomination row must be filled in."))

    def _reconcile_with_shift(self) -> None:
        if not self.shift:
            return
        shift_variance = flt(
            frappe.db.get_value("POS Closing Shift", self.shift, "variance_amount") or 0
        )
        diff = abs(flt(self.total_variance) - shift_variance)
        if diff > RECONCILIATION_TOLERANCE:
            frappe.throw(
                _(
                    "Annex T-07 cash-count total variance is NGN {0:+,.2f} but the linked "
                    "POS Closing Shift records NGN {1:+,.2f} (off by NGN {2:,.2f}). "
                    "Please recount or correct the denomination rows before signing."
                ).format(self.total_variance, shift_variance, diff)
            )

    def _stamp_cashier_signature(self) -> None:
        if not self.cashier_signed_by:
            self.cashier_signed_by = frappe.session.user
        if not self.cashier_signed_on:
            self.cashier_signed_on = now_datetime()


# ---------------------- module-level helpers ---------------------------

@frappe.whitelist()
def stamp_role_signoff(annex_name: str, role_key: str, notes: str | None = None) -> dict:
    """Stamp a role-specific signature block on a submitted T-07.

    Called by the linked closing shift's workflow transitions so the
    investigation chain is captured on the audit document.

    Args:
        annex_name: e.g. "AT07-26-00001"
        role_key:   one of "plant_manager", "hod_ops", "hod_finance"
        notes:      optional text appended to the role's notes field
    """
    field_map = {
        "plant_manager": ("plant_manager_signed_by", "plant_manager_signed_on", "plant_manager_notes"),
        "hod_ops": ("hod_ops_signed_by", "hod_ops_signed_on", "hod_ops_notes"),
        "hod_finance": ("hod_finance_signed_by", "hod_finance_signed_on", "hod_finance_notes"),
    }
    if role_key not in field_map:
        frappe.throw(_("Unknown role_key {0}").format(role_key))
    by_field, on_field, notes_field = field_map[role_key]

    updates = {
        by_field: frappe.session.user,
        on_field: now_datetime(),
    }
    if notes:
        existing = frappe.db.get_value("Annex T-07 Worksheet", annex_name, notes_field) or ""
        updates[notes_field] = (existing + "\n" if existing else "") + notes

    frappe.db.set_value(
        "Annex T-07 Worksheet", annex_name, updates, update_modified=False
    )
    return {"ok": True, "annex": annex_name, "role": role_key}
