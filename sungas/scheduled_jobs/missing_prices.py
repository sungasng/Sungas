"""Patch 0025 -- items each plant holds in stock but cannot sell (no price).

An item is priced at a plant when its till price list (POS Profile
selling_price_list) has a valid Item Price above zero, or an enabled,
valid LPG Outlet Price Tier above zero exists for it.
"""
from __future__ import annotations

import frappe
from frappe.utils import flt, getdate


def _valid(start, end, today) -> bool:
    return (not start or getdate(start) <= today) and (not end or getdate(end) >= today)


def priced(today) -> tuple[dict, set]:
    """({price_list: {item_code}}, {tier item_codes})."""
    by_list = {}
    for r in frappe.get_all("Item Price", filters={"selling": 1, "price_list_rate": [">", 0]},
                            fields=["price_list", "item_code", "valid_from", "valid_upto"]):
        if _valid(r.valid_from, r.valid_upto, today):
            by_list.setdefault(r.price_list, set()).add(r.item_code)
    tiers = {r.item_code for r in frappe.get_all("LPG Outlet Price Tier", filters={"enabled": 1, "rate": [">", 0]},
                                                 fields=["item_code", "valid_from", "valid_to"])
             if _valid(r.valid_from, r.valid_to, today)}
    return by_list, tiers


def missing_by_warehouse(today) -> dict:
    """{plant warehouse: [(item_code, item_name, qty)]} for items in stock with no price."""
    today = getdate(today)
    wh_list = {}
    for p in frappe.get_all("POS Profile", filters={"disabled": 0}, fields=["warehouse", "selling_price_list"]):
        wh_list.setdefault(p.warehouse, p.selling_price_list)
    if not wh_list:
        return {}
    by_list, tiers = priced(today)
    bins = frappe.get_all("Bin", filters={"warehouse": ["in", list(wh_list)], "actual_qty": [">", 0]},
                          fields=["warehouse", "item_code", "actual_qty"])
    sellable = {r.name: r.item_name for r in frappe.get_all(
        "Item", filters={"name": ["in", list({b.item_code for b in bins}) or [""]], "disabled": 0, "is_sales_item": 1},
        fields=["name", "item_name"])}
    out = {}
    for b in sorted(bins, key=lambda b: b.item_code):
        if b.item_code in sellable and b.item_code not in tiers \
                and b.item_code not in by_list.get(wh_list[b.warehouse], set()):
            out.setdefault(b.warehouse, []).append((b.item_code, sellable[b.item_code], flt(b.actual_qty)))
    return out
