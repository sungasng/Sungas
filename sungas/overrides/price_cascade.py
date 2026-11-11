"""Patch 0030 -- an approved regional / national price replaces the plant prices below it.

Runs after POS Awesome has upserted the approved tier (on_submit of an approved
LPG Bulk Price Upload or LPG Price Change Request). For each row that actually
changes the price on a group territory (or blank = whole country), every enabled
tier for the same item, customer group and quantity band on a territory below it
is set to the new price -- except tiers the same upload sets itself. Broader rows
apply first so a regional row in the same upload beats a national one.
"""
from __future__ import annotations

import frappe
from frappe.utils import flt

Key = tuple


def _key(item, group, territory, lo, hi) -> Key:
    return (item, group, territory or "", flt(lo), flt(hi))


def _bounds(territory):
    if not territory:
        return None
    return frappe.db.get_value("Territory", territory, ["lft", "rgt", "is_group"], as_dict=True)


def changed(r) -> bool:
    return flt(r.get("rate")) > 0 and flt(r.get("rate")) != flt(r.get("current_rate"))


def cascade(rows: list[dict], force: bool = False, keep=()) -> list[str]:
    """rows: item_code, customer_group, territory, min_qty, max_qty, rate, current_rate, valid_from, valid_to.
    force: treat every row as a change (re-apply); keep: plant territories to leave alone."""
    rows = [r for r in rows if force or changed(r)]
    explicit = {_key(r["item_code"], r["customer_group"], r.get("territory"), r.get("min_qty"), r.get("max_qty")) for r in rows}
    scoped = []
    for r in rows:
        b = _bounds(r.get("territory"))
        if r.get("territory") and (not b or not b.is_group):
            continue
        scoped.append((r, b))
    scoped.sort(key=lambda x: -(x[1].rgt - x[1].lft) if x[1] else float("-inf"))
    applied = []
    for r, b in scoped:
        if b:
            below = frappe.get_all("Territory", filters={"lft": [">", b.lft], "rgt": ["<", b.rgt]}, pluck="name")
        else:
            below = frappe.get_all("Territory", pluck="name")
        if not below:
            continue
        for t in frappe.get_all("LPG Outlet Price Tier", filters={
                "item_code": r["item_code"], "customer_group": r["customer_group"], "enabled": 1,
                "territory": ["in", below], "min_qty": flt(r.get("min_qty")), "max_qty": flt(r.get("max_qty"))},
                fields=["name", "territory", "rate"]):
            if t.territory in keep or \
                    _key(r["item_code"], r["customer_group"], t.territory, r.get("min_qty"), r.get("max_qty")) in explicit:
                continue
            if flt(t.rate) == flt(r["rate"]):
                continue
            doc = frappe.get_doc("LPG Outlet Price Tier", t.name)
            doc.rate = flt(r["rate"])
            if r.get("valid_from"):
                doc.valid_from = r["valid_from"]
            if r.get("valid_to"):
                doc.valid_to = r["valid_to"]
            doc.save(ignore_permissions=True)
            applied.append(f"{t.territory}: {flt(t.rate):,.2f} -> {flt(r['rate']):,.2f} ({r['customer_group']}, {r['item_code']})")
    return applied


def _note(doc, applied):
    if applied:
        doc.add_comment("Info", "Regional/national price applied to plants below it:<br>" + "<br>".join(applied))


def _bulk_rows(doc):
    return [{"item_code": r.item_code, "customer_group": r.customer_group, "territory": r.territory,
             "min_qty": r.min_qty, "max_qty": r.max_qty, "rate": r.new_rate, "current_rate": r.current_rate,
             "valid_from": r.valid_from, "valid_to": r.valid_to} for r in doc.rows if r.enabled]


def on_bulk_approved(doc, method=None):
    if (doc.workflow_state or "") != "Approved":
        return
    _note(doc, cascade(_bulk_rows(doc)))


@frappe.whitelist()
def reapply(name, keep=None):
    """System Manager: push an already-approved Bulk Price Upload's regional/national rows down to plants."""
    import json

    frappe.only_for("System Manager")
    doc = frappe.get_doc("LPG Bulk Price Upload", name)
    if doc.workflow_state != "Approved":
        frappe.throw("Only an approved upload can be re-applied.")
    applied = cascade(_bulk_rows(doc), force=True, keep=set(json.loads(keep) if isinstance(keep, str) else keep or []))
    _note(doc, applied)
    return applied


def on_pcr_approved(doc, method=None):
    if (doc.workflow_state or "") != "Approved":
        return
    _note(doc, cascade([{
        "item_code": doc.item_code, "customer_group": doc.customer_group, "territory": doc.territory,
        "min_qty": doc.min_qty, "max_qty": doc.max_qty, "rate": doc.proposed_rate, "current_rate": doc.current_rate,
        "valid_from": doc.get("valid_from"), "valid_to": doc.get("valid_to")}]))
