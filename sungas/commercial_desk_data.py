"""Patch 0032 -- Commercial Desk figures: LPG kg per customer, dormant accounts, upgrade prospects, leakage watch."""
from __future__ import annotations

import frappe
from frappe.utils import add_days, date_diff, flt, getdate, nowdate

PREMIUM = ("Commercial", "Distributors")
DORMANT_DAYS = 30
PROSPECT_MIN_KG = 200
LEAK_PER_DAY = 3

_INV_SQL = """
    select inv.name, inv.customer, inv.posting_date, inv.pos_profile, inv.owner,
           sum(case when it.item_group = 'LPG' then it.stock_qty else 0 end) as kg, inv.grand_total
    from `tab{dt}` inv join `tab{dt} Item` it on it.parent = inv.name
    where inv.docstatus = 1 and inv.posting_date between %(start)s and %(end)s {extra} {cust}
    group by inv.name"""


def invoices(start, end, customers=None) -> list[dict]:
    """Submitted POS Invoices + non-consolidated Sales Invoices with their LPG kg."""
    args = {"start": str(start), "end": str(end), "customers": tuple(customers or ()) or ("",)}
    cust = "and inv.customer in %(customers)s" if customers is not None else ""
    rows = []
    for dt, extra in (("POS Invoice", ""), ("Sales Invoice", "and inv.is_consolidated = 0")):
        rows += frappe.db.sql(_INV_SQL.format(dt=dt, extra=extra, cust=cust), args, as_dict=True)
    return rows


def kg_by_customer(rows) -> dict:
    out: dict = {}
    for r in rows:
        out[r["customer"]] = out.get(r["customer"], 0.0) + flt(r["kg"])
    return out


def last_purchase(customers) -> dict:
    out: dict = {}
    if not customers:
        return out
    for dt, extra in (("POS Invoice", ""), ("Sales Invoice", "and is_consolidated = 0")):
        for c, d in frappe.db.sql(f"select customer, max(posting_date) from `tab{dt}` where docstatus = 1 {extra} "
                                  "and customer in %(c)s group by customer", {"c": tuple(customers)}):
            if d and (c not in out or d > out[c]):
                out[c] = d
    return out


def account_rows(day=None) -> list[dict]:
    day = getdate(day or nowdate())
    mtd_start, lm_end = day.replace(day=1), add_days(day.replace(day=1), -1)
    lm_start = getdate(lm_end).replace(day=1)
    accts = frappe.get_all("Customer", filters={"customer_group": ["in", PREMIUM], "disabled": 0},
                           fields=["name", "customer_name", "customer_group", "sungas_account_owner", "sungas_expected_monthly_kg"])
    names = [a.name for a in accts]
    mtd = kg_by_customer(invoices(mtd_start, day, names)) if names else {}
    lm = kg_by_customer(invoices(lm_start, lm_end, names)) if names else {}
    last = last_purchase(names)
    out = []
    for a in accts:
        exp = flt(a.sungas_expected_monthly_kg)
        since = date_diff(day, last[a.name]) if a.name in last else None
        out.append({"customer": a.name, "customer_name": a.customer_name, "customer_group": a.customer_group,
                    "account_owner": a.sungas_account_owner, "expected_kg": exp, "kg_mtd": mtd.get(a.name, 0.0),
                    "kg_last_month": lm.get(a.name, 0.0),
                    "pct_of_expected": round(mtd.get(a.name, 0.0) * 100 / exp, 1) if exp else None,
                    "last_purchase": last.get(a.name), "days_since": since,
                    "dormant": 1 if since is None or since > DORMANT_DAYS else 0})
    return sorted(out, key=lambda r: (-r["dormant"], -(r["days_since"] or 9999), r["customer_name"] or ""))


def prospect_rows(days=30, min_kg=PROSPECT_MIN_KG, day=None) -> list[dict]:
    day = getdate(day or nowdate())
    rows = invoices(add_days(day, -int(days)), day)
    groups = dict(frappe.get_all("Customer", filters={"name": ["in", list({r["customer"] for r in rows}) or [""]]},
                                 fields=["name", "customer_group"], as_list=True))
    pending = set(frappe.get_all("Customer Group Change Request", filters={"status": "Pending"}, pluck="customer"))
    agg: dict = {}
    for r in rows:
        c = r["customer"]
        if groups.get(c) != "Retail" or (c or "").lower().startswith("walk-in"):
            continue
        a = agg.setdefault(c, {"customer": c, "kg": 0.0, "invoices": 0, "plants": set()})
        a["kg"] += flt(r["kg"])
        a["invoices"] += 1
        a["plants"].add(r["pos_profile"] or "-")
    out = [dict(a, plants=", ".join(sorted(a["plants"])), request_pending=1 if a["customer"] in pending else 0)
           for a in agg.values() if a["kg"] >= flt(min_kg)]
    return sorted(out, key=lambda r: -r["kg"])


def leakage_rows(start, end, per_day=LEAK_PER_DAY) -> list[dict]:
    """Sales to Commercial / Distributors accounts by account, plant and cashier; flag busy days."""
    accts = frappe.get_all("Customer", filters={"customer_group": ["in", PREMIUM]}, fields=["name", "customer_group"],
                           as_list=True)
    groups = dict(accts)
    if not groups:
        return []
    return aggregate_leakage(invoices(start, end, list(groups)), groups, per_day)


def aggregate_leakage(rows, groups, per_day=LEAK_PER_DAY) -> list[dict]:
    agg: dict = {}
    for r in rows:
        key = (r["customer"], r["pos_profile"] or "-", r["owner"])
        a = agg.setdefault(key, {"customer": key[0], "customer_group": groups.get(key[0]), "plant": key[1],
                                 "cashier": key[2], "invoices": 0, "kg": 0.0, "amount": 0.0, "days": {}})
        a["invoices"] += 1
        a["kg"] += flt(r["kg"])
        a["amount"] += flt(r["grand_total"])
        d = str(r["posting_date"])
        a["days"][d] = a["days"].get(d, 0) + 1
    out = []
    for a in agg.values():
        days = a.pop("days")
        a["max_per_day"] = max(days.values())
        a["busiest_day"] = max(days, key=days.get)
        a["flag"] = "Check" if a["max_per_day"] >= per_day else ""
        out.append(a)
    return sorted(out, key=lambda r: (r["flag"] != "Check", -r["max_per_day"], -r["kg"]))
