import frappe


@frappe.whitelist()
def submit_journal_entry(doc, event):
    doc.approving_user = frappe.session.user
