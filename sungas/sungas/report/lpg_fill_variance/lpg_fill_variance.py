"""Patch 0041 -- kg sold on the receipt vs kg the filler dispensed, by plant and filler."""
import frappe
from frappe import _
from frappe.utils import flt

from sungas.lpg_fill import is_variance


def execute(filters=None):
    from sungas.scheduled_jobs.briefing_figures import outlets_for

    f = filters or {}
    user = frappe.session.user
    whs = outlets_for(user, set(frappe.get_roles(user)))
    rows = frappe.db.sql("""select pp.warehouse as plant, inv.sungas_filled_by as filler, inv.name,
                inv.sungas_filled_kg as filled, inv.sungas_fill_variance_kg as variance, inv.net_total, inv.grand_total
            from `tabPOS Invoice` inv left join `tabPOS Profile` pp on pp.name = inv.pos_profile
            where inv.docstatus = 1 and inv.sungas_fill_status = 'Filled'
              and inv.sungas_filled_at between %(a)s and %(b)s""",
                         {"a": f"{f.get('from_date')} 00:00:00", "b": f"{f.get('to_date')} 23:59:59"}, as_dict=True)
    groups = {}
    for r in rows:
        if (whs is not None and r.plant not in whs) or (f.get("plant") and r.plant != f["plant"]):
            continue
        sold = flt(r.filled) - flt(r.variance)
        g = groups.setdefault((r.plant, r.filler), {"plant": r.plant, "filler": r.filler, "receipts": 0, "sold_kg": 0.0,
                                                    "filled_kg": 0.0, "variance_kg": 0.0, "flagged": 0, "over_kg": 0.0,
                                                    "value": 0.0})
        g["receipts"] += 1
        g["sold_kg"] += sold
        g["filled_kg"] += flt(r.filled)
        g["variance_kg"] += flt(r.variance)
        g["over_kg"] += max(flt(r.variance), 0)
        g["flagged"] += 1 if is_variance(sold, r.filled) else 0
        g["value"] += flt(r.variance) * (flt(r.net_total) / sold if sold else 0)
    out = sorted(groups.values(), key=lambda g: (-abs(g["variance_kg"]), str(g["plant"])))
    for g in out:
        g["variance_pct"] = g["variance_kg"] / g["sold_kg"] * 100 if g["sold_kg"] else 0
    cols = [
        {"fieldname": "plant", "label": _("Plant"), "fieldtype": "Link", "options": "Warehouse", "width": 170},
        {"fieldname": "filler", "label": _("Filler"), "fieldtype": "Link", "options": "User", "width": 170},
        {"fieldname": "receipts", "label": _("Receipts"), "fieldtype": "Int", "width": 80},
        {"fieldname": "sold_kg", "label": _("kg Sold"), "fieldtype": "Float", "width": 90},
        {"fieldname": "filled_kg", "label": _("kg Filled"), "fieldtype": "Float", "width": 90},
        {"fieldname": "variance_kg", "label": _("Variance kg"), "fieldtype": "Float", "width": 100},
        {"fieldname": "variance_pct", "label": _("Variance %"), "fieldtype": "Percent", "width": 90},
        {"fieldname": "over_kg", "label": _("Over-filled kg"), "fieldtype": "Float", "width": 110},
        {"fieldname": "value", "label": _("Variance (NGN)"), "fieldtype": "Currency", "width": 120},
        {"fieldname": "flagged", "label": _("Flagged"), "fieldtype": "Int", "width": 80},
    ]
    return cols, out
