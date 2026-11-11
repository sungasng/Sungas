"""Patch 0028 -- selling prices change only through approval.

Direct creates, edits or deletes of an LPG Outlet Price Tier or a selling
Item Price are refused. The approved paths (LPG Price Change Request and
LPG Bulk Price Upload on approval, and the national price-list sync) save
with ignore_permissions, which is the only way through. Data Import is
blocked too: use a Bulk Price Upload. Buying prices are untouched.
"""
from __future__ import annotations

import frappe

MSG = ("Selling prices can only be changed through an approved Price Change Request or "
       "Bulk Price Upload. Direct edits, imports and deletions are locked.")


def _locked(doc) -> bool:
    if frappe.flags.in_migrate or frappe.flags.in_install or doc.flags.ignore_permissions:
        return False
    if doc.doctype == "Item Price" and not doc.get("selling"):
        return False
    return True


def block_direct_edit(doc, method=None):
    if _locked(doc):
        frappe.throw(MSG, title="Prices are locked")


def ensure_no_auto_price_insert():
    """after_migrate: ERPNext must not create prices from typed rates (hidden 6th price route)."""
    if frappe.db.get_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing"):
        frappe.db.set_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing", 0)
        frappe.db.commit()
