"""sungas.overrides.purchase_order_matrix
==========================================

Wave P-1 (Feb 2026) -- LPG + Non-LPG PO Approval Matrix enforcement.

Threshold matrix (defaults, editable via Sungas Procurement Policy):
    LPG:
        Tier 1  ≤ NGN 16M      OR ≤ 25 000 kg   -> HoO
        Tier 2  ≤ NGN 100M     OR ≤ 100 000 kg  -> HoO + HoF
        Tier 3  > NGN 100M     OR > 100 000 kg  -> HoO + HoF + COO
    Non-LPG:
        Tier 1  ≤ NGN 1M                        -> CPL
        Tier 2  ≤ NGN 15M                       -> CPL + HoF
        Tier 3  > NGN 15M                       -> CPL + HoF + COO

How enforcement works (custom-fields pattern, no Frappe Workflow):
    1. `classify_tier(doc)` runs at validate. It:
         * detects LPG vs Non-LPG by inspecting item_groups on rows
         * computes the tier bucket (T1 / T2 / T3) from grand_total + qty
         * writes to read-only fields `sungas_is_lpg`, `sungas_approval_tier`
    2. `enforce_tier_approvals(doc)` runs at before_submit. It:
         * looks at the tier & re-derives the *required* stamp fields
           (hoo/hof/coo/cpl_approved_by)
         * throws if any required stamp is empty
    3. Four whitelisted approve endpoints stamp the current user+time
       into the respective stamp fields, gated by role. UI can wire
       them to custom buttons or a WhatsApp magic-link.

Bypass: System Manager can set/reset any stamp via normal write access
(the doctype's Custom DocPerm allows SM write on stamp fields), which
covers incident response / cleanup.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, now_datetime


_POLICY_DOCTYPE = "Sungas Procurement Policy"


# --------------------------------------------------------------------------- #
# Public hooks
# --------------------------------------------------------------------------- #

def classify_tier(doc, method=None) -> None:
    """validate hook -- stamps sungas_is_lpg + sungas_approval_tier."""
    policy = _policy()
    if not policy["enabled"]:
        doc.sungas_is_lpg = 0
        doc.sungas_approval_tier = ""
        return

    is_lpg = _is_lpg_po(doc, policy["lpg_item_groups"])
    tier = _compute_tier(doc, policy, is_lpg)

    doc.sungas_is_lpg = 1 if is_lpg else 0
    doc.sungas_approval_tier = tier  # "T1" | "T2" | "T3"


def enforce_tier_approvals(doc, method=None) -> None:
    """before_submit hook -- throws if required approver stamps missing."""
    policy = _policy()
    if not policy["enabled"]:
        return

    is_lpg = _is_lpg_po(doc, policy["lpg_item_groups"])
    tier = _compute_tier(doc, policy, is_lpg)
    required = _required_stamps(tier, is_lpg)

    missing = [label for stamp_field, label in required
               if not doc.get(stamp_field)]
    if missing:
        frappe.throw(
            _(
                "Purchase Order <b>{name}</b> is Tier <b>{tier}</b> "
                "({type}). The following approvals are still missing: "
                "<b>{missing}</b>.<br><br>Grand total: NGN {gt:,.2f} · "
                "Total qty: {qty:g}"
            ).format(
                name=doc.name,
                tier=tier,
                type="LPG" if is_lpg else "Non-LPG",
                missing=", ".join(missing),
                gt=flt(doc.grand_total or 0),
                qty=flt(doc.total_qty or 0),
            ),
            title=_("PO Approval Matrix -- Required Approvers Not Signed"),
        )


# --------------------------------------------------------------------------- #
# Approve endpoints (whitelisted, role-gated)
# --------------------------------------------------------------------------- #

def _approve(name: str, role_key: str, stamp_by: str, stamp_on: str) -> dict:
    policy = _policy()
    required_role = policy["roles"][role_key]

    if required_role not in frappe.get_roles(frappe.session.user):
        frappe.throw(
            _("This action requires the {role} role.").format(role=required_role),
            title=_("Not Authorised"),
        )

    doc = frappe.get_doc("Purchase Order", name)
    if doc.docstatus != 0:
        frappe.throw(_("Only Draft Purchase Orders can be approved."))

    frappe.db.set_value("Purchase Order", name, {
        stamp_by: frappe.session.user,
        stamp_on: now_datetime(),
    })
    frappe.db.commit()

    return {
        "ok": True,
        "po": name,
        "role": role_key,
        "user": frappe.session.user,
    }


@frappe.whitelist()
def approve_as_hoo(name: str) -> dict:
    return _approve(name, "hoo", "sungas_hoo_approved_by", "sungas_hoo_approved_on")


@frappe.whitelist()
def approve_as_hof(name: str) -> dict:
    return _approve(name, "hof", "sungas_hof_approved_by", "sungas_hof_approved_on")


@frappe.whitelist()
def approve_as_coo(name: str) -> dict:
    return _approve(name, "coo", "sungas_coo_approved_by", "sungas_coo_approved_on")


@frappe.whitelist()
def approve_as_cpl(name: str) -> dict:
    return _approve(name, "cpl", "sungas_cpl_approved_by", "sungas_cpl_approved_on")


# --------------------------------------------------------------------------- #
# Internals -- classification
# --------------------------------------------------------------------------- #

def _policy() -> dict:
    """Fetch policy in one call; fall back to safe defaults if not installed."""
    if not frappe.db.exists("DocType", _POLICY_DOCTYPE):
        return {"enabled": False}
    return frappe.get_single(_POLICY_DOCTYPE).get_matrix()


def _is_lpg_po(doc, lpg_groups: list[str]) -> bool:
    """LPG PO iff every line's item_group is in the configured LPG groups.

    Mixed-basket POs are treated as Non-LPG for approval purposes -- the
    Non-LPG matrix's stricter Tier 2 threshold (NGN 1M) is the safer
    default when the basket is ambiguous.
    """
    if not lpg_groups:
        return False
    if not doc.get("items"):
        return False
    groups = {row.get("item_group") for row in doc.get("items") if row.get("item_group")}
    return bool(groups) and groups.issubset(set(lpg_groups))


def _compute_tier(doc, policy: dict, is_lpg: bool) -> str:
    """Return 'T1' | 'T2' | 'T3' based on grand_total and qty vs matrix."""
    gt = flt(doc.get("grand_total") or 0)
    qty = flt(doc.get("total_qty") or 0)

    if is_lpg:
        m = policy["lpg"]
        # Tier 3 first (highest): > tier_3_value OR > tier_3_volume.
        if gt > m["tier_3_value_ngn"] or qty > m["tier_3_volume_kg"]:
            return "T3"
        # Tier 2: >= tier_2_value OR >= tier_2_volume.
        if gt >= m["tier_2_value_ngn"] or qty >= m["tier_2_volume_kg"]:
            return "T2"
        return "T1"

    m = policy["nonlpg"]
    if gt > m["tier_3_value_ngn"]:
        return "T3"
    if gt >= m["tier_2_value_ngn"]:
        return "T2"
    return "T1"


def _required_stamps(tier: str, is_lpg: bool) -> list[tuple[str, str]]:
    """Return list of (stamp_by_fieldname, human_label) that must be signed."""
    if is_lpg:
        base = [("sungas_hoo_approved_by", "Head of Operations")]
    else:
        base = [("sungas_cpl_approved_by", "Central Procurement Lead")]

    if tier == "T1":
        return base
    if tier == "T2":
        return base + [("sungas_hof_approved_by", "Head of Finance")]
    # T3
    return base + [
        ("sungas_hof_approved_by", "Head of Finance"),
        ("sungas_coo_approved_by", "COO"),
    ]
