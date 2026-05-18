import json

import frappe


@frappe.whitelist()
def autoname_sales_invoice(doc, event):
    """
    Validate that a Sales invoice fetches the
    naming series from the pos profile
    """
    if isinstance(doc, str):
        doc = json.loads(doc)
    if doc.pos_profile:
        prof_doc = frappe.get_doc("POS Profile", doc.pos_profile)
        req_doc = prof_doc.sales_invoice_series or None
        if doc.is_new() and doc.pos_profile:
            doc.naming_series = req_doc
            frappe.db.commit()


def validate_sales_invoice(doc, event):
    if doc.posa_pos_opening_shift:
        if doc.outstanding_amount > 0.0:
            frappe.throw("Please complete payment for this POS invoice")
