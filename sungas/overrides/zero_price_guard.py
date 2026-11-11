"""Patch 0025 -- hard zero-price block at the POS till (Pricing Wave P-4).

Any POS Invoice, or Sales Invoice raised from the till (is_pos), with an item
line at price 0 is refused until the price is set. Returns and consolidated
invoices are skipped. Patch 0026: always on, independent of the Sungas
Pricing Policy master switch (which is off on live).
"""
from __future__ import annotations

import frappe
from frappe.utils import flt


def zero_price_items(items) -> list[str]:
    out = []
    for it in items or []:
        if flt(it.get("qty")) > 0 and flt(it.get("rate")) <= 0 and it.get("item_code") not in out:
            out.append(it.get("item_code"))
    return out


def block_zero_price(doc, method=None):
    if frappe.flags.in_migrate or frappe.flags.in_import or frappe.flags.in_install:
        return
    if doc.get("is_return") or doc.get("is_consolidated"):
        return
    if doc.doctype == "Sales Invoice" and not doc.get("is_pos"):
        return
    bad = zero_price_items(doc.get("items"))
    if bad:
        frappe.throw(f"No selling price is set for: {', '.join(bad)}. Ask your plant manager to set "
                     "the price before selling. Items cannot leave the till at zero.",
                     title="Item has no price")
