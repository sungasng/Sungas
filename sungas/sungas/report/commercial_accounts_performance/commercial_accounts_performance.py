"""Patch 0032 -- Commercial Desk report."""
from frappe import _

from sungas.commercial_desk_data import DORMANT_DAYS, account_rows


def execute(filters=None):
    f = filters or {}
    rows = account_rows(f.get("as_of"))
    if f.get("dormant_only"):
        rows = [r for r in rows if r["dormant"]]
    cols = [
        {"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link", "options": "Customer", "width": 130},
        {"fieldname": "customer_name", "label": _("Name"), "fieldtype": "Data", "width": 180},
        {"fieldname": "customer_group", "label": _("Group"), "fieldtype": "Data", "width": 100},
        {"fieldname": "account_owner", "label": _("Account Owner"), "fieldtype": "Link", "options": "User", "width": 150},
        {"fieldname": "kg_mtd", "label": _("kg MTD"), "fieldtype": "Float", "width": 90},
        {"fieldname": "kg_last_month", "label": _("kg Last Month"), "fieldtype": "Float", "width": 100},
        {"fieldname": "expected_kg", "label": _("Expected kg/mo"), "fieldtype": "Float", "width": 100},
        {"fieldname": "pct_of_expected", "label": _("% of Expected"), "fieldtype": "Percent", "width": 90},
        {"fieldname": "last_purchase", "label": _("Last Purchase"), "fieldtype": "Date", "width": 100},
        {"fieldname": "days_since", "label": _("Days Since"), "fieldtype": "Int", "width": 80},
        {"fieldname": "dormant", "label": _("Dormant (>{0}d)").format(DORMANT_DAYS), "fieldtype": "Check", "width": 90},
    ]
    return cols, rows
