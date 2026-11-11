"""Patch 0030 -- pre-filled Bulk Price Upload CSV template (current prices)."""
from __future__ import annotations

import csv
import io

import frappe
from frappe.utils import flt

ALLOWED = {"LPG Head of Sales", "LPG Head of Finance", "System Manager"}
HEADER = ["item_code", "customer_group", "territory", "min_qty", "max_qty", "new_rate", "valid_from", "valid_to",
          "justification", "item_name", "current_rate", "level"]


ROOTS = (None, "", "All Territories")


def _level(territory, terr: dict) -> str:
    t = terr.get(territory)
    if not territory or not t or t.parent_territory in ROOTS:
        return "National"
    return "Regional" if t.is_group else "Plant"


def build_rows(item_code=None, customer_group=None, territory=None) -> list[list]:
    filters = {"enabled": 1}
    if item_code:
        filters["item_code"] = item_code
    if customer_group:
        filters["customer_group"] = customer_group
    if territory:
        b = frappe.db.get_value("Territory", territory, ["lft", "rgt"], as_dict=True)
        filters["territory"] = ["in", frappe.get_all("Territory", filters={"lft": [">=", b.lft], "rgt": ["<=", b.rgt]},
                                                     pluck="name")]
    terr = {t.name: t for t in frappe.get_all("Territory", fields=["name", "lft", "is_group", "parent_territory"])}
    tiers = frappe.get_all("LPG Outlet Price Tier", filters=filters,
                           fields=["item_code", "item_name", "customer_group", "territory", "min_qty", "max_qty", "rate"])
    tiers.sort(key=lambda t: (t.item_code, t.customer_group, terr[t.territory].lft if t.territory in terr else 0,
                              flt(t.min_qty)))
    return [[t.item_code, t.customer_group, t.territory or "", flt(t.min_qty), flt(t.max_qty), flt(t.rate), "", "", "",
             t.item_name or "", flt(t.rate), _level(t.territory, terr)] for t in tiers]


@frappe.whitelist()
def download_bulk_template(item_code=None, customer_group=None, territory=None):
    if not ALLOWED & set(frappe.get_roles()):
        frappe.throw("Only Head of Sales, Head of Finance or System Manager can download the price template.",
                     frappe.PermissionError)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADER)
    w.writerows(build_rows(item_code, customer_group, territory))
    frappe.response["filename"] = f"bulk_price_template_{frappe.utils.nowdate()}.csv"
    frappe.response["filecontent"] = "\ufeff" + buf.getvalue()
    frappe.response["type"] = "download"
