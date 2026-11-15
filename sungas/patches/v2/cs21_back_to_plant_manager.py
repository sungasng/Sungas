"""Patch 0050 one-off: POSA-CS-26-0000021 passed the Plant Manager and Head of Operations before its
investigation was done. Send it back to the Plant Manager and clear the early stamps."""
import frappe
from frappe.utils import now_datetime

CS = "POSA-CS-26-0000021"


def execute():
    row = frappe.db.get_value("POS Closing Shift", CS, ["docstatus", "workflow_state", "pos_variance_investigation"],
                              as_dict=True)
    if not row or row.docstatus != 0 or row.workflow_state not in ("Pending HOD Operations", "Pending HOD Finance"):
        return
    frappe.db.set_value("POS Closing Shift", CS, {"workflow_state": "Pending Plant Manager",
                                                  "variance_state_entered_at": now_datetime(),
                                                  "plant_manager_signed_by": None, "plant_manager_signed_on": None,
                                                  "hod_ops_signed_by": None, "hod_ops_signed_on": None}, update_modified=False)
    if row.pos_variance_investigation:
        frappe.db.set_value("POS Variance Investigation", row.pos_variance_investigation,
                            {"hod_ops_signed_by": None, "hod_ops_signed_on": None}, update_modified=False)
        from sungas.overrides.pvi_rules import tell_cashier

        tell_cashier(row.pos_variance_investigation)
    note = ("Sent back to the Plant Manager (patch 0050): it was approved by the Plant Manager and Head of Operations "
            "before its investigation was finished. Approve again once the investigation is submitted.")
    frappe.get_doc("POS Closing Shift", CS).add_comment("Comment", note)
    from sungas.overrides.closing_approval_alerts import send

    send(CS, "Pending Plant Manager")
