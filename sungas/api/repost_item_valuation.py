import frappe
from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import (
    repost
)


@frappe.whitelist()
def repost_entry(doc):

    doc = frappe.get_doc("Repost Item Valuation", doc)
    frappe.enqueue(
        repost, timeout=99000,
        queue='long', job_name='repost_sle',
        now=frappe.flags.in_test, doc=doc
    )

    return True
