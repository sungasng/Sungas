"""Patch 0032 -- Commercial Desk report."""
from frappe import _

from sungas.commercial_desk_data import leakage_rows


def execute(filters=None):
    f = filters or {}
    rows = leakage_rows(f.get("from_date"), f.get("to_date"), int(f.get("per_day") or 3))
    cols = [
        {"fieldname": "flag", "label": _("Flag"), "fieldtype": "Data", "width": 70},
        {"fieldname": "customer", "label": _("Account"), "fieldtype": "Link", "options": "Customer", "width": 180},
        {"fieldname": "customer_group", "label": _("Group"), "fieldtype": "Data", "width": 100},
        {"fieldname": "plant", "label": _("Till"), "fieldtype": "Link", "options": "POS Profile", "width": 140},
        {"fieldname": "cashier", "label": _("Cashier"), "fieldtype": "Link", "options": "User", "width": 170},
        {"fieldname": "invoices", "label": _("Invoices"), "fieldtype": "Int", "width": 80},
        {"fieldname": "kg", "label": _("LPG kg"), "fieldtype": "Float", "width": 90},
        {"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 110},
        {"fieldname": "max_per_day", "label": _("Most in One Day"), "fieldtype": "Int", "width": 110},
        {"fieldname": "busiest_day", "label": _("On"), "fieldtype": "Date", "width": 100},
    ]
    return cols, rows
