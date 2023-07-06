from erpnext.selling.doctype.customer.customer import Customer
import frappe


class CustomerOverride(Customer):
    
    def on_doctype_update(self):
        frappe.db.add_index("Customer   ", ["mobile_no", "email_id"])