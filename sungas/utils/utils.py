import frappe
from six import string_types
import json
from frappe.utils import strip

def item_name(doc,ev):
    if frappe.db.get_default("item_naming_by") == "Naming Series":
        if doc.variant_of:
            doc.naming_series = frappe.db.get_value("Item",doc.variant_of,'naming_series')
        from frappe.model.naming import set_name_by_naming_series
        set_name_by_naming_series(doc)
        doc.item_code = doc.name



@frappe.whitelist()
def submit_je(doc,ev):
    doc.approving_user = frappe.session.user
    # doc.save()
    

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
    if doc.pos_profile:
        prof_doc = frappe.get_doc("POS Profile",doc.pos_profile)
        req_doc = prof_doc.sales_invoice_series or None
        if doc.is_new() and doc.pos_profile :
            doc.naming_series = req_doc
            frappe.db.commit()
            return

    
