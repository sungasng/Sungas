# Copyright (c) 2026, Manqala and contributors
"""Every amount charged to a cashier (2608 Cashier Recovery) and every repayment, with a running balance."""
import re

import frappe
from frappe import _
from frappe.utils import flt

REF = re.compile(r"(PVI-\d+-\d+|POSA-CS-\d+-\d+)")


def execute(filters=None):
    f = frappe._dict(filters or {})
    acct = frappe.db.get_single_value("Sungas Close Policy", "cashier_recovery_account")
    if not acct:
        frappe.throw(_("Set the Cashier Recovery account on the Sungas Close Policy page."))
    cond = {"account": acct, "is_cancelled": 0, "party_type": "Employee"}
    if f.employee:
        cond["party"] = f.employee
    if f.to_date:
        cond["posting_date"] = ["<=", f.to_date]
    rows = frappe.get_all("GL Entry", filters=cond, order_by="party, posting_date, creation",
                          fields=["party", "posting_date", "voucher_type", "voucher_no", "debit", "credit", "remarks"])
    names = dict(frappe.get_all("Employee", fields=["name", "employee_name"], as_list=True))
    branch = dict(frappe.get_all("Employee", fields=["name", "branch"], as_list=True))
    titles = {r.voucher_no: r.title for r in frappe.get_all(
        "Journal Entry", filters={"name": ["in", list({r.voucher_no for r in rows if r.voucher_type == "Journal Entry"}) or [""]]},
        fields=["name", "title"])}
    data, bal, last, summary = [], 0.0, None, {}
    for r in rows:
        if r.party != last:
            bal, last = 0.0, r.party
        bal += flt(r.debit) - flt(r.credit)
        s = summary.setdefault(r.party, {"charged": 0.0, "repaid": 0.0})
        s["charged"] += flt(r.debit)
        s["repaid"] += flt(r.credit)
        if f.from_date and str(r.posting_date) < str(f.from_date):
            continue
        refs = REF.findall(f"{titles.get(r.voucher_no, '')} {r.remarks or ''}")
        data.append({
            "employee": r.party, "cashier": names.get(r.party), "plant": branch.get(r.party),
            "posting_date": r.posting_date, "voucher_type": r.voucher_type, "voucher_no": r.voucher_no,
            "case": next((x for x in refs if x.startswith("PVI")), None),
            "shift": next((x for x in refs if x.startswith("POSA")), None),
            "charged": flt(r.debit), "repaid": flt(r.credit), "balance": bal,
        })
    if f.summary:
        data = [{"employee": e, "cashier": names.get(e), "plant": branch.get(e), "charged": v["charged"],
                 "repaid": v["repaid"], "balance": v["charged"] - v["repaid"]} for e, v in summary.items()
                if not f.outstanding_only or abs(v["charged"] - v["repaid"]) > 0.005]
    return columns(f.summary), data


def columns(summary):
    c = [
        {"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 120},
        {"fieldname": "cashier", "label": _("Cashier"), "fieldtype": "Data", "width": 170},
        {"fieldname": "plant", "label": _("Plant"), "fieldtype": "Data", "width": 110},
    ]
    if not summary:
        c += [
            {"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
            {"fieldname": "voucher_type", "label": _("Voucher Type"), "fieldtype": "Data", "width": 110},
            {"fieldname": "voucher_no", "label": _("Voucher"), "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 160},
            {"fieldname": "case", "label": _("Case"), "fieldtype": "Link", "options": "POS Variance Investigation", "width": 120},
            {"fieldname": "shift", "label": _("Closing Shift"), "fieldtype": "Link", "options": "POS Closing Shift", "width": 150},
        ]
    return c + [
        {"fieldname": "charged", "label": _("Charged"), "fieldtype": "Currency", "width": 120},
        {"fieldname": "repaid", "label": _("Repaid"), "fieldtype": "Currency", "width": 120},
        {"fieldname": "balance", "label": _("Balance Owed"), "fieldtype": "Currency", "width": 130},
    ]
