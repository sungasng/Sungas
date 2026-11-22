"""Patch 0067 -- recorded stock less till receipts not yet closed, per plant and item."""
from frappe import _

from sungas.stock_available import available_rows


def execute(filters=None):
    f = filters or {}
    cols = [
        {"fieldname": "warehouse", "label": _("Plant"), "fieldtype": "Link", "options": "Warehouse", "width": 190},
        {"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 180},
        {"fieldname": "uom", "label": _("Unit"), "fieldtype": "Data", "width": 70},
        {"fieldname": "recorded", "label": _("Recorded"), "fieldtype": "Float", "width": 120},
        {"fieldname": "open_till", "label": _("Sold at Till, Not Yet Closed"), "fieldtype": "Float", "width": 190},
        {"fieldname": "available", "label": _("Available Now"), "fieldtype": "Float", "width": 130},
    ]
    return cols, available_rows(f.get("plant"), f.get("item_code"))
