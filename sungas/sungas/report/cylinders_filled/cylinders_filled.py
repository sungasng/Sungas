"""Patch 0038 -- LPG refills by cylinder size per till and cashier."""
import frappe
from frappe import _

from sungas.lpg_cylinders import REFILL_ITEMS, UNKNOWN, is_cyl_uom


def execute(filters=None):
    f = filters or {}
    cond = "and inv.pos_profile = %(pos_profile)s" if f.get("pos_profile") else ""
    rows = frappe.db.sql(f"""
        select inv.pos_profile, inv.owner, it.uom, it.sungas_fill_into, count(distinct inv.name) as receipts,
               sum(it.qty) as qty, sum(it.stock_qty) as kg, sum(it.amount) as amount
        from `tabPOS Invoice` inv join `tabPOS Invoice Item` it on it.parent = inv.name
        where inv.docstatus = 1 and inv.is_return = 0 and it.item_code in %(items)s
          and inv.posting_date between %(from_date)s and %(to_date)s {cond}
        group by inv.pos_profile, inv.owner, it.uom, it.sungas_fill_into
        order by inv.pos_profile, inv.owner, kg desc""",
        dict(f, items=tuple(REFILL_ITEMS)), as_dict=True)
    for r in rows:
        cyl = is_cyl_uom(r.uom)
        r.size = r.uom if cyl else f"kg / amount into {r.sungas_fill_into or UNKNOWN}"
        r.cylinders = r.qty if cyl else None
    cols = [
        {"fieldname": "pos_profile", "label": _("Till"), "fieldtype": "Link", "options": "POS Profile", "width": 150},
        {"fieldname": "owner", "label": _("Cashier"), "fieldtype": "Link", "options": "User", "width": 170},
        {"fieldname": "size", "label": _("Size / Fill"), "fieldtype": "Data", "width": 220},
        {"fieldname": "cylinders", "label": _("Cylinders"), "fieldtype": "Float", "width": 90},
        {"fieldname": "kg", "label": _("kg"), "fieldtype": "Float", "width": 90},
        {"fieldname": "receipts", "label": _("Receipts"), "fieldtype": "Int", "width": 80},
        {"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 120},
    ]
    return cols, rows
