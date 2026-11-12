import frappe
from frappe import _
from frappe.model.document import Document

from sungas.commercial_desk import can_set_group, notify_new_request


class CustomerGroupChangeRequest(Document):
    def validate(self):
        if self.is_new():
            self.requested_by = self.requested_by or frappe.session.user
            if not self.flags.sungas_internal:
                self.current_group = frappe.db.get_value("Customer", self.customer, "customer_group")
        elif not self.flags.sungas_internal and not can_set_group(frappe.get_roles()):
            frappe.throw(_("Only the Commercial Desk can change a group change request after it is raised."))
        if self.flags.sungas_internal:
            return
        if frappe.db.get_value("Customer Group", self.requested_group, "is_group"):
            frappe.throw(_("Pick a specific customer group, not {0}.").format(self.requested_group))
        if self.requested_group == self.current_group:
            frappe.throw(_("{0} is already in {1}.").format(self.customer_name or self.customer, self.current_group))
        if self.is_new():
            self.status = "Pending"
            dup = frappe.db.exists("Customer Group Change Request",
                                   {"customer": self.customer, "status": "Pending", "name": ["!=", self.name or ""]})
            if dup:
                frappe.throw(_("Request {0} for this customer is already waiting for the Commercial Desk.").format(dup))

    def after_insert(self):
        if self.status == "Pending":
            notify_new_request(self)

