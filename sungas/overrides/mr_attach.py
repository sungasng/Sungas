"""Patch 0064 -- an MR approved after it was submitted (HoO ticks 'HoO Approved' and presses Update) was never
put on a Loading Schedule: the attach script runs on save / submit only. Run the same script on update-after-submit."""
import frappe

SCRIPT = "MR Attach To Loading Schedule"


def attach_after_update(doc, method=None):
    if doc.material_request_type != "Material Transfer" or not doc.get("hoo_approved") or doc.get("loading_schedule"):
        return
    if frappe.db.get_value("Server Script", SCRIPT, "disabled") == 0:
        frappe.get_doc("Server Script", SCRIPT).execute_doc(doc)
