"""Patch 0024 -- Transit Loss Variance Cases are system-opened only.

A case is valid only if its outlet receipt (Material Transfer out of GIT)
is submitted against the PR and the transit-loss clearing Material Issue
(Cr 1626 / Dr 1609) exists. Hand-made cases skipped that clearing, so the
write-off credited 1609 with nothing behind it.
"""
from __future__ import annotations

import frappe

MSG = ("Transit Loss Variance Cases open automatically when the outlet receipt for a supplier "
       "truck is submitted short. Submit the outlet Stock Entry instead of creating a case by hand.")


def has_clearing(pr: str, outlet_se: str) -> bool:
    return bool(frappe.db.exists("Stock Entry", {
        "docstatus": 1, "purpose": "Material Issue", "pr_reference": pr,
        "remarks": ["like", f"%SE {outlet_se}%"]}))


def require_system_opened(doc, method=None):
    if frappe.flags.in_migrate or frappe.flags.in_install or frappe.flags.in_import:
        return
    se = doc.get("outlet_receipt_se")
    row = frappe.db.get_value("Stock Entry", se, ["docstatus", "purpose", "pr_reference"], as_dict=True) if se else None
    if not row or row.docstatus != 1 or row.purpose != "Material Transfer" \
            or row.pr_reference != doc.get("purchase_receipt") or not has_clearing(doc.purchase_receipt, se):
        frappe.throw(MSG, title="Case must come from the outlet receipt")
