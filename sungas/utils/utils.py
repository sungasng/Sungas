import frappe
from six import string_types
import json


@frappe.whitelist()
def validate_customer(doc,ev):
    #Validate that a customer cannot be created twice within the same territory
    if isinstance(doc,string_types):
        doc=json.loads(doc)
    if doc.is_new():
        exists = frappe.get_all("Customer",{'Territory':doc.territory,'mobile_no':doc.mobile_no})
        if exists:
            frappe.throw(f"Please not that a customer with mobile no {doc.mobile_no} in territory {doc.territory} already exists")


@frappe.whitelist()
def validate_sales_invoice(doc,ev):
    #Validate that a Sales invoice fetches the naming series from the pos profile
    if isinstance(doc,string_types):
        doc=json.loads(doc)
    new_doc = doc
    if doc.is_new() and doc.pos_profile and bool(frappe.get_value("Pos Profile",doc.pos_profile,'sales_invoice_naming_series')):
        doc.naming_series = frappe.get_value("Pos Profile",doc.pos_profile,'sales_invoice_naming_series')
        
        frappe.db.commit()
        return

    
