"""sungas.overrides.item_pricing_gate
======================================

Wave P-7 — New SKU Activation Gate.

A simple validate hook on the standard ERPNext `Item` doctype that
prevents an SKU from being enabled (`disabled` going from 1 -> 0) when
no approved `LPG Outlet Price Tier` row exists for it. This stops new
items from going live at the POS at zero price by accident.

Gating predicates:

  * `Sungas Pricing Policy.policy_enabled` must be 1 (master switch).
  * `Sungas Pricing Policy.enforce_new_sku_gate` must be 1 (feature flag).
  * Only kicks in on transitions where the doc was previously `disabled=1`
    (i.e. brand new SKUs or explicitly re-enabled ones). Edits to an
    already-active Item are untouched.
  * Skipped for stock-non-applicable items (`is_stock_item=0`) and for
    services / fixed-assets where pricing tier may legitimately not apply.

The check is intentionally permissive: it only looks for the existence of
**any** enabled tier row for this Item — not for a tier row at the
specific selling location. Per-location enforcement is the job of P-4
(hard zero-price block at POS).
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe import _


def require_tier_before_enable(doc, method=None) -> None:
    if not _policy_active():
        return

    # Only fire when the Item is being enabled (disabled flips 1 -> 0).
    before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
    old_disabled = (before.get("disabled") if before else 1)
    new_disabled = int(doc.get("disabled") or 0)
    if not (old_disabled and not new_disabled):
        return

    # Items that legitimately don't carry a sellable price (services /
    # fixed assets / non-stock) are exempt.
    if not int(doc.get("is_stock_item") or 0):
        return

    has_tier = frappe.db.exists(
        "LPG Outlet Price Tier",
        {"item_code": doc.name, "enabled": 1},
    )
    if has_tier:
        return

    frappe.throw(
        _(
            "Item <b>{item}</b> cannot be enabled until an approved "
            "<b>LPG Outlet Price Tier</b> row exists for it. Create a "
            "Price Change Request first, get it approved, then re-enable "
            "this Item."
        ).format(item=doc.name),
        title=_("New SKU Activation Gate"),
    )


def _policy_active() -> bool:
    if not frappe.db.exists("DocType", "Sungas Pricing Policy"):
        return False
    policy = frappe.get_single("Sungas Pricing Policy")
    return bool(policy.get("policy_enabled")) and bool(policy.get("enforce_new_sku_gate"))
