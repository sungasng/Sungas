"""Patch 0065 -- a Plant Manager schedules trips only from his own plant, and never for a past date."""
import frappe
from frappe import _
from frappe.utils import getdate, today

FREE = {"LPG Head of Operations", "System Manager", "LPG Chief Operating Officer", "Chief Operating Officer"}
TRANSIT = "Goods In Transit - SCL"


def _free(user=None) -> bool:
    user = user or frappe.session.user
    return user in ("Administrator", "lmd-bot@sungas.org") or bool(FREE & set(frappe.get_roles(user)))


@frappe.whitelist()
def my_plants() -> list[str]:
    if _free():
        return []
    from sungas.lpg_fill import user_plants

    return sorted(w for w in user_plants(frappe.session.user) if w != TRANSIT)


def validate(doc, method=None):
    before = None if doc.is_new() else doc.get_doc_before_save()
    if _free() or doc.flags.ignore_permissions:  # system-created trips (MR attach, auto-close) are not user picks
        return
    if not before or before.source_outlet != doc.source_outlet:
        plants = my_plants()
        if doc.source_outlet not in plants:
            frappe.throw(_("You can schedule trips only from your own plant ({0}).").format(", ".join(plants) or "-"))
    if (not before or str(before.schedule_date) != str(doc.schedule_date)) and getdate(doc.schedule_date) < getdate(today()):
        frappe.throw(_("The schedule date cannot be in the past."))
