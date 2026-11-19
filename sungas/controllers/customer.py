import json
import re

import frappe


def _digits(phone) -> str:
    return re.sub(r"\D", "", phone or "")[-10:]


@frappe.whitelist()
def validate_customer(doc, event):
    """Patch 0062: a mobile number and an email belong to one customer company-wide (names may repeat)."""
    if isinstance(doc, str):
        doc = frappe.get_doc(json.loads(doc))
    before = None if doc.is_new() else doc.get_doc_before_save()
    phone = _digits(doc.mobile_no)
    if phone and (not before or _digits(before.mobile_no) != phone):
        other = frappe.db.sql(
            """select name, customer_name, territory from `tabCustomer`
               where name != %s and right(regexp_replace(ifnull(mobile_no, ''), '[^0-9]', ''), 10) = %s limit 1""",
            (doc.name or "", phone), as_dict=True)
        if other:
            o = other[0]
            frappe.throw(f"Mobile number {doc.mobile_no} already belongs to {o.customer_name} ({o.territory}). "
                         "Search for that customer instead.", title="Customer already exists")
    email = (doc.email_id or "").strip().lower()
    if email and (not before or (before.email_id or "").strip().lower() != email):
        other = frappe.db.sql(
            """select customer_name, territory from `tabCustomer` where name != %s and lower(trim(email_id)) = %s limit 1""",
            (doc.name or "", email), as_dict=True)
        if other:
            o = other[0]
            frappe.throw(f"Email {doc.email_id} already belongs to {o.customer_name} ({o.territory}). "
                         "Search for that customer instead.", title="Customer already exists")
