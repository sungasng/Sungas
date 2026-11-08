"""Patch 0021 / 0021a -- IAS 2 supplier inbound freight capitalisation.

At Purchase Receipt submit (policy switch `inbound_freight_enabled`):
  * per-kg freight = freight amount / waybill kg (PR qty + supplier short-load)
  * Landed Cost Voucher adds freight on the RECEIVED kg to stock (Dr GIT stock):
      Prepaid Haulier / Haulier (Pay on Invoice) / Supplier Invoice
          -> Cr 6225 Freight Accrued. The haulier's or supplier's Purchase
             Invoice codes its freight line to 6225; prepayments are ordinary
             ERPNext supplier advances (Payment Entry) set off with Get Advances.
      Own Truck -> Cr Logistics Clearing; actual fleet costs come in through the
             month-end true-up (market rate = standard).
  * Supplier short-load: Dr supplier (party) / Cr the same account for freight
    on the missing kg -- recovered from the supplier.
  * Prepaid Haulier: if the hauler's unused advance (less freight on earlier
    receipts not yet invoiced) does not cover this load, Finance is alerted.
  * Transit losses (GIT -> outlet) are valued at gas + freight per kg by the
    'Outlet SE Open Transit Loss Case' server script.

Month-end (`month_end_fleet_true_up`): Draft JE that moves own-truck running
costs from the listed fleet accounts into Clearing and posts the gap against
own-truck freight absorbed to Haulage Variance. Finance reviews and submits.
"""
from __future__ import annotations

import frappe
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate, nowdate

from sungas.overrides.haulage_costing import POLICY

SOURCES = ("Prepaid Haulier", "Haulier (Pay on Invoice)", "Supplier Invoice", "Own Truck")
HAULIER_SOURCES = ("Prepaid Haulier", "Haulier (Pay on Invoice)")
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


def advance_shortfall(freight, advance_balance, uninvoiced_freight) -> float:
    """Freight on this load not covered by the hauler's remaining advance."""
    available = max(flt(advance_balance) - flt(uninvoiced_freight), 0)
    return flt(max(flt(freight) - available, 0), 2)


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
    if source in HAULIER_SOURCES and not doc.get("hauler"):
        frappe.throw("Pick the Hauler on this receipt -- the freight is owed to (or prepaid with) that hauler.")
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
    credit = credit_account(policy, source)
    received, short = _kg(doc)
    split = split_freight(doc.inbound_freight_amount, received, short)
    shortfall = _prepaid_shortfall(doc, policy) if source == "Prepaid Haulier" else 0.0
    lcv = _make_lcv(doc, credit, split["capitalised"])
    je = _make_shortload_je(doc, credit, split["supplier_recovery"])
    frappe.db.set_value("Purchase Receipt", doc.name, {
        "inbound_freight_lcv": lcv, "inbound_freight_je": je,
        "inbound_freight_capitalised": split["capitalised"],
    }, update_modified=False)
    if shortfall > 0:
        _alert_finance(doc, shortfall)


def credit_account(policy, source):
    field = "logistics_clearing_account" if source == "Own Truck" else "freight_accrued_account"
    _require(policy, field)
    return policy.get(field)


def before_cancel_inbound_freight(doc, method=None):
    for dt, field in (("Landed Cost Voucher", "inbound_freight_lcv"), ("Journal Entry", "inbound_freight_je")):
        name = doc.get(field)
        if name and frappe.db.get_value(dt, name, "docstatus") == 1:
            frappe.get_doc(dt, name).cancel()


def _make_lcv(doc, credit, amount):
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
        "expense_account": credit,
        "description": f"Inbound freight ({doc.inbound_freight_source}) -- {doc.name}",
        "amount": amount,
    })
    lcv.insert(ignore_permissions=True)
    lcv.submit()
    return lcv.name


def _hauler_advance(hauler, company):
    """Unallocated supplier advance = debit balance on the hauler's payable accounts."""
    row = frappe.db.sql(
        """select coalesce(sum(gle.debit - gle.credit), 0) from `tabGL Entry` gle
           join `tabAccount` acc on acc.name = gle.account
           where gle.party_type='Supplier' and gle.party=%s and gle.company=%s
           and gle.is_cancelled=0 and acc.account_type='Payable'""", (hauler, company))
    return flt(row[0][0]) if row else 0.0


def _uninvoiced_freight(hauler, company, accrued_account, exclude):
    """Freight accrued on this hauler's earlier receipts minus what their invoices cleared."""
    accrued = frappe.db.sql(
        """select coalesce(sum(inbound_freight_amount), 0) from `tabPurchase Receipt`
           where docstatus=1 and company=%s and hauler=%s and name!=%s
           and inbound_freight_source in ('Prepaid Haulier', 'Haulier (Pay on Invoice)')""",
        (company, hauler, exclude))
    invoiced = frappe.db.sql(
        """select coalesce(sum(gle.debit - gle.credit), 0) from `tabGL Entry` gle
           join `tabPurchase Invoice` pi on pi.name = gle.voucher_no
           where gle.voucher_type='Purchase Invoice' and gle.account=%s and gle.is_cancelled=0
           and pi.supplier=%s and pi.company=%s""", (accrued_account, hauler, company))
    return max(flt(accrued[0][0]) - flt(invoiced[0][0]), 0)


def _prepaid_shortfall(doc, policy):
    advance = _hauler_advance(doc.hauler, doc.company)
    pending = _uninvoiced_freight(doc.hauler, doc.company, policy.freight_accrued_account, doc.name)
    return advance_shortfall(doc.inbound_freight_amount, advance, pending)


def _make_shortload_je(doc, credit, amount):
    if amount <= 0:
        return None
    from erpnext.accounts.party import get_party_account

    payable = get_party_account("Supplier", doc.supplier, doc.company)
    cc = frappe.get_cached_value("Company", doc.company, "cost_center")
    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.company = doc.company
    je.posting_date = doc.posting_date
    je.user_remark = (f"[Inbound Freight] Supplier short-load freight on {doc.name} recovered from "
                      f"{doc.supplier} -- NGN {amount:,.2f}")
    je.append("accounts", _row(payable, amount, 0, cc, "Supplier", doc.supplier))
    je.append("accounts", _row(credit, 0, amount, cc))
    je.insert(ignore_permissions=True)
    je.submit()
    return je.name


def _alert_finance(doc, shortfall):
    from sungas.utils.bell import ring

    users = frappe.get_all("Has Role", filters={"role": ["in", list(FINANCE_ROLES)], "parenttype": "User"},
                           pluck="parent", distinct=True)
    subject = f"Top up haulier advance -- {doc.hauler}: NGN {shortfall:,.2f} not covered on {doc.name}"
    msg = (f"<p>The prepaid advance with <b>{doc.hauler}</b> (after freight on earlier receipts not yet "
           f"invoiced) does not cover the freight on <b>{doc.name}</b>. NGN {shortfall:,.2f} will be "
           "payable when the hauler's invoice is posted.</p>"
           "<p>Top up the advance with a Payment Entry (Pay, Party = this hauler), or pay the balance on "
           "the invoice.</p>")
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
