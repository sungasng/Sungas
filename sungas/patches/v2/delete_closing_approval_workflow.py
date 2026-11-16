"""Patch 0053: the closing-shift approval workflow is replaced by the variance case (0052) -- delete it."""
import frappe


def execute():
    if frappe.db.exists("Workflow", "POS Closing Shift Variance"):
        frappe.delete_doc("Workflow", "POS Closing Shift Variance", force=1, ignore_permissions=True)
    frappe.db.commit()
