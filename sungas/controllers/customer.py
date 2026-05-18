import json

import frappe


@frappe.whitelist()
def validate_customer(doc, event):
    """
    Validate that a customer cannot be created twice within the same territory
    """
    if isinstance(doc, str):
        doc = json.loads(doc)
    if doc.is_new():
        exists = frappe.get_all(
            "Customer",
            {"territory": doc.territory, "mobile_no": doc.mobile_no},
        )
        if exists:
            frappe.throw(
                f"""
                Please note that a customer with mobile no {doc.mobile_no}
                in territory {doc.territory} already exists"""
            )
