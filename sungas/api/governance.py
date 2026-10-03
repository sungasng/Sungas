"""sungas.api.governance -- lightweight whitelisted governance endpoints.

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


@frappe.whitelist()
def get_po_item_qty(name: str) -> float:
    """Return `qty` on a Purchase Order Item row -- used by the PR
    Variance Auto-Calc client script to compare dispatched qty to the
    ordered qty on the parent PO.

    Why this exists (Patch 0012a): the client script previously called
    frappe.db.get_value('Purchase Order Item', ...) directly, which
    forces check_parent_permission on Purchase Order. Users without
    read-perm on Purchase Order (e.g. Stock User creating a PR off a
    PO) saw a 'Not permitted' popup even though the JS wrapped the
    call in try/catch -- Frappe shows the popup server-side before
    the JS catch runs.

    This endpoint bypasses that check by reading one field directly,
    returning 0 on any failure. Safe: read-only, scalar, no PII.
    """
    try:
        qty = frappe.db.get_value("Purchase Order Item", name, "qty")
        return float(qty) if qty else 0.0
    except Exception:
        return 0.0
