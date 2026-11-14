"""Patch 0041 -- paid LPG receipts still owed to customers (not filled, not refunded)."""
import frappe
from frappe import _
from frappe.utils import date_diff, flt, nowdate

from sungas.lpg_cylinders import REFILL_ITEMS
from sungas.lpg_fill import OWED


def execute(filters=None):
    from sungas.scheduled_jobs.briefing_figures import outlets_for

    f = filters or {}
    user = frappe.session.user
    whs = outlets_for(user, set(frappe.get_roles(user)))
    states = [f["status"]] if f.get("status") else list(OWED)
    rows = frappe.db.sql("""select inv.name, inv.posting_date, inv.pos_profile, pp.warehouse as plant, inv.customer_name,
                inv.owner, inv.sungas_fill_status as status, inv.sungas_fill_due as due, inv.grand_total,
                sum(it.stock_qty) as kg
            from `tabPOS Invoice` inv join `tabPOS Invoice Item` it on it.parent = inv.name and it.item_code in %(items)s
            left join `tabPOS Profile` pp on pp.name = inv.pos_profile
            where inv.docstatus = 1 and inv.sungas_fill_status in %(states)s
            group by inv.name order by inv.posting_date""",
                         {"items": REFILL_ITEMS, "states": tuple(states)}, as_dict=True)
    out = []
    for r in rows:
        if (whs is not None and r.plant not in whs) or (f.get("plant") and r.plant != f["plant"]):
            continue
        r.age = date_diff(nowdate(), r.posting_date)
        r.kg = flt(r.kg, 2)
        out.append(r)
    cols = [
        {"fieldname": "name", "label": _("Receipt"), "fieldtype": "Link", "options": "POS Invoice", "width": 170},
        {"fieldname": "posting_date", "label": _("Paid"), "fieldtype": "Date", "width": 95},
        {"fieldname": "age", "label": _("Days"), "fieldtype": "Int", "width": 60},
        {"fieldname": "plant", "label": _("Plant"), "fieldtype": "Link", "options": "Warehouse", "width": 170},
        {"fieldname": "customer_name", "label": _("Customer"), "fieldtype": "Data", "width": 170},
        {"fieldname": "kg", "label": _("kg"), "fieldtype": "Float", "width": 80},
        {"fieldname": "grand_total", "label": _("Paid (NGN)"), "fieldtype": "Currency", "width": 120},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 120},
        {"fieldname": "due", "label": _("Fill By"), "fieldtype": "Date", "width": 95},
        {"fieldname": "owner", "label": _("Cashier"), "fieldtype": "Link", "options": "User", "width": 160},
    ]
    return cols, out
