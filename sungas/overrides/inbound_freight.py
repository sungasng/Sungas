"""Patch 0021 -- IAS 2 supplier inbound freight capitalisation.

At Purchase Receipt submit (policy switch `inbound_freight_enabled`):
  * per-kg freight = freight amount / waybill kg (PR qty + supplier short-load)
  * Landed Cost Voucher: Dr stock (GIT) / Cr Logistics Clearing for the
    received kg only
  * Drawdown JE by freight source:
      Prepaid Haulier  -> Dr Clearing / Cr Haulier Advance (party = hauler);
                          anything above the advance balance -> Cr Payable
                          (owed to hauler) + Finance alert
      Supplier Invoice -> Dr Clearing / Cr Freight Accrued (supplier PI clears it)
      Own Truck        -> no credit here; actual fleet costs reach Clearing via
                          the month-end true-up (market rate = standard)
    plus, when the supplier short-loaded: Dr Payable (party = supplier) /
    Cr Clearing for freight on the missing kg (recovered from supplier).
  * Transit losses (GIT -> outlet) are valued at gas + freight per kg by the
    'Outlet SE Open Transit Loss Case' server script, so Hauler / Driver
    Liable recovers freight too.

Month-end (`month_end_fleet_true_up`): Draft JE that moves own-truck running
costs from the listed fleet accounts into Clearing and posts the gap against
own-truck freight absorbed to Haulage Variance. Finance reviews and submits.
"""
from __future__ import annotations

import frappe
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate, nowdate

from sungas.overrides.haulage_costing import POLICY

SOURCES = ("Prepaid Haulier", "Supplier Invoice", "Own Truck")
FINANCE_ROLES = ("LPG Head of Finance", "Accounts Manager")
TRUE_UP_TAG = "[Fleet True-up"


# --------------------------------------------------------------------------- #
# Pure maths
# --------------------------------------------------------------------------- #

def split_freight(freight, received_kg, shortload_kg) -> dict:
    freight = flt(freight, 2)
    waybill = flt(received_kg) + flt(shortload_kg)
    if freight <= 0 or waybill <= 0:
        return {"per_kg": 0.0, "capitalised": 0.0, "supplier_recovery": 0.0}
    per_kg = freight / waybill
    recovery = flt(per_kg * flt(shortload_kg), 2)
    return {"per_kg": flt(per_kg, 6), "capitalised": flt(freight - recovery, 2), "supplier_recovery": recovery}


def split_prepaid(freight, advance_balance) -> dict:
    freight = flt(freight, 2)
    from_advance = flt(min(freight, max(flt(advance_balance), 0)), 2)
    return {"from_advance": from_advance, "owed": flt(freight - from_advance, 2)}


def true_up_lines(fleet_balances, absorbed, clearing, variance_account, variance_cc) -> list:
    """fleet_balances: [(account, cost_center, net_debit)]. Returns JE account rows."""
    lines, moved = [], 0.0
    for account, cc, amount in fleet_balances:
        amount = flt(amount, 2)
        if not amount:
            continue
        moved += amount
        cc = cc or variance_cc
        if amount > 0:
            lines.append(_row(account, 0, amount, cc))
        else:
            lines.append(_row(account, -amount, 0, cc))
    moved = flt(moved, 2)
    if moved:
        lines.append(_row(clearing, moved, 0, variance_cc) if moved > 0 else _row(clearing, 0, -moved, variance_cc))
    gap = flt(moved - flt(absorbed), 2)
    if gap > 0:
        lines += [_row(variance_account, gap, 0, variance_cc), _row(clearing, 0, gap, variance_cc)]
    elif gap < 0:
        lines += [_row(clearing, -gap, 0, variance_cc), _row(variance_account, 0, -gap, variance_cc)]
    return lines


def _row(account, dr, cr, cc=None, party_type=None, party=None):
    row = {"account": account, "debit_in_account_currency": flt(dr, 2),
           "credit_in_account_currency": flt(cr, 2), "cost_center": cc}
    if party:
        row.update({"party_type": party_type, "party": party})
    return row


# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #

def get_inbound_policy():
    try:
        policy = frappe.get_cached_doc(POLICY, POLICY)
    except Exception:
        return None
    return policy if policy.get("inbound_freight_enabled") else None


def _require(policy, *fields):
    missing = [policy.meta.get_label(f) for f in fields if not policy.get(f)]
    if missing:
        frappe.throw(f"Set {', '.join(missing)} in {POLICY} before posting inbound freight.")


def _kg(doc):
    received = sum(flt(i.get("qty")) for i in doc.get("items") or [])
    short = sum(flt(i.get("supplier_shortload_qty")) for i in doc.get("items") or [])
    return received, short


# --------------------------------------------------------------------------- #
# Purchase Receipt hooks
# --------------------------------------------------------------------------- #

def validate_inbound_freight(doc, method=None):
    source = doc.get("inbound_freight_source")
    if not source or source == "None":
        doc.inbound_freight_per_kg = 0
        doc.freight_on_shortload = 0
        return
    policy = get_inbound_policy()
    if not policy:
        return
    received, short = _kg(doc)
    if source == "Own Truck" and not flt(doc.get("inbound_freight_amount")):
        doc.inbound_freight_amount = flt(flt(policy.get("own_truck_rate_per_kg")) * (received + short), 2)
    if flt(doc.get("inbound_freight_amount")) <= 0:
        frappe.throw("Enter the Inbound Freight Amount (NGN) for this delivery, or set Freight Source to None.")
    if source == "Prepaid Haulier" and not doc.get("hauler"):
        frappe.throw("Pick the Hauler on this receipt -- prepaid freight is drawn from that hauler's advance.")
    split = split_freight(doc.inbound_freight_amount, received, short)
    doc.inbound_freight_per_kg = split["per_kg"]
    doc.freight_on_shortload = split["supplier_recovery"]


def on_submit_inbound_freight(doc, method=None):
    source = doc.get("inbound_freight_source")
    if source not in SOURCES or flt(doc.get("inbound_freight_amount")) <= 0:
        return
    policy = get_inbound_policy()
    if not policy:
        return
    _require(policy, "logistics_clearing_account")
    received, short = _kg(doc)
    split = split_freight(doc.inbound_freight_amount, received, short)
    lcv = _make_lcv(doc, policy, split["capitalised"])
    je, owed = _make_drawdown_je(doc, policy, source, split)
    frappe.db.set_value("Purchase Receipt", doc.name, {
        "inbound_freight_lcv": lcv, "inbound_freight_je": je,
        "inbound_freight_capitalised": split["capitalised"],
    }, update_modified=False)
    if owed > 0:
        _alert_finance(doc, owed)


def before_cancel_inbound_freight(doc, method=None):
    for dt, field in (("Landed Cost Voucher", "inbound_freight_lcv"), ("Journal Entry", "inbound_freight_je")):
        name = doc.get(field)
        if name and frappe.db.get_value(dt, name, "docstatus") == 1:
            frappe.get_doc(dt, name).cancel()


def _make_lcv(doc, policy, amount):
    if amount <= 0:
        return None
    lcv = frappe.new_doc("Landed Cost Voucher")
    lcv.company = doc.company
    lcv.posting_date = doc.posting_date
    lcv.distribute_charges_based_on = "Qty"
    lcv.append("purchase_receipts", {
        "receipt_document_type": "Purchase Receipt", "receipt_document": doc.name,
        "supplier": doc.supplier, "posting_date": doc.posting_date, "grand_total": doc.grand_total,
    })
    lcv.get_items_from_purchase_receipts()
    lcv.append("taxes", {
        "expense_account": policy.logistics_clearing_account,
        "description": f"Inbound freight ({doc.inbound_freight_source}) -- {doc.name}",
        "amount": amount,
    })
    lcv.insert(ignore_permissions=True)
    lcv.submit()
    return lcv.name


def _party_balance(account, party_type, party, company):
    row = frappe.db.sql(
        """select coalesce(sum(debit - credit), 0) from `tabGL Entry`
           where account=%s and party_type=%s and party=%s and company=%s and is_cancelled=0""",
        (account, party_type, party, company))
    return flt(row[0][0]) if row else 0.0


def _is_party_account(account):
    return frappe.get_cached_value("Account", account, "account_type") in ("Payable", "Receivable")


def _make_drawdown_je(doc, policy, source, split):
    clearing = policy.logistics_clearing_account
    cc = frappe.get_cached_value("Company", doc.company, "cost_center")
    payable = frappe.get_cached_value("Company", doc.company, "default_payable_account")
    freight = flt(doc.inbound_freight_amount, 2)
    lines, owed = [], 0.0
    if source == "Prepaid Haulier":
        _require(policy, "haulier_advance_account")
        adv = policy.haulier_advance_account
        party = _is_party_account(adv)
        balance = _party_balance(adv, "Supplier", doc.hauler, doc.company) if party else freight
        p = split_prepaid(freight, balance)
        owed = p["owed"]
        lines.append(_row(clearing, freight, 0, cc))
        if p["from_advance"]:
            lines.append(_row(adv, 0, p["from_advance"], cc, *(("Supplier", doc.hauler) if party else (None, None))))
        if owed:
            lines.append(_row(payable, 0, owed, cc, "Supplier", doc.hauler))
    elif source == "Supplier Invoice":
        _require(policy, "freight_accrued_account")
        lines += [_row(clearing, freight, 0, cc), _row(policy.freight_accrued_account, 0, freight, cc)]
    if split["supplier_recovery"] > 0:
        lines += [_row(payable, split["supplier_recovery"], 0, cc, "Supplier", doc.supplier),
                  _row(clearing, 0, split["supplier_recovery"], cc)]
    if not lines:
        return None, owed
    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.company = doc.company
    je.posting_date = doc.posting_date
    je.user_remark = (f"[Inbound Freight] {source} on {doc.name} -- NGN {freight:,.2f}"
                      + (f"; supplier short-load freight recovered NGN {split['supplier_recovery']:,.2f}"
                         if split["supplier_recovery"] else ""))
    for row in lines:
        je.append("accounts", row)
    je.insert(ignore_permissions=True)
    je.submit()
    return je.name, owed


def _alert_finance(doc, owed):
    from sungas.utils.bell import ring

    users = frappe.get_all("Has Role", filters={"role": ["in", list(FINANCE_ROLES)], "parenttype": "User"},
                           pluck="parent", distinct=True)
    subject = f"Top up haulier advance -- {doc.hauler}: NGN {owed:,.2f} owed on {doc.name}"
    msg = (f"<p>The prepaid advance with <b>{doc.hauler}</b> did not cover the freight on "
           f"<b>{doc.name}</b>. NGN {owed:,.2f} was booked as owed to the hauler.</p>"
           "<p>Pay or top up the advance with a Payment Entry against this hauler.</p>")
    ring(users, subject, msg, "Purchase Receipt", doc.name)
    try:
        frappe.sendmail(recipients=users, subject=f"[SCL] {subject}", message=msg,
                        reference_doctype="Purchase Receipt", reference_name=doc.name, now=False)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.inbound_freight alert")


# --------------------------------------------------------------------------- #
# Month-end own-truck true-up
# --------------------------------------------------------------------------- #

def _period(month: str | None):
    start = get_first_day(getdate(month) if month else add_months(nowdate(), -1))
    return start, get_last_day(start)


def _fleet_balances(policy, company, start, end):
    out = []
    for row in policy.get("fleet_cost_accounts") or []:
        cond, args = "", [row.account, company, start, end]
        if row.get("cost_center"):
            cond, args = " and cost_center=%s", args + [row.cost_center]
        val = frappe.db.sql(
            f"""select coalesce(sum(debit - credit), 0) from `tabGL Entry`
                where account=%s and company=%s and posting_date between %s and %s
                and is_cancelled=0{cond}
                and not (voucher_type='Journal Entry' and voucher_no in (
                    select name from `tabJournal Entry` where user_remark like %s and docstatus=1))""",
            tuple(args + [f"{TRUE_UP_TAG}%"]))
        out.append((row.account, row.get("cost_center") or None, flt(val[0][0]) if val else 0.0))
    return out


def _own_truck_absorbed(company, start, end):
    val = frappe.db.sql(
        """select coalesce(sum(inbound_freight_capitalised), 0) from `tabPurchase Receipt`
           where company=%s and docstatus=1 and inbound_freight_source='Own Truck'
           and posting_date between %s and %s""", (company, start, end))
    return flt(val[0][0]) if val else 0.0


@frappe.whitelist()
def preview_fleet_true_up(month: str | None = None, company: str | None = None) -> dict:
    frappe.only_for(list(FINANCE_ROLES) + ["System Manager"])
    return _build_true_up(month, company)


def _build_true_up(month, company):
    policy = frappe.get_cached_doc(POLICY, POLICY)
    company = company or frappe.defaults.get_global_default("company")
    start, end = _period(month)
    balances = _fleet_balances(policy, company, start, end)
    absorbed = _own_truck_absorbed(company, start, end)
    cc = policy.get("hq_operations_cost_center") or frappe.get_cached_value("Company", company, "cost_center")
    lines = true_up_lines(balances, absorbed, policy.logistics_clearing_account,
                          policy.haulage_variance_account, cc)
    moved = flt(sum(b[2] for b in balances), 2)
    return {"company": company, "from": str(start), "to": str(end), "fleet_costs_moved": moved,
            "own_truck_freight_absorbed": absorbed, "haulage_variance": flt(moved - absorbed, 2),
            "lines": lines}


@frappe.whitelist()
def create_fleet_true_up(month: str | None = None, company: str | None = None) -> dict:
    frappe.only_for(list(FINANCE_ROLES) + ["System Manager"])
    return _create_true_up(month, company)


def _create_true_up(month, company):
    data = _build_true_up(month, company)
    tag = f"{TRUE_UP_TAG} {data['from'][:7]}]"
    existing = frappe.db.get_value("Journal Entry", {"user_remark": ["like", f"{tag}%"], "docstatus": ["<", 2],
                                                     "company": data["company"]}, "name")
    if existing:
        return {**data, "journal_entry": existing, "already": True}
    if not data["lines"]:
        return {**data, "journal_entry": None}
    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.company = data["company"]
    je.posting_date = data["to"]
    je.user_remark = (f"{tag} Own-truck running costs NGN {data['fleet_costs_moved']:,.2f} moved to Logistics "
                      f"Clearing; own-truck freight absorbed NGN {data['own_truck_freight_absorbed']:,.2f}; "
                      f"Haulage Variance NGN {data['haulage_variance']:,.2f}.")
    for row in data["lines"]:
        je.append("accounts", row)
    je.insert(ignore_permissions=True)
    return {**data, "journal_entry": je.name}


def month_end_fleet_true_up():
    """Scheduler (monthly): draft last month's true-up and ask Finance to review it."""
    try:
        policy = get_inbound_policy()
        if not policy or not policy.get("fleet_cost_accounts"):
            return
        res = _create_true_up(None, None)
        if not res.get("journal_entry") or res.get("already"):
            return
        from sungas.utils.bell import ring

        users = frappe.get_all("Has Role", filters={"role": ["in", list(FINANCE_ROLES)], "parenttype": "User"},
                               pluck="parent", distinct=True)
        subject = f"Review own-truck freight true-up {res['from'][:7]} -- {res['journal_entry']}"
        msg = (f"<p>Draft Journal Entry <b>{res['journal_entry']}</b>: fleet costs moved NGN "
               f"{res['fleet_costs_moved']:,.2f}, own-truck freight absorbed NGN "
               f"{res['own_truck_freight_absorbed']:,.2f}, Haulage Variance NGN {res['haulage_variance']:,.2f}. "
               "Review and submit.</p>")
        ring(users, subject, msg, "Journal Entry", res["journal_entry"])
        frappe.sendmail(recipients=users, subject=f"[SCL] {subject}", message=msg,
                        reference_doctype="Journal Entry", reference_name=res["journal_entry"], now=False)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.inbound_freight month_end")
