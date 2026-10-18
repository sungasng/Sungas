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


@frappe.whitelist()
def approve_writeoff_as_hof(case: str, remarks: str = "") -> dict:
    """Stamp Head-of-Finance sign-off on a Transit Loss Variance Case
    before it can resolve as 'Written Off'. Role-gated to LPG Head of
    Finance (break-glass: System Manager).

    Called by the client-side 'Approve Write-Off as HoF' button on
    Draft Transit Loss Variance Cases. Writes:
        hod_finance_signed_by  = session.user
        hod_finance_signed_on  = now
        hof_remarks            = <optional user text>

    Idempotent: re-signing silently replaces the previous stamp.
    """
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not ({"LPG Head of Finance", "System Manager"} & user_roles):
        frappe.throw(
            "Only users with the LPG Head of Finance role may approve "
            "a Transit Loss write-off."
        )

    doc = frappe.get_doc("Transit Loss Variance Case", case)
    if doc.docstatus != 0:
        frappe.throw("Transit Loss case must be in Draft to approve write-off.")
    if doc.get("resolution") != "Written Off":
        frappe.throw(
            "HoF write-off approval only applies when Resolution = 'Written Off'. "
            f"Current resolution: {doc.get('resolution') or '-'}."
        )

    doc.db_set("hod_finance_signed_by", frappe.session.user, update_modified=False)
    doc.db_set("hod_finance_signed_on", frappe.utils.now_datetime(), update_modified=False)
    if remarks:
        doc.db_set("hof_remarks", remarks[:140], update_modified=False)
    doc.add_comment(
        "Info",
        f"<b>[HoF Write-Off Approval]</b> Approved by {frappe.session.user}"
        + (f" -- {frappe.utils.strip_html(remarks)[:140]}" if remarks else "")
    )
    return {"ok": True, "approved_by": frappe.session.user}


@frappe.whitelist()
def approve_writeoff_as_hof_iovc(case: str, remarks: str = "") -> dict:
    """Stamp Head-of-Finance sign-off on an Inter-Outlet Variance Case
    before it can resolve as 'Write-off as transit loss'. Mirrors the TLVC
    pattern (Patch 0013) exactly. Role-gated to LPG Head of Finance
    (break-glass: System Manager). Idempotent."""
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not ({"LPG Head of Finance", "System Manager"} & user_roles):
        frappe.throw(
            "Only users with the LPG Head of Finance role may approve "
            "an Inter-Outlet variance write-off."
        )

    doc = frappe.get_doc("Inter-Outlet Variance Case", case)
    if doc.docstatus != 0:
        frappe.throw("Inter-Outlet variance case must be in Draft to approve write-off.")
    if doc.get("resolution") != "Write-off as transit loss":
        frappe.throw(
            "HoF write-off approval only applies when Resolution = "
            "'Write-off as transit loss'. "
            f"Current resolution: {doc.get('resolution') or '-'}."
        )

    doc.db_set("hod_finance_signed_by", frappe.session.user, update_modified=False)
    doc.db_set("hod_finance_signed_on", frappe.utils.now_datetime(), update_modified=False)
    if remarks:
        doc.db_set("hof_remarks", remarks[:140], update_modified=False)
    doc.add_comment(
        "Info",
        f"<b>[HoF Write-Off Approval]</b> Approved by {frappe.session.user}"
        + (f" -- {frappe.utils.strip_html(remarks)[:140]}" if remarks else "")
    )
    return {"ok": True, "approved_by": frappe.session.user}


@frappe.whitelist()
def force_close_trip(ls: str, reason: str) -> dict:
    """Patch 0015e -- escape hatch for the Truck Open Trip Guard.

    When a truck trip is stuck in Locked / Loading / Dispatched and the
    truck physically cannot reconcile (broke down, driver unreachable,
    residual gas written off, etc.), HoO can force-close the trip so the
    truck is freed for a new Material Request / Loading Schedule.

    Role-gated to LPG Head of Operations + System Manager. The reason
    is MANDATORY and stamped on the DLS for audit.
    """
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not ({"LPG Head of Operations", "System Manager"} & user_roles):
        frappe.throw(
            "Only users with the LPG Head of Operations role may force-close a trip."
        )
    if not (reason or "").strip():
        frappe.throw("Reason is required for force-close.")

    doc = frappe.get_doc("Daily Loading Schedule", ls)
    if doc.state == "Closed":
        return {"ok": True, "note": "already closed", "closed_by": doc.get("force_closed_by")}
    if doc.state not in ("Locked", "Loading", "Dispatched"):
        frappe.throw(
            f"Trip is in state '{doc.state}'. Force-close only applies to "
            "Locked / Loading / Dispatched trips."
        )

    # Patch 0016 -- dispatched trips must have trip costs settled (clearing = 0).
    from sungas.overrides.haulage_costing import ensure_trip_settled
    ensure_trip_settled(doc)

    doc.state = "Closed"
    doc.force_closed_by = frappe.session.user
    doc.force_closed_at = frappe.utils.now_datetime()
    doc.force_close_reason = (reason or "").strip()[:1000]
    doc.save(ignore_permissions=True)
    doc.add_comment(
        "Info",
        f"<b>[Force Close Trip]</b> Closed by {frappe.session.user} -- "
        f"{frappe.utils.strip_html(reason)[:500]}",
    )
    frappe.db.commit()
    return {
        "ok": True,
        "state": "Closed",
        "closed_by": frappe.session.user,
        "truck_no": doc.truck_no,
    }
