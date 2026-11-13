"""0036: restore Customer Group Change Request.current_group overwritten by ERPNext's
Customer.update_customer_groups (it rewrote every Customer Group link for the customer)."""
import json

import frappe


def from_group(req, versions):
    """Old group from the first customer_group change logged at/after the request."""
    for v in versions:
        if str(v.creation) < str(req.creation):
            continue
        for field, old, _new in json.loads(v.data or "{}").get("changed", []):
            if field == "customer_group" and old:
                return old
    return None


def execute():
    for req in frappe.get_all("Customer Group Change Request",
                              fields=["name", "customer", "creation", "current_group", "direct_change"]):
        versions = frappe.get_all("Version", filters={"ref_doctype": "Customer", "docname": req.customer},
                                  fields=["creation", "data"], order_by="creation asc")
        old = from_group(req, versions)
        if old and old != req.current_group:
            frappe.db.set_value("Customer Group Change Request", req.name, "current_group", old, update_modified=False)
    frappe.db.commit()
