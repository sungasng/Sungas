"""Sungas Procurement Policy -- single doctype.

Wave P-1 / P-2 (Feb 2026) -- centralises:
    * LPG + Non-LPG PO Approval Matrix thresholds (₦ + kg)
    * Approver role names for HoO / HoF / COO / CPL
    * GIT ageing configuration (stale-hours + reviewer role)

Threshold semantics follow the app-wide convention: 0 or blank on any
threshold field means "tier disabled" (returns math.inf so the
`>=` comparison never trips). Same pattern as Sungas Close Policy.
"""
import math

import frappe
from frappe.model.document import Document


_DISABLED = math.inf


def _thr(value) -> float:
    """0 / blank -> disabled sentinel; anything positive is passed through."""
    v = float(value or 0)
    return v if v > 0 else _DISABLED


class SungasProcurementPolicy(Document):
    """No custom validate -- consumers use get_matrix() and get_git()."""

    # ------------------------------------------------------------------ #
    # Matrix accessor
    # ------------------------------------------------------------------ #

    def get_matrix(self) -> dict:
        """Return the resolved PO Approval Matrix thresholds & roles.

        `float('inf')` for a tier means that tier is disabled -- the
        PO can never reach it, so the effective ceiling shifts down.
        """
        return {
            "enabled": bool(self.policy_enabled),
            "lpg_item_groups": [
                g.strip() for g in (self.lpg_item_groups or "").split(",")
                if g.strip()
            ],
            "lpg": {
                "tier_2_value_ngn": _thr(self.lpg_tier_2_value_ngn),
                "tier_2_volume_kg": _thr(self.lpg_tier_2_volume_kg),
                "tier_3_value_ngn": _thr(self.lpg_tier_3_value_ngn),
                "tier_3_volume_kg": _thr(self.lpg_tier_3_volume_kg),
            },
            "nonlpg": {
                "tier_2_value_ngn": _thr(self.nonlpg_tier_2_value_ngn),
                "tier_3_value_ngn": _thr(self.nonlpg_tier_3_value_ngn),
            },
            "roles": {
                "hoo": self.hoo_role or "LPG Head of Operations",
                "hof": self.hof_role or "LPG Head of Finance",
                "coo": self.coo_role or "Chief Operating Officer",
                "cpl": self.cpl_role or "Purchase Manager",
            },
        }

    # ------------------------------------------------------------------ #
    # GIT ageing accessor
    # ------------------------------------------------------------------ #

    def get_git(self) -> dict:
        return {
            "enabled": bool(self.policy_enabled) and int(self.git_stale_hours or 0) > 0,
            "stale_hours": int(self.git_stale_hours or 0),
            "reviewer_role": self.git_reviewer_role or "LPG Head of Operations",
        }
