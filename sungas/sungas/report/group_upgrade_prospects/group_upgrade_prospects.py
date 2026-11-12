"""Patch 0032 -- Commercial Desk report."""
from frappe import _

from sungas.commercial_desk_data import prospect_rows


def execute(filters=None):
    f = filters or {}
    rows = prospect_rows(f.get("days") or 30, f.get("min_kg") or 200)
    cols = [
        {"fieldname": "customer", "label": _("Retail Customer"), "fieldtype": "Link", "options": "Customer", "width": 200},
        {"fieldname": "kg", "label": _("LPG kg"), "fieldtype": "Float", "width": 100},
        {"fieldname": "invoices", "label": _("Invoices"), "fieldtype": "Int", "width": 80},
        {"fieldname": "plants", "label": _("Tills"), "fieldtype": "Data", "width": 220},
        {"fieldname": "request_pending", "label": _("Request Pending"), "fieldtype": "Check", "width": 110},
    ]
    return cols, rows
