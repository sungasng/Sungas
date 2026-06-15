"""Sungas Close Policy -- single doctype for cash-variance enforcement settings."""
import frappe
from frappe.model.document import Document


class SungasClosePolicy(Document):
    """No special validations -- field defaults handle everything."""

    def get_thresholds(self):
        """Return resolved threshold values with sensible defaults if user left fields blank."""
        return {
            "warn_abs": float(self.variance_warn_abs or 5000),
            "warn_pct": float(self.variance_warn_pct or 0.5),
            "block_abs": float(self.variance_block_abs or 50000),
            "block_pct": float(self.variance_block_pct or 2.0),
            "block_pct_min_expected": float(self.block_pct_min_expected or 500000),
            "warn_abs_overage": float(self.variance_warn_abs_overage or 10000),
            "block_abs_overage": float(self.variance_block_abs_overage or 100000),
            "critical_abs": float(self.get("variance_critical_abs") or 100000),
            "critical_pct": float(self.get("variance_critical_pct") or 3.0),
            "critical_abs_overage": float(self.get("variance_critical_abs_overage") or 200000),
        }

    def get_approver_roles(self):
        """Return list of role names authorised to approve block-threshold variances."""
        roles = []
        if self.approver_role_primary:
            roles.append(self.approver_role_primary)
        if self.approver_role_secondary:
            roles.append(self.approver_role_secondary)
        return roles or ["Accounts Manager"]


def get_policy():
    """Helper used by hook code."""
    return frappe.get_single("Sungas Close Policy")
