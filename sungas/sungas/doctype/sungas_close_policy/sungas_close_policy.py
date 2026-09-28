"""Sungas Close Policy -- single doctype for cash-variance enforcement settings.

Threshold-field semantics (Wave TG-1, Feb 2026):

    A threshold field left blank or set to 0 means the corresponding tier
    is DISABLED. `get_thresholds()` returns `math.inf` for those, so the
    downstream comparison `abs_var >= threshold` can never trip.

    The single exception is `block_pct_min_expected`, which is a *gate /
    floor* (not a tier). Blank/0 there means "no floor -- percent rules
    apply to every shift".

    This lets operators explicitly turn off tiers they don't want
    enforced (e.g. leave Critical Absolute blank to skip the HOD-Finance
    tier entirely, keeping the workflow at PM -> HOD Ops).
"""
import math

import frappe
from frappe.model.document import Document


# Sentinel used for disabled tiers. Any `abs_var >= math.inf` is False,
# so the tier never trips.
_DISABLED = math.inf


def _thr(value: float | None) -> float:
    """Convert a policy field to a threshold: 0 / blank -> disabled sentinel."""
    v = float(value or 0)
    return v if v > 0 else _DISABLED


class SungasClosePolicy(Document):
    """No special validations -- field defaults handle everything."""

    def get_thresholds(self):
        """Return resolved threshold values.

        Blank / 0 on any tier field yields `math.inf` -> tier disabled.
        `block_pct_min_expected` is a floor, so blank / 0 yields 0 (no
        floor, percent rules always apply).
        """
        return {
            "warn_abs": _thr(self.variance_warn_abs),
            "warn_pct": _thr(self.variance_warn_pct),
            "block_abs": _thr(self.variance_block_abs),
            "block_pct": _thr(self.variance_block_pct),
            # Floor / gate -- 0 means "no floor".
            "block_pct_min_expected": float(self.block_pct_min_expected or 0),
            "warn_abs_overage": _thr(self.variance_warn_abs_overage),
            "block_abs_overage": _thr(self.variance_block_abs_overage),
            "critical_abs": _thr(self.get("variance_critical_abs")),
            "critical_pct": _thr(self.get("variance_critical_pct")),
            "critical_abs_overage": _thr(self.get("variance_critical_abs_overage")),
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
