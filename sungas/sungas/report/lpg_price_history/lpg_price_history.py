"""Patch 0029 -- LPG Price History.

Every selling-price change over time with who requested and approved it:
  * Price Change Request (approved): Plant Manager -> Head of Sales -> Head of Finance
  * Bulk Price Upload (approved): uploader -> Head of Finance
  * Direct / system: tier or price-list changes not made by the two routes
    (one-off loads, edits before the Patch 0028 lock, national price-list sync)
Plant managers see only their own plant(s) plus national prices.
"""
from __future__ import annotations

import json

import frappe
from frappe.utils import flt, get_datetime, getdate, time_diff_in_seconds

ALL_ROLES = {"System Manager", "LPG Head of Sales", "LPG Head of Finance", "LPG Head of Operations",
             "COO", "Internal Control", "Accounts Manager"}
MATCH_SECONDS = 600


def execute(filters=None):
    f = frappe._dict(filters or {})
    rows = pcr_rows(f) + bulk_rows(f)
    rows += direct_rows(f, {(r["tier"], r["_approved"]) for r in rows if r.get("tier")})
    rows = [r for r in rows if _in_scope(r, f, allowed_territories(frappe.session.user))]
    rows.sort(key=lambda r: (r["_approved"] or get_datetime("1900-01-01")), reverse=True)
    names = {}
    for r in rows:
        for k in ("requested_by", "plant_manager", "head_of_sales", "head_of_finance"):
            u = r.get(k)
            if u and u not in names:
                names[u] = frappe.db.get_value("User", u, "full_name") or u
            r[k] = names.get(u, u) if u else None
        r.pop("_approved", None)
    return columns(), rows


def columns():
    c = [("changed_on", "Changed On", "Datetime", 150), ("item_code", "Item", "Link/Item", 110),
         ("item_name", "Item Name", "Data", 140), ("customer_group", "Customer Group", "Data", 110),
         ("territory", "Plant", "Data", 110), ("qty_band", "Qty Band", "Data", 90),
         ("old_rate", "Old Price", "Currency", 100), ("new_rate", "New Price", "Currency", 100),
         ("pct_change", "Change %", "Percent", 80), ("route", "Route", "Data", 150),
         ("requested_by", "Requested By", "Data", 130), ("plant_manager", "Plant Manager", "Data", 130),
         ("plant_manager_on", "PM Approved", "Datetime", 140), ("head_of_sales", "Head of Sales", "Data", 130),
         ("head_of_sales_on", "HoS Approved", "Datetime", 140), ("head_of_finance", "Head of Finance", "Data", 130),
         ("head_of_finance_on", "HoF Approved", "Datetime", 140), ("reason", "Reason", "Data", 220),
         ("ref_doctype", "Document Type", "Data", 140), ("ref_name", "Document", "Dynamic Link/ref_doctype", 140)]
    out = []
    for name, label, ftype, width in c:
        col = {"fieldname": name, "label": label, "width": width}
        if "/" in ftype:
            col["fieldtype"], col["options"] = ftype.split("/")
        else:
            col["fieldtype"] = ftype
        out.append(col)
    return out


def _band(lo, hi) -> str:
    lo, hi = flt(lo), flt(hi)
    return "" if not lo and not hi else f"{lo:g}-{hi:g}" if hi else f"{lo:g}+"


def _pct(old, new):
    return round((flt(new) - flt(old)) * 100.0 / flt(old), 2) if flt(old) else None


def _row(**kw) -> dict:
    kw["pct_change"] = _pct(kw.get("old_rate"), kw.get("new_rate"))
    kw.setdefault("changed_on", kw.get("_approved"))
    return kw


def _span(f):
    return ["between", [f"{f.from_date} 00:00:00", f"{f.to_date} 23:59:59"]]


def pcr_rows(f) -> list[dict]:
    out = []
    for p in frappe.get_all("LPG Price Change Request",
                            filters={"workflow_state": "Approved", "head_of_finance_approved_on": _span(f)},
                            fields=["name", "item_code", "item_name", "customer_group", "territory", "min_qty", "max_qty",
                                    "current_rate", "proposed_rate", "reason", "requester", "plant_manager",
                                    "plant_manager_approved_on", "head_of_sales", "head_of_sales_approved_on",
                                    "head_of_finance", "head_of_finance_approved_on", "created_tier"]):
        out.append(_row(
            _approved=get_datetime(p.head_of_finance_approved_on), item_code=p.item_code, item_name=p.item_name,
            customer_group=p.customer_group, territory=p.territory, qty_band=_band(p.min_qty, p.max_qty),
            old_rate=p.current_rate, new_rate=p.proposed_rate, route="Price Change Request",
            requested_by=p.requester, plant_manager=p.plant_manager, plant_manager_on=p.plant_manager_approved_on,
            head_of_sales=p.head_of_sales, head_of_sales_on=p.head_of_sales_approved_on,
            head_of_finance=p.head_of_finance, head_of_finance_on=p.head_of_finance_approved_on,
            reason=p.reason, ref_doctype="LPG Price Change Request", ref_name=p.name, tier=p.created_tier))
    return out


def bulk_rows(f) -> list[dict]:
    out = []
    for b in frappe.get_all("LPG Bulk Price Upload", filters={"workflow_state": "Approved", "finance_approved_on": _span(f)},
                            fields=["name", "uploader", "approved_by_finance", "finance_approved_on", "description"]):
        for r in frappe.get_all("LPG Bulk Price Upload Row", filters={"parent": b.name},
                                fields=["item_code", "item_name", "customer_group", "territory", "min_qty", "max_qty",
                                        "current_rate", "new_rate", "justification", "created_tier"]):
            out.append(_row(
                _approved=get_datetime(b.finance_approved_on), item_code=r.item_code, item_name=r.item_name,
                customer_group=r.customer_group, territory=r.territory, qty_band=_band(r.min_qty, r.max_qty),
                old_rate=r.current_rate, new_rate=r.new_rate, route="Bulk Price Upload", requested_by=b.uploader,
                head_of_finance=b.approved_by_finance, head_of_finance_on=b.finance_approved_on,
                reason=r.justification or b.description, ref_doctype="LPG Bulk Price Upload", ref_name=b.name,
                tier=r.created_tier))
    return out


def _rate(v) -> float:
    return flt(str(v or 0).replace("\u20a6", "").replace(",", "").strip())


def is_route_change(tier, at, routed) -> bool:
    return any(t == tier and ap and abs(time_diff_in_seconds(at, ap)) <= MATCH_SECONDS for t, ap in routed)


def direct_rows(f, routed) -> list[dict]:
    out = []
    span = _span(f)
    for dt, rate_field, route in (("LPG Outlet Price Tier", "rate", "Direct / system (tier)"),
                                  ("Item Price", "price_list_rate", "Price list (national)")):
        is_tier = dt == "LPG Outlet Price Tier"
        fields = ["name", "item_code", "item_name", "creation", "owner", rate_field] + (
            ["customer_group", "territory", "min_qty", "max_qty"] if is_tier else ["price_list"])
        filters = {} if is_tier else {"selling": 1}
        docs = {d.name: d for d in frappe.get_all(dt, filters=filters, fields=fields)}
        versions = frappe.get_all("Version", filters={"ref_doctype": dt}, fields=["docname", "owner", "creation", "data"],
                                  order_by="creation asc")
        first_old = {}
        for v in sorted(versions, key=lambda v: get_datetime(v.creation)):
            d = docs.get(v.docname)
            if not d:
                continue
            ch = [c for c in json.loads(v.data or "{}").get("changed") or [] if c[0] == rate_field]
            if not ch:
                continue
            first_old.setdefault(v.docname, _rate(ch[0][1]))
            at = get_datetime(v.creation)
            if not (getdate(f.from_date) <= at.date() <= getdate(f.to_date)) or (is_tier and is_route_change(v.docname, at, routed)):
                continue
            out.append(_direct(d, is_tier, at, v.owner, _rate(ch[0][1]), _rate(ch[0][2]), route, dt))
        for name, d in docs.items():
            at = get_datetime(d.creation)
            if span[1][0] <= str(at) <= span[1][1] and not (is_tier and is_route_change(name, at, routed)):
                out.append(_direct(d, is_tier, at, d.owner, None, first_old.get(name, flt(d[rate_field])), route + " - created", dt))
    return out


def _direct(d, is_tier, at, user, old, new, route, dt) -> dict:
    return _row(_approved=at, item_code=d.item_code, item_name=d.item_name,
                customer_group=d.customer_group if is_tier else "All (price list)",
                territory=d.territory if is_tier else "", qty_band=_band(d.min_qty, d.max_qty) if is_tier else "",
                old_rate=old, new_rate=new, route=route, requested_by=user,
                reason="" if is_tier else d.price_list, ref_doctype=dt, ref_name=d.name)


def allowed_territories(user):
    """None = everything; set = plant manager's territories (national rows always shown)."""
    roles = set(frappe.get_roles(user))
    if roles & ALL_ROLES:
        return None
    whs = frappe.get_all("Warehouse", or_filters={"outlet_plant_manager": user, "outlet_secondary_manager": user},
                         pluck="name")
    return {w.replace(" - SCL", "") for w in whs}


def _in_scope(r, f, allowed) -> bool:
    t = r.get("territory") or ""
    if allowed is not None and t and t not in allowed:
        return False
    if f.item_code and r.get("item_code") != f.item_code:
        return False
    if f.territory and t != f.territory:
        return False
    if f.customer_group and r.get("customer_group") != f.customer_group:
        return False
    return True
