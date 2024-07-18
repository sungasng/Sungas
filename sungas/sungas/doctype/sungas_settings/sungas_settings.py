# Copyright (c) 2022, Manqala and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SungasSettings(Document):

    def on_save(self):
        frappe.clear_document_cache(self.doctype)
