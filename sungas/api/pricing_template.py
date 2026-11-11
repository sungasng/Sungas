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


def _date(v):
    v = (v or "").strip()
    if not v:
        return None
    try:
        return str(frappe.utils.getdate(v))
    except Exception:
        return v


def parse_rows(text: str) -> list[dict]:
    """Template / CSV text -> Bulk Price Upload rows. Rows whose new_rate equals the
    reference current_rate column (unchanged template rows) are skipped."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    missing = {"item_code", "customer_group", "new_rate"} - set(reader.fieldnames or [])
    if missing:
        frappe.throw("The file is missing column(s): " + ", ".join(sorted(missing)))
    out = []
    for raw in reader:
        code = (raw.get("item_code") or "").strip()
        if not code:
            continue
        new = flt(raw.get("new_rate"))
        cur = (raw.get("current_rate") or "").strip()
        if cur and flt(cur) == new:
            continue
        out.append({"item_code": code, "customer_group": (raw.get("customer_group") or "").strip() or None,
                    "territory": (raw.get("territory") or "").strip() or None,
                    "min_qty": flt(raw.get("min_qty")), "max_qty": flt(raw.get("max_qty")), "new_rate": new,
                    "valid_from": _date(raw.get("valid_from")), "valid_to": _date(raw.get("valid_to")),
                    "justification": (raw.get("justification") or "").strip() or None, "enabled": 1})
    return out


@frappe.whitelist()
def parse_template(file_url):
    """Patch 0030a: read an attached template on the form so the rows table is filled before saving."""
    if not ALLOWED & set(frappe.get_roles()):
        frappe.throw("Only Head of Sales, Head of Finance or System Manager can load a price file.",
                     frappe.PermissionError)
    content = frappe.get_doc("File", {"file_url": file_url}).get_content()
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    return parse_rows(content)
