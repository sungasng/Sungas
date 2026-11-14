"""Patch 0041 -- paid LPG receipts that have not been filled yet.

* Every submitted LPG receipt starts "Awaiting Fill" and must be filled within FILL_DAYS (7).
* The filler confirms on /fill (scan the receipt barcode or type the number) and enters the kg
  actually dispensed. A receipt fills once; the cashier who sold it cannot confirm it; fillers
  only confirm receipts of their own plant. Sold vs filled kg beyond tolerance = fill variance.
* Day 8: "Expired" -> Plant Manager decides (extend up to 7 days, or approve refund).
  No decision ESCALATE_DAYS later -> Head of Operations, Head of Finance and Internal Control.
* Month end: value of receipts still owed is moved out of sales into "Unfilled LPG - Customer
  Deposits" (and its cost out of COGS) with a reversal on the 1st (IFRS 15).
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, escape_html, flt, get_datetime, get_first_day, get_last_day, getdate, \
    now_datetime, nowdate

from sungas.lpg_cylinders import REFILL_ITEMS, lpg_kg

FILL_DAYS = 7
MAX_EXTEND_DAYS = 7
ESCALATE_DAYS = 2
KG_TOLERANCE = 0.5
PCT_TOLERANCE = 1.0
FILLER_ROLE = "LPG Filler"
FILL_ROLES = {FILLER_ROLE, "LPG Plant Manager"}
DECIDE_ROLES = {"LPG Plant Manager", "LPG Head of Operations", "LPG Head of Finance", "System Manager"}
HEAD_ROLES = ("LPG Head of Operations", "LPG Head of Finance", "Internal Control")
FINANCE_ROLES = {"LPG Head of Finance", "Accounts Manager", "System Manager"}
AWAITING, FILLED, EXPIRED, EXTENDED, REFUND_OK, REFUNDED = (
    "Awaiting Fill", "Filled", "Expired", "Extended", "Refund Approved", "Refunded")
OPEN = (AWAITING, EXTENDED)
OWED = (AWAITING, EXTENDED, EXPIRED, REFUND_OK)
DEPOSIT_ACCOUNT = "Unfilled LPG - Customer Deposits"
HELD_ACCOUNT = "Unfilled LPG - Held for Customers"


def plant_of(inv) -> str | None:
    return frappe.db.get_value("POS Profile", inv.pos_profile, "warehouse") if inv.get("pos_profile") else None


def is_variance(sold: float, filled: float) -> bool:
    diff = abs(flt(filled) - flt(sold))
    return diff > KG_TOLERANCE and (not sold or diff / sold * 100 > PCT_TOLERANCE)


def plant_managers(wh) -> list[str]:
    row = frappe.db.get_value("Warehouse", wh, ["outlet_plant_manager", "outlet_secondary_manager"], as_dict=True) or {}
    return [u for u in (row.get("outlet_plant_manager"), row.get("outlet_secondary_manager")) if u]


def role_users(roles) -> list[str]:
    return frappe.get_all("Has Role", filters={"role": ["in", list(roles)], "parenttype": "User"},
                          pluck="parent", distinct=True)


def user_plants(user: str) -> set:
    from sungas.overrides.outlet_scope import _allowed_profiles

    whs = set(frappe.get_all("POS Profile", filters={"name": ["in", _allowed_profiles(user) or [""]]}, pluck="warehouse"))
    whs |= set(frappe.get_all("User Permission", filters={"user": user, "allow": "Warehouse"}, pluck="for_value"))
    whs |= set(frappe.get_all("Warehouse", or_filters={"outlet_plant_manager": user, "outlet_secondary_manager": user},
                              pluck="name"))
    return {w for w in whs if w}


def _alert(users, subject, body, inv_name):
    from sungas.utils.bell import ring

    ring(users, subject, body, "POS Invoice", inv_name)


def _log(name, text):
    frappe.get_doc({"doctype": "Comment", "comment_type": "Info", "reference_doctype": "POS Invoice",
                    "reference_name": name, "content": text}).insert(ignore_permissions=True)


# -- POS Invoice hooks --------------------------------------------------------

def on_submit(doc, method=None):
    if doc.get("is_return"):
        orig = doc.get("return_against")
        if orig and frappe.db.get_value("POS Invoice", orig, "sungas_fill_status") in OWED:
            frappe.db.set_value("POS Invoice", orig, "sungas_fill_status", REFUNDED, update_modified=False)
            _log(orig, _("Refunded on {0} - gas will not be filled.").format(doc.name))
        return
    if lpg_kg(doc) > 0:
        doc.db_set({"sungas_fill_status": AWAITING, "sungas_fill_due": add_days(doc.posting_date, FILL_DAYS)},
                   update_modified=False)


# -- Filler screen --------------------------------------------------------------

def _receipt_no(code: str) -> str:
    return (code or "").split("|")[0].strip().strip("*").strip()


def _check_filler(inv, user) -> str | None:
    """Reason the user may not fill this receipt, or None."""
    if user == "Administrator":
        return None
    if not FILL_ROLES & set(frappe.get_roles(user)):
        return _("Only fillers and plant managers can confirm fills.")
    if inv.owner == user:
        return _("You sold this receipt - another person must confirm the fill.")
    wh = plant_of(inv)
    if wh not in user_plants(user):
        return _("This receipt belongs to {0}. Fill it at that plant.").format(wh or _("another plant"))
    return None


def _status_problem(inv) -> str | None:
    st = inv.sungas_fill_status
    if st == FILLED:
        return _("Already filled on {0} by {1}. Do not fill again.").format(
            frappe.utils.format_datetime(inv.sungas_filled_at, "dd-MM-yyyy HH:mm"), inv.sungas_filled_by)
    if st in (REFUND_OK, REFUNDED):
        return _("This receipt was refunded / approved for refund. Do not fill.")
    if st == EXPIRED or (st in OPEN and inv.sungas_fill_due and getdate(inv.sungas_fill_due) < getdate(nowdate())):
        return _("This receipt expired on {0}. Send the customer to the Plant Manager.").format(
            frappe.utils.formatdate(inv.sungas_fill_due))
    if st not in OPEN:
        return _("This receipt has no gas to fill.")
    return None


def _get_receipt(code):
    name = _receipt_no(code)
    if not name or not frappe.db.exists("POS Invoice", name):
        frappe.throw(_("Receipt {0} not found. Check the number on the receipt.").format(escape_html(name)))
    inv = frappe.get_doc("POS Invoice", name)
    if inv.docstatus != 1 or inv.is_return:
        frappe.throw(_("{0} is not a paid receipt.").format(name))
    return inv


@frappe.whitelist()
def lookup(code: str) -> dict:
    from sungas.lpg_cylinders import receipt_lines

    inv = _get_receipt(code)
    blocked = _check_filler(inv, frappe.session.user)
    if blocked:
        frappe.throw(blocked, title=_("Not allowed"))
    return {"name": inv.name, "customer": inv.customer_name or inv.customer, "plant": plant_of(inv),
            "posted": f"{frappe.utils.formatdate(inv.posting_date)} {str(inv.posting_time or '')[:5]}",
            "kg": lpg_kg(inv), "fills": [ln["fill"] for ln in receipt_lines(inv) if ln["fill"]],
            "status": inv.sungas_fill_status, "due": frappe.utils.formatdate(inv.sungas_fill_due),
            "problem": _status_problem(inv)}


@frappe.whitelist(methods=["POST"])
def confirm(code: str, kg_filled, note: str = "") -> dict:
    inv = _get_receipt(code)
    user = frappe.session.user
    blocked = _check_filler(inv, user)
    if blocked:
        frappe.throw(blocked, title=_("Not allowed"))
    frappe.db.sql("select name from `tabPOS Invoice` where name = %s for update", inv.name)
    inv.reload()
    problem = _status_problem(inv)
    if problem:
        frappe.throw(problem, title=_("Cannot fill"))
    sold, filled = lpg_kg(inv), flt(kg_filled, 2)
    if filled <= 0:
        frappe.throw(_("Enter the kg shown on the dispenser."))
    var = flt(filled - sold, 2)
    flagged = is_variance(sold, filled)
    if flagged and not (note or "").strip():
        frappe.throw(_("Filled {0} kg but the receipt is for {1} kg. Type the reason.").format(filled, sold))
    inv.db_set({"sungas_fill_status": FILLED, "sungas_filled_kg": filled, "sungas_fill_variance_kg": var,
                "sungas_filled_by": user, "sungas_filled_at": now_datetime(), "sungas_fill_note": note or None},
               update_modified=False)
    _log(inv.name, _("Filled {0} kg (receipt {1} kg, variance {2:+g} kg) by {3}. {4}").format(
        filled, sold, var, user, escape_html(note or "")))
    if flagged:
        wh = plant_of(inv)
        _alert(plant_managers(wh) + role_users(("Internal Control", "LPG Head of Operations")),
               _("Fill variance {0:+g} kg on {1} at {2}").format(var, inv.name, (wh or "").replace(" - SCL", "")),
               _("<p>Receipt <b>{0}</b>: sold {1} kg, filled {2} kg (variance {3:+g} kg) by {4}.</p><p>Reason: {5}</p>")
               .format(inv.name, sold, filled, var, user, escape_html(note or "")), inv.name)
    frappe.db.commit()
    return {"ok": True, "variance": var, "flagged": flagged,
            "message": _("Filled {0} kg on {1}.").format(filled, inv.name)}


# -- Plant Manager decision -----------------------------------------------------

@frappe.whitelist(methods=["POST"])
def decide(invoice: str, action: str, note: str, days=FILL_DAYS) -> dict:
    inv = frappe.get_doc("POS Invoice", invoice)
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    if not DECIDE_ROLES & roles:
        frappe.throw(_("Only the Plant Manager or a Head can decide on unfilled receipts."))
    if not roles & {"LPG Head of Operations", "LPG Head of Finance", "System Manager"} \
            and plant_of(inv) not in user_plants(user):
        frappe.throw(_("{0} is not your plant.").format(plant_of(inv)))
    if inv.sungas_fill_status not in (AWAITING, EXTENDED, EXPIRED):
        frappe.throw(_("Receipt is '{0}' - nothing to decide.").format(inv.sungas_fill_status or "-"))
    if not (note or "").strip():
        frappe.throw(_("Type the reason for your decision."))
    if action == "Extend":
        days = cint(days)
        if not 1 <= days <= MAX_EXTEND_DAYS:
            frappe.throw(_("Extend by 1 to {0} days.").format(MAX_EXTEND_DAYS))
        due = add_days(nowdate(), days)
        inv.db_set({"sungas_fill_status": EXTENDED, "sungas_fill_due": due, "sungas_fill_escalation": 0},
                   update_modified=False)
        text = _("Fill time extended to {0} by {1}: {2}").format(frappe.utils.formatdate(due), user, escape_html(note))
    elif action == "Refund":
        inv.db_set("sungas_fill_status", REFUND_OK, update_modified=False)
        text = _("Refund approved by {0}: {1}. Cashier to process the return at the till.").format(user, escape_html(note))
    else:
        frappe.throw(_("Action must be Extend or Refund."))
    _log(inv.name, text)
    frappe.db.commit()
    return {"ok": True, "status": inv.sungas_fill_status, "message": text}


# -- Daily expiry + escalation ------------------------------------------------------

def sweep() -> dict:
    today = getdate(nowdate())
    out = {"expired": 0, "escalated": 0}
    for r in frappe.get_all("POS Invoice", filters={"docstatus": 1, "sungas_fill_status": ["in", OPEN],
                                                     "sungas_fill_due": ["<", today]},
                            fields=["name", "pos_profile", "customer_name", "sungas_fill_due", "grand_total"]):
        frappe.db.set_value("POS Invoice", r.name, {"sungas_fill_status": EXPIRED, "sungas_fill_escalation": 1},
                            update_modified=False)
        wh = plant_of(r)
        _alert(plant_managers(wh), _("Unfilled receipt expired - {0} ({1})").format(r.name, r.customer_name),
               _("<p>{0} paid on receipt <b>{1}</b> but the gas was not filled by {2}. "
                 "Open the receipt and choose <b>Extend fill time</b> or <b>Approve refund</b>.</p>")
               .format(escape_html(r.customer_name or ""), r.name, frappe.utils.formatdate(r.sungas_fill_due)), r.name)
        out["expired"] += 1
    late = add_days(today, -ESCALATE_DAYS)
    for r in frappe.get_all("POS Invoice", filters={"docstatus": 1, "sungas_fill_status": EXPIRED,
                                                     "sungas_fill_escalation": ["<", 2], "sungas_fill_due": ["<", late]},
                            fields=["name", "pos_profile", "customer_name", "grand_total"]):
        frappe.db.set_value("POS Invoice", r.name, "sungas_fill_escalation", 2, update_modified=False)
        _alert(role_users(HEAD_ROLES) + plant_managers(plant_of(r)),
               _("ESCALATED: no decision on unfilled receipt {0}").format(r.name),
               _("<p>Receipt <b>{0}</b> ({1}, {2:,.0f}) expired over {3} days ago and the Plant Manager has not "
                 "extended or refunded it.</p>").format(r.name, escape_html(r.customer_name or ""), flt(r.grand_total),
                                                         ESCALATE_DAYS), r.name)
        out["escalated"] += 1
    frappe.db.commit()
    return out


# -- Briefing + reports -----------------------------------------------------------

def plant_rows(day, whs=None) -> list[dict]:
    """Per plant: receipts still owed (count/kg/value, oldest, expired) and day's fills vs sold kg."""
    prof_wh = dict(frappe.get_all("POS Profile", fields=["name", "warehouse"], as_list=True))
    rows = {}

    def row(wh):
        return rows.setdefault(wh, {"plant": wh, "owed": 0, "owed_kg": 0.0, "owed_value": 0.0, "oldest": None,
                                    "expired": 0, "expired_value": 0.0, "filled": 0, "sold_kg": 0.0,
                                    "filled_kg": 0.0, "variance_kg": 0.0, "flagged": 0})
    for r in frappe.db.sql("""select inv.name, inv.pos_profile, inv.posting_date, inv.sungas_fill_status as st,
                inv.grand_total, sum(it.stock_qty) as kg
            from `tabPOS Invoice` inv join `tabPOS Invoice Item` it on it.parent = inv.name and it.item_code in %(items)s
            where inv.docstatus = 1 and inv.sungas_fill_status in %(owed)s group by inv.name""",
                           {"items": REFILL_ITEMS, "owed": OWED}, as_dict=True):
        wh = prof_wh.get(r.pos_profile)
        if whs is not None and wh not in whs:
            continue
        x = row(wh)
        x["owed"] += 1
        x["owed_kg"] += flt(r.kg)
        x["owed_value"] += flt(r.grand_total)
        x["oldest"] = min(x["oldest"] or r.posting_date, r.posting_date)
        if r.st in (EXPIRED, REFUND_OK):
            x["expired"] += 1
            x["expired_value"] += flt(r.grand_total)
    for r in frappe.get_all("POS Invoice", filters={"docstatus": 1, "sungas_fill_status": FILLED,
                                                     "sungas_filled_at": ["between", [f"{day} 00:00:00", f"{day} 23:59:59"]]},
                            fields=["pos_profile", "sungas_filled_kg", "sungas_fill_variance_kg"]):
        wh = prof_wh.get(r.pos_profile)
        if whs is not None and wh not in whs:
            continue
        x = row(wh)
        x["filled"] += 1
        x["filled_kg"] += flt(r.sungas_filled_kg)
        x["sold_kg"] += flt(r.sungas_filled_kg) - flt(r.sungas_fill_variance_kg)
        x["variance_kg"] += flt(r.sungas_fill_variance_kg)
        x["flagged"] += 1 if is_variance(flt(r.sungas_filled_kg) - flt(r.sungas_fill_variance_kg), r.sungas_filled_kg) else 0
    return sorted(rows.values(), key=lambda x: (-x["owed_value"], str(x["plant"])))


def briefing_section(user, roles, day) -> str:
    from sungas.scheduled_jobs.briefing_figures import outlets_for

    whs = outlets_for(user, roles)
    if whs is not None and not whs:
        return ""
    rows = [r for r in plant_rows(day, set(whs) if whs is not None else None)
            if r["owed"] or r["filled"]]
    if not rows:
        return ""
    td = '<td style="text-align:right;padding:2px 8px{1}">{0}</td>'
    red = ";color:#c62828;font-weight:bold"
    body = "".join(
        f'<tr><td style="padding:2px 8px">{escape_html((r["plant"] or "-").replace(" - SCL", ""))}</td>'
        + td.format(r["owed"], "") + td.format(f'{r["owed_kg"]:,.1f}', "") + td.format(f'{r["owed_value"]:,.0f}', "")
        + td.format(frappe.utils.formatdate(r["oldest"]) if r["oldest"] else "-", "")
        + td.format(r["expired"], red if r["expired"] else "")
        + td.format(r["filled"], "") + td.format(f'{r["sold_kg"]:,.1f}', "") + td.format(f'{r["filled_kg"]:,.1f}', "")
        + td.format(f'{r["variance_kg"]:+,.1f}', red if r["flagged"] else "") + td.format(r["flagged"], red if r["flagged"] else "")
        + "</tr>" for r in rows)
    head = ('<tr><th rowspan="2" style="text-align:left;padding:2px 8px">Plant</th><th colspan="5">Paid, not yet filled (now)</th>'
            '<th colspan="5">Fills yesterday</th></tr><tr><th>Receipts</th><th>kg</th><th>NGN</th><th>Oldest</th>'
            '<th>Expired - decide</th><th>Receipts</th><th>kg sold</th><th>kg filled</th><th>Variance kg</th><th>Flagged</th></tr>')
    return (f"<h4>Paid receipts not yet filled</h4>"
            f'<table border="1" cellspacing="0" style="border-collapse:collapse;font-size:13px">{head}{body}</table>'
            f'<p style="font-size:12px">Receipts must be filled within {FILL_DAYS} days. Expired receipts wait for the '
            f'Plant Manager to extend or refund; after {ESCALATE_DAYS} more days they go to the Heads and Internal Control. '
            f'Flagged = filled kg differs from the receipt by more than {KG_TOLERANCE:g} kg.</p>')


# -- Month-end correction (IFRS 15) -------------------------------------------------

def _owed_at(month_end) -> list[dict]:
    """LPG lines of receipts posted by month end and neither filled nor refunded by then."""
    end = f"{month_end} 23:59:59"
    rate = "it.incoming_rate" if frappe.db.has_column("POS Invoice Item", "incoming_rate") else "0"
    return frappe.db.sql(f"""select inv.name, inv.company, it.item_code, it.warehouse, it.income_account,
                it.expense_account, it.cost_center, it.base_net_amount, it.stock_qty, {rate} as incoming_rate
            from `tabPOS Invoice` inv join `tabPOS Invoice Item` it on it.parent = inv.name
            where inv.docstatus = 1 and inv.is_return = 0 and it.item_code in %(items)s
              and inv.posting_date <= %(me)s and ifnull(inv.sungas_fill_status, '') != ''
              and not (inv.sungas_filled_at is not null and inv.sungas_filled_at <= %(end)s)
              and not exists (select 1 from `tabPOS Invoice` r where r.return_against = inv.name
                              and r.docstatus = 1 and r.posting_date <= %(me)s)""",
                         {"items": REFILL_ITEMS, "me": month_end, "end": end}, as_dict=True)


def _ensure_account(company, name, root_type, parent_names):
    abbr = frappe.get_cached_value("Company", company, "abbr")
    full = f"{name} - {abbr}"
    if frappe.db.exists("Account", full):
        return full
    parent = None
    for p in parent_names:
        parent = frappe.db.get_value("Account", {"company": company, "account_name": p, "is_group": 1})
        if parent:
            break
    parent = parent or frappe.db.get_value("Account", {"company": company, "root_type": root_type, "is_group": 1,
                                                      "parent_account": ["is", "set"]})
    return frappe.get_doc({"doctype": "Account", "account_name": name, "company": company, "parent_account": parent,
                           "root_type": root_type, "account_type": "", "is_group": 0}).insert(ignore_permissions=True).name


def _rate(line) -> float:
    if flt(line.incoming_rate):
        return flt(line.incoming_rate)
    return flt(frappe.db.get_value("Bin", {"item_code": line.item_code, "warehouse": line.warehouse}, "valuation_rate"))


def _je(company, date, lines, remark):
    je = frappe.get_doc({"doctype": "Journal Entry", "voucher_type": "Journal Entry", "company": company,
                         "posting_date": date, "user_remark": remark, "accounts": lines})
    je.flags.ignore_permissions = True
    je.insert()
    je.submit()
    return je.name


def reclass_entries(month_end) -> dict:
    """{company: (journal lines, receipts, value, cost)} -- Dr sales / Cr deposits; Dr held / Cr COGS."""
    out = {}
    for ln in _owed_at(month_end):
        c = out.setdefault(ln.company, {"inc": {}, "cogs": {}, "receipts": set(), "value": 0.0, "cost": 0.0})
        inc = ln.income_account or frappe.get_cached_value("Company", ln.company, "default_income_account")
        exp = ln.expense_account or frappe.get_cached_value("Company", ln.company, "default_expense_account")
        cc = ln.cost_center or frappe.get_cached_value("Company", ln.company, "cost_center")
        cost = flt(flt(ln.stock_qty) * _rate(ln), 2)
        c["inc"][(inc, cc)] = c["inc"].get((inc, cc), 0.0) + flt(ln.base_net_amount)
        c["cogs"][(exp, cc)] = c["cogs"].get((exp, cc), 0.0) + cost
        c["receipts"].add(ln.name)
        c["value"] += flt(ln.base_net_amount)
        c["cost"] += cost
    return out


def month_end_reclass(month_end=None, dry_run=False) -> dict:
    me = getdate(month_end) if month_end else get_last_day(add_days(get_first_day(nowdate()), -1))
    result = {}
    for company, c in reclass_entries(me).items():
        key = f"sungas_0041_unfilled_{frappe.scrub(company)}_{me}"
        if dry_run:
            result[company] = {"receipts": sorted(c["receipts"]), "value": c["value"], "cost": c["cost"],
                               "posted": frappe.db.get_default(key)}
            continue
        if frappe.db.get_default(key) or not flt(c["value"], 2):
            continue
        try:
            dep = _ensure_account(company, DEPOSIT_ACCOUNT, "Liability", ("Current Liabilities", "Duties and Taxes"))
            held = _ensure_account(company, HELD_ACCOUNT, "Asset", ("Current Assets",))
            lines = [{"account": a, "cost_center": cc, "debit_in_account_currency": flt(v, 2)}
                     for (a, cc), v in c["inc"].items() if flt(v, 2)]
            lines.append({"account": dep, "credit_in_account_currency": flt(sum(c["inc"].values()), 2)})
            if flt(c["cost"], 2):
                lines.append({"account": held, "debit_in_account_currency": flt(c["cost"], 2)})
                lines += [{"account": a, "cost_center": cc, "credit_in_account_currency": flt(v, 2)}
                          for (a, cc), v in c["cogs"].items() if flt(v, 2)]
            remark = _("Paid LPG not yet filled at {0}: {1} receipt(s), sales {2:,.2f}, cost {3:,.2f} (IFRS 15)").format(
                me, len(c["receipts"]), c["value"], c["cost"])
            rev = [{**ln, "debit_in_account_currency": flt(ln.get("credit_in_account_currency")),
                    "credit_in_account_currency": flt(ln.get("debit_in_account_currency"))} for ln in lines]
            j1 = _je(company, me, lines, remark)
            j2 = _je(company, add_days(me, 1), rev, _("Reversal of {0} - {1}").format(j1, remark))
            frappe.db.set_default(key, f"{j1},{j2}")
            result[company] = {"journal": j1, "reversal": j2, "receipts": len(c["receipts"]),
                               "value": c["value"], "cost": c["cost"]}
            from sungas.utils.bell import ring

            ring(role_users(("LPG Head of Finance", "Accounts Manager", "Internal Control")),
                 _("Month end {0}: {1:,.0f} of paid LPG not yet filled moved to customer deposits").format(me, c["value"]),
                 f"<p>{escape_html(remark)}</p><p>Journal {j1}, reversed by {j2}.</p>", "Journal Entry", j1)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), "sungas.lpg_fill.month_end_reclass")
            result[company] = {"error": True}
    return result


@frappe.whitelist(methods=["POST"])
def run_month_end_reclass(month_end: str, dry_run=1) -> dict:
    """Finance: preview (dry_run=1, default) or post the correction for a month end."""
    if not FINANCE_ROLES & set(frappe.get_roles()):
        frappe.throw(_("Only Finance can run the month-end unfilled LPG correction."))
    return month_end_reclass(month_end, dry_run=bool(cint(dry_run)))


@frappe.whitelist(methods=["POST"])
def run_sweep() -> dict:
    frappe.only_for("System Manager")
    return sweep()


# -- Install (after_migrate) ----------------------------------------------------

def install():
    try:
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

        if not frappe.db.exists("Role", FILLER_ROLE):
            frappe.get_doc({"doctype": "Role", "role_name": FILLER_ROLE, "desk_access": 1}).insert(ignore_permissions=True)
        common = {"read_only": 1, "no_copy": 1, "allow_on_submit": 1}
        fields = [
            {"fieldname": "sungas_fill_section", "fieldtype": "Section Break", "label": "Gas Fill",
             "insert_after": "sungas_print_count", "collapsible": 1},
            {"fieldname": "sungas_fill_status", "fieldtype": "Select", "label": "Fill Status", "in_standard_filter": 1,
             "options": "\n" + "\n".join((AWAITING, FILLED, EXPIRED, EXTENDED, REFUND_OK, REFUNDED)),
             "insert_after": "sungas_fill_section", "search_index": 1, **common},
            {"fieldname": "sungas_fill_due", "fieldtype": "Date", "label": "Fill By", "insert_after": "sungas_fill_status", **common},
            {"fieldname": "sungas_fill_escalation", "fieldtype": "Int", "label": "Fill Escalation Level", "hidden": 1,
             "insert_after": "sungas_fill_due", **common},
            {"fieldname": "sungas_fill_col", "fieldtype": "Column Break", "insert_after": "sungas_fill_escalation"},
            {"fieldname": "sungas_filled_kg", "fieldtype": "Float", "label": "kg Filled", "insert_after": "sungas_fill_col", **common},
            {"fieldname": "sungas_fill_variance_kg", "fieldtype": "Float", "label": "Fill Variance (kg)",
             "insert_after": "sungas_filled_kg", **common},
            {"fieldname": "sungas_filled_by", "fieldtype": "Link", "options": "User", "label": "Filled By",
             "insert_after": "sungas_fill_variance_kg", **common},
            {"fieldname": "sungas_filled_at", "fieldtype": "Datetime", "label": "Filled At",
             "insert_after": "sungas_filled_by", **common},
            {"fieldname": "sungas_fill_note", "fieldtype": "Small Text", "label": "Fill Note",
             "insert_after": "sungas_filled_at", **common},
        ]
        create_custom_fields({"POS Invoice": fields}, update=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.lpg_fill.install")
