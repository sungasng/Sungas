"""Patch 0022 -- IFRS category on every Item.

`sungas_ifrs_category` on Item (and a default on Item Group). Item validate
fills it from the group when blank, insists on it, and blocks combinations
that contradict the standard (e.g. a service held as stock).
`backfill()` runs after every migrate and only fills blanks.
"""
from __future__ import annotations

import frappe

INV = "Inventory"
PPE = "PP&E"
EXP = "Expense"

CATEGORIES = {
    "Inventory - LPG Gas (IAS 2)": INV,
    "Inventory - Cylinders for Sale (IAS 2)": INV,
    "Inventory - Accessories (IAS 2)": INV,
    "Inventory - Appliances (IAS 2)": INV,
    "Inventory - Equipment for Sale (IAS 2)": INV,
    "PP&E - Own-use Equipment (IAS 16)": PPE,
    "PP&E - Own Cylinders (IAS 16)": PPE,
    "Expense - Services": EXP,
    "Expense - Consumables": EXP,
}

GROUP_DEFAULTS = {
    "LPG": "Inventory - LPG Gas (IAS 2)",
    "LPG-Cylinders": "Inventory - Cylinders for Sale (IAS 2)",
    "Accessories": "Inventory - Accessories (IAS 2)",
    "Gas Cookers": "Inventory - Appliances (IAS 2)",
    "Equipment": "Inventory - Equipment for Sale (IAS 2)",
    "Services": "Expense - Services",
    "Consumables": "Expense - Consumables",
    "Consumable": "Expense - Consumables",
}


def conflict(category, is_stock_item, is_fixed_asset) -> str | None:
    """Return a reason the item flags contradict the IFRS category, else None."""
    kind = CATEGORIES.get(category)
    if kind == INV and (not is_stock_item or is_fixed_asset):
        return "an Inventory (IAS 2) item must have Maintain Stock ticked and Is Fixed Asset unticked"
    if kind == PPE and not is_fixed_asset:
        return "a PP&E (IAS 16) item must have Is Fixed Asset ticked"
    if kind == EXP and (is_stock_item or is_fixed_asset):
        return "an Expense item must not maintain stock or be a fixed asset"
    return None


def _group_default(item_group):
    group = item_group
    while group:
        cat = frappe.db.get_value("Item Group", group, "sungas_ifrs_category")
        if cat:
            return cat
        group = frappe.db.get_value("Item Group", group, "parent_item_group")
    return GROUP_DEFAULTS.get(item_group)


def validate_item(doc, method=None):
    if frappe.flags.in_migrate or frappe.flags.in_install:
        return
    if not doc.get("sungas_ifrs_category"):
        doc.sungas_ifrs_category = _group_default(doc.item_group)
    if not doc.sungas_ifrs_category:
        frappe.throw(f"Pick the IFRS Category for item {doc.name or doc.item_code} "
                     "(or set a default IFRS Category on its Item Group).")
    reason = conflict(doc.sungas_ifrs_category, doc.is_stock_item, doc.is_fixed_asset)
    if reason:
        frappe.throw(f"IFRS Category '{doc.sungas_ifrs_category}': {reason}.")


def backfill():
    """after_migrate: set Item Group defaults and fill blank item categories."""
    try:
        if not frappe.db.has_column("Item", "sungas_ifrs_category"):
            return
        for group, cat in GROUP_DEFAULTS.items():
            if frappe.db.exists("Item Group", group) and not frappe.db.get_value(
                    "Item Group", group, "sungas_ifrs_category"):
                frappe.db.set_value("Item Group", group, "sungas_ifrs_category", cat, update_modified=False)
        for item in frappe.get_all("Item", filters={"sungas_ifrs_category": ["is", "not set"]},
                                   fields=["name", "item_group"]):
            cat = _group_default(item.item_group)
            if cat:
                frappe.db.set_value("Item", item.name, "sungas_ifrs_category", cat, update_modified=False)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.ifrs_category.backfill")
