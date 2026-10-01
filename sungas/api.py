"""sungas.api -- lightweight whitelisted endpoints

Minimum surface, read-only, callable by any logged-in user. These exist so
that client scripts don't need to pierce DocType read-perms on singletons
like `Sungas Procurement Policy`.
"""

from __future__ import annotations

import frappe  # type: ignore

DEFAULT_HOI_COST_CENTER = "70003 - Procurement - SCL"


@frappe.whitelist()
def get_hoi_cost_center() -> str:
    """Return the HO Procurement cost center from Sungas Procurement Policy.

    No role restriction -- any logged-in user may read it. Falls back to
    the hard-coded default if the policy singleton is missing or the field
    is empty. Never throws.
    """
    try:
        cc = frappe.db.get_single_value(
            "Sungas Procurement Policy", "hoi_cost_center"
        )
        if cc:
            return cc
    except Exception:
        pass
    return DEFAULT_HOI_COST_CENTER
