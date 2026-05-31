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
