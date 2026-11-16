"""Patch 0052 one-off (test environment): clear closes still in the old approval flow so every cashier
closes again under the new flow (close first, variance case after)."""
import frappe


def execute():
    for c in frappe.get_all("POS Closing Shift", filters={"docstatus": 0},
                            fields=["name", "pos_opening_shift", "variance_provisional_je", "pos_variance_investigation"]):
        je = c.variance_provisional_je
        if je and frappe.db.get_value("Journal Entry", je, "docstatus") == 1:
            d = frappe.get_doc("Journal Entry", je)
            d.flags.ignore_permissions = True
            d.cancel()
        for pvi in frappe.get_all("POS Variance Investigation", filters={"shift": c.name}, fields=["name", "docstatus"]):
            if pvi.docstatus == 1:
                frappe.db.set_value("POS Variance Investigation", pvi.name, "docstatus", 2, update_modified=False)
            frappe.delete_doc("POS Variance Investigation", pvi.name, force=1, ignore_permissions=True)
        frappe.delete_doc("POS Closing Shift", c.name, force=1, ignore_permissions=True)
        if c.pos_opening_shift:
            frappe.db.set_value("POS Opening Shift", c.pos_opening_shift, "sungas_count_log", None, update_modified=False)
    frappe.db.commit()
