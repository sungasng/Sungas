"""Patch 0043 -- shift controls: blind count + one recount, cash lodgement (till -> Cash in Transit -> bank).

* Closing: the till hides expected amounts until the count is submitted; one recount is allowed (first count kept);
  a recount on a block / critical difference must name the Plant Manager who witnessed it.
* Closing submitted -> draft Cash Lodgement for the Plant Manager (bell + WhatsApp).
* Plant Manager records amount, bank, teller no. and slip photo -> submitted: Dr Cash in Transit / Cr till cash;
  a DRAFT Dr Bank / Cr Cash in Transit goes to Finance, who match it to the bank statement and submit it.
* Not lodged by the next working day -> Plant Manager; one more working day -> Heads + Internal Control.
  Draft bank posting not matched in 3 days -> Finance + Internal Control. Lodged <> counted -> remarks + alert.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, escape_html, flt, getdate, now_datetime, nowdate

LODGEMENT = "Sungas Cash Lodgement"
TRANSIT_ACCOUNT = "Cash in Transit"
FINANCE = ("Accounts Manager", "LPG Head of Finance")
HEADS = ("LPG Head of Operations", "LPG Head of Finance", "Internal Control")
DECIDE_ALL = {"Accounts Manager", "LPG Head of Finance", "LPG Head of Operations", "System Manager"}
BANK_MATCH_DAYS = 3


def _ring(users, subject, body, name, doctype=LODGEMENT):
    from sungas.utils.bell import ring

    ring(list(dict.fromkeys(u for u in users if u)), subject, body, doctype, name)


def _wa(users, template, variables, ref):
    from sungas.utils import whatsapp

    whatsapp.send([u for u in users if u], template, variables, ref=ref)


def working_days(a, b) -> int:
    """Weekdays after a, up to and including b."""
    a, b = getdate(a), getdate(b)
    n, d = 0, a
    while d < b:
        d = add_days(d, 1)
        n += 1 if getdate(d).weekday() < 5 else 0
    return n


def _is_cash(mop) -> bool:
    return frappe.get_cached_value("Mode of Payment", mop, "type") == "Cash"


def _cash_account(mop, company):
    return frappe.db.get_value("Mode of Payment Account", {"parent": mop, "company": company}, "default_account")


def _plant_manager(profile, wh):
    from sungas.lpg_fill import plant_managers

    return (plant_managers(wh) or [None])[0] or frappe.db.get_value("POS Profile", profile, "outlet_manager")


# -- Closing count --------------------------------------------------------------

def _count_log(raw):
    return frappe.parse_json(raw) if raw else []


def _shift_for_cashier(opening_shift):
    shift = frappe.get_doc("POS Opening Shift", opening_shift)
    if shift.user != frappe.session.user:
        frappe.throw(_("Only the cashier of this shift can count it."))
    return shift


@frappe.whitelist(methods=["POST"])
def record_count(opening_shift: str, counts) -> dict:
    """Patch 0047: every 'Submit count' is saved on the shift -- closing the screen can no longer wipe the first count."""
    shift = _shift_for_cashier(opening_shift)
    if shift.status != "Open":
        frappe.throw(_("This shift is already closed."))
    log = _count_log(shift.get("sungas_count_log"))
    log.append({"at": str(now_datetime()), "counts": [
        {"mode_of_payment": c.get("mode_of_payment"), "closing_amount": flt(c.get("closing_amount"))}
        for c in (frappe.parse_json(counts) or [])]})
    shift.db_set("sungas_count_log", frappe.as_json(log, indent=None), update_modified=False)
    return {"counts": len(log), "first": log[0]["counts"]}


@frappe.whitelist()
def approver_roles() -> list:
    """Patch 0048: the closing form reads the approver roles here -- approvers cannot read the Close Policy itself."""
    raw = frappe.db.get_single_value("Sungas Close Policy", "approver_roles") or ""
    return [r.strip() for r in raw.split("\n") if r.strip()]


@frappe.whitelist()
def get_counts(opening_shift: str) -> dict:
    log = _count_log(_shift_for_cashier(opening_shift).get("sungas_count_log"))
    return {"counts": len(log), "first": log[0]["counts"] if log else []}


def validate_count(doc, method=None):
    # Patch 0047: the counts saved on the shift decide whether this was a recount, not the screen.
    log = _count_log(frappe.db.get_value("POS Opening Shift", doc.pos_opening_shift, "sungas_count_log")) \
        if doc.get("pos_opening_shift") else []
    if len(log) > 1:
        doc.sungas_recounted = 1
        doc.sungas_first_count = ", ".join(
            f"{c['mode_of_payment']}: {flt(c['closing_amount']):,.2f}" for c in log[0]["counts"])
    if doc.get("sungas_recounted") and (doc.get("variance_severity") or "") in ("block", "critical") \
            and not (doc.get("sungas_count_witness") or "").strip():
        frappe.throw(_("This recount still shows a large difference. The Plant Manager must witness it - "
                       "type their name in 'Recount witnessed by'."), title=_("Witness required"))


# -- Lodgement creation ---------------------------------------------------------

def create_lodgement(doc, method=None):
    if doc.get("sungas_cash_lodgement") or frappe.db.exists(LODGEMENT, {"closing_shift": doc.name, "docstatus": ["<", 2]}):
        return
    rows = [r for r in doc.payment_reconciliation or [] if _is_cash(r.mode_of_payment)]
    counted = sum(flt(r.closing_amount) for r in rows)
    float_ = sum(flt(r.opening_amount) for r in rows)
    to_lodge = flt(counted - float_, 2)
    if to_lodge <= 0:
        return
    wh = frappe.db.get_value("POS Profile", doc.pos_profile, "warehouse")
    pm = _plant_manager(doc.pos_profile, wh)
    cl = frappe.get_doc({"doctype": LODGEMENT, "closing_shift": doc.name, "pos_profile": doc.pos_profile, "plant": wh,
                         "company": doc.company, "cashier": doc.user, "plant_manager": pm,
                         "shift_date": getdate(doc.get("period_end_date") or nowdate()),
                         "counted_cash": counted, "opening_float": float_, "cash_to_lodge": to_lodge,
                         "lodged_amount": to_lodge, "status": "Awaiting Lodgement"})
    cl.flags.ignore_permissions = cl.flags.ignore_mandatory = True
    cl.insert()
    doc.db_set("sungas_cash_lodgement", cl.name, update_modified=False)
    _ask_pm(cl, first=True)


def _ask_pm(cl, first=False):
    from sungas.utils.whatsapp import doc_url, first_name

    plant = (cl.plant or "").replace(" - SCL", "")
    who = frappe.db.get_value("User", cl.cashier, "full_name") or cl.cashier
    _ring([cl.plant_manager], _("Lodge {0:,.0f} cash from {1}'s shift ({2})").format(flt(cl.cash_to_lodge), who, plant),
          _("<p>Bank the cash and record the deposit on <b>{0}</b>: amount, bank, teller number and a photo of the "
            "slip.</p>").format(cl.name), cl.name)
    _wa([cl.plant_manager], "sungas_approval_needed", {
        "approver_name": first_name(cl.plant_manager), "doc_label": f"Cash lodgement {cl.name}",
        "summary": f"{plant}: NGN {flt(cl.cash_to_lodge):,.0f} from {who}'s shift of {cl.shift_date}",
        "state": "bank it and record the teller no. + slip photo", "link": doc_url(LODGEMENT, cl.name)},
        ref=f"CL:{cl.name}:{'new' if first else 'remind'}")


# -- Lodgement controller hooks --------------------------------------------------

def validate_lodgement(doc):
    roles = set(frappe.get_roles())
    if not doc.flags.ignore_permissions and not roles & DECIDE_ALL \
            and frappe.session.user not in (doc.plant_manager, "Administrator"):
        from sungas.lpg_fill import user_plants

        if doc.plant not in user_plants(frappe.session.user):
            frappe.throw(_("Only the Plant Manager of {0} or Finance can record this lodgement.").format(doc.plant))
    doc.difference = flt(flt(doc.lodged_amount) - flt(doc.cash_to_lodge), 2)
    if doc.docstatus == 0 and doc.lodgement_date:
        if getdate(doc.lodgement_date) > getdate(nowdate()):
            frappe.throw(_("Date Lodged cannot be in the future."))
        if doc.shift_date and getdate(doc.lodgement_date) < getdate(doc.shift_date):
            frappe.throw(_("Date Lodged cannot be before the shift date."))
    if doc.bank_account:
        acc = frappe.db.get_value("Account", doc.bank_account, ["account_type", "company", "is_group"], as_dict=True)
        if not acc or acc.account_type != "Bank" or acc.company != doc.company or acc.is_group:
            frappe.throw(_("Pick a bank account of {0}.").format(doc.company))


def before_submit_lodgement(doc):
    if flt(doc.lodged_amount) <= 0:
        frappe.throw(_("Enter the amount lodged."))
    if abs(flt(doc.difference)) >= 1 and not (doc.remarks or "").strip():
        frappe.throw(_("Lodged {0:,.2f} but the shift cash to lodge is {1:,.2f}. Type the reason in Remarks.")
                     .format(flt(doc.lodged_amount), flt(doc.cash_to_lodge)))


def _je(doc, lines, remark, submit):
    je = frappe.get_doc({"doctype": "Journal Entry", "voucher_type": "Bank Entry" if not submit else "Journal Entry",
                         "company": doc.company, "posting_date": doc.lodgement_date, "cheque_no": doc.teller_no,
                         "cheque_date": doc.lodgement_date, "user_remark": remark, "accounts": lines})
    je.flags.ignore_permissions = True
    je.insert()
    if submit:
        je.submit()
    return je.name


def on_submit_lodgement(doc):
    from sungas.lpg_fill import _ensure_account, role_users

    mop = next((r.mode_of_payment for r in frappe.get_doc("POS Closing Shift", doc.closing_shift).payment_reconciliation
                if _is_cash(r.mode_of_payment)), None)
    till = _cash_account(mop, doc.company) if mop else None
    if not till:
        frappe.throw(_("No cash account set on the till's cash payment mode {0}.").format(mop or "-"))
    transit = _ensure_account(doc.company, TRANSIT_ACCOUNT, "Asset", ("Current Assets",))
    cc = frappe.db.get_value("POS Profile", doc.pos_profile, "cost_center")
    amt = flt(doc.lodged_amount, 2)
    plant = (doc.plant or "").replace(" - SCL", "")
    remark = f"{doc.name}: {plant} cash of shift {doc.shift_date} ({doc.closing_shift}), teller {doc.teller_no}"
    j1 = _je(doc, [{"account": transit, "debit_in_account_currency": amt, "cost_center": cc},
                   {"account": till, "credit_in_account_currency": amt, "cost_center": cc}], remark, submit=True)
    j2 = _je(doc, [{"account": doc.bank_account, "debit_in_account_currency": amt, "cost_center": cc},
                   {"account": transit, "credit_in_account_currency": amt, "cost_center": cc}],
             remark + " -- submit only after matching the bank statement", submit=False)
    doc.db_set({"transit_journal": j1, "bank_journal": j2, "status": "In Transit", "escalation": 0})
    _ring(role_users(FINANCE), _("Match cash lodgement {0}: {1:,.0f} at {2}").format(doc.name, amt, plant),
          _("<p>{0} lodged {1:,.2f} ({2}, teller {3}, {4}). Match it to the downloaded bank statement, then submit the "
            "draft bank posting <b>{5}</b>.</p>").format(escape_html(doc.plant_manager or ""), amt,
                                                          escape_html(doc.bank_account), escape_html(doc.teller_no),
                                                          doc.lodgement_date, j2), doc.name)
    if abs(flt(doc.difference)) >= 1:
        _ring(role_users(HEADS) + [doc.plant_manager],
              _("Cash lodgement difference {0:+,.0f} at {1}").format(flt(doc.difference), plant),
              _("<p>{0}: cash to lodge {1:,.2f}, lodged {2:,.2f}. Reason: {3}</p>").format(
                  doc.name, flt(doc.cash_to_lodge), amt, escape_html(doc.remarks or "")), doc.name)


def on_cancel_lodgement(doc):
    if doc.bank_journal and frappe.db.get_value("Journal Entry", doc.bank_journal, "docstatus") == 1:
        frappe.throw(_("The bank posting {0} is already matched and submitted - cancel it first.").format(doc.bank_journal))
    if doc.bank_journal and frappe.db.exists("Journal Entry", doc.bank_journal):
        frappe.delete_doc("Journal Entry", doc.bank_journal, ignore_permissions=True)
    if doc.transit_journal:
        je = frappe.get_doc("Journal Entry", doc.transit_journal)
        if je.docstatus == 1:
            je.flags.ignore_permissions = True
            je.cancel()
    doc.db_set({"status": "Cancelled", "bank_journal": None})


def journal_submitted(doc, method=None):
    name = frappe.db.get_value(LODGEMENT, {"bank_journal": doc.name, "docstatus": 1})
    if name:
        frappe.db.set_value(LODGEMENT, name, {"status": "Banked", "banked_on": nowdate(), "banked_by": frappe.session.user})


def journal_cancelled(doc, method=None):
    name = frappe.db.get_value(LODGEMENT, {"bank_journal": doc.name, "docstatus": 1})
    if name:
        frappe.db.set_value(LODGEMENT, name, {"status": "In Transit", "banked_on": None, "banked_by": None})


# -- Daily escalation -----------------------------------------------------------

def sweep() -> dict:
    from sungas.lpg_fill import role_users
    from sungas.utils.whatsapp import doc_url, first_name

    today = getdate(nowdate())
    out = {"reminded": 0, "escalated": 0, "finance": 0}
    for r in frappe.get_all(LODGEMENT, filters={"docstatus": 0, "status": "Awaiting Lodgement"},
                            fields=["name", "plant", "plant_manager", "shift_date", "cash_to_lodge", "escalation", "cashier"]):
        late = working_days(r.shift_date, today)
        plant = (r.plant or "").replace(" - SCL", "")
        if late >= 2 and (r.escalation or 0) < 2:
            _ring(role_users(HEADS) + [r.plant_manager], _("ESCALATED: cash not lodged - {0} {1:,.0f}").format(plant, flt(r.cash_to_lodge)),
                  _("<p>{0}: {1:,.2f} cash from the shift of {2} is still not lodged after {3} working days.</p>")
                  .format(r.name, flt(r.cash_to_lodge), r.shift_date, late), r.name)
            frappe.db.set_value(LODGEMENT, r.name, "escalation", 2, update_modified=False)
            out["escalated"] += 1
        elif late >= 1 and (r.escalation or 0) < 1:
            _ring([r.plant_manager], _("Cash not lodged yet - {0} {1:,.0f}").format(plant, flt(r.cash_to_lodge)),
                  _("<p>{0}: bank the cash from the shift of {1} today and record the deposit.</p>").format(r.name, r.shift_date), r.name)
            _wa([r.plant_manager], "sungas_approval_overdue", {
                "approver_name": first_name(r.plant_manager), "doc_label": f"Cash lodgement {r.name} (NGN {flt(r.cash_to_lodge):,.0f})",
                "hours": str(late * 24), "waiting_on": "you to bank it", "link": doc_url(LODGEMENT, r.name)}, ref=f"CL:{r.name}:late")
            frappe.db.set_value(LODGEMENT, r.name, "escalation", 1, update_modified=False)
            out["reminded"] += 1
    for r in frappe.get_all(LODGEMENT, filters={"docstatus": 1, "status": "In Transit", "escalation": ["<", 3],
                                                 "lodgement_date": ["<=", add_days(today, -BANK_MATCH_DAYS)]},
                            fields=["name", "plant", "bank_journal", "lodged_amount", "lodgement_date"]):
        _ring(role_users(FINANCE + ("Internal Control",)),
              _("Lodgement not matched to the bank in {0} days - {1}").format(BANK_MATCH_DAYS, r.name),
              _("<p>{0} ({1}, {2:,.2f}, lodged {3}) is still not matched. Check the bank statement and submit {4}, "
                "or raise it with the Plant Manager.</p>").format(r.name, escape_html(r.plant or ""), flt(r.lodged_amount),
                                                                   r.lodgement_date, r.bank_journal), r.name)
        frappe.db.set_value(LODGEMENT, r.name, "escalation", 3, update_modified=False)
        out["finance"] += 1
    frappe.db.commit()
    return out


@frappe.whitelist(methods=["POST"])
def run_sweep() -> dict:
    frappe.only_for("System Manager")
    return sweep()


# -- Briefing ---------------------------------------------------------------------

def briefing_section(user, roles) -> str:
    from sungas.scheduled_jobs.briefing_figures import outlets_for

    whs = outlets_for(user, roles)
    if whs is not None and not whs:
        return ""
    rows = {}
    for r in frappe.get_all(LODGEMENT, filters={"docstatus": ["<", 2], "status": ["in", ["Awaiting Lodgement", "In Transit"]]},
                            fields=["plant", "status", "cash_to_lodge", "lodged_amount", "shift_date"]):
        if whs is not None and r.plant not in whs:
            continue
        x = rows.setdefault(r.plant, {"due": 0.0, "n_due": 0, "transit": 0.0, "n_transit": 0, "oldest": r.shift_date})
        if r.status == "Awaiting Lodgement":
            x["due"] += flt(r.cash_to_lodge)
            x["n_due"] += 1
            x["oldest"] = min(x["oldest"], r.shift_date)
        else:
            x["transit"] += flt(r.lodged_amount)
            x["n_transit"] += 1
    if not rows:
        return ""
    td = '<td style="text-align:right;padding:2px 8px">{0}</td>'
    body = "".join(f'<tr><td style="padding:2px 8px">{escape_html((p or "-").replace(" - SCL", ""))}</td>'
                   + td.format(x["n_due"]) + td.format(f'{x["due"]:,.0f}')
                   + td.format(frappe.utils.formatdate(x["oldest"]) if x["n_due"] else "-")
                   + td.format(x["n_transit"]) + td.format(f'{x["transit"]:,.0f}') + "</tr>"
                   for p, x in sorted(rows.items(), key=lambda kv: -kv[1]["due"]))
    return ('<h4>Cash to bank</h4><table border="1" cellspacing="0" style="border-collapse:collapse;font-size:13px">'
            '<tr><th style="text-align:left;padding:2px 8px">Plant</th><th>Shifts not lodged</th><th>NGN</th>'
            '<th>Oldest shift</th><th>Lodged, not matched</th><th>NGN</th></tr>' + body + '</table>')


# -- Install ------------------------------------------------------------------------

def install():
    try:
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

        ro = {"read_only": 1, "no_copy": 1}
        create_custom_fields({"POS Closing Shift": [
            {"fieldname": "sungas_count_section", "fieldtype": "Section Break", "label": "Cash Count",
             "insert_after": "variance_remarks", "collapsible": 1},
            {"fieldname": "sungas_first_count", "fieldtype": "Small Text", "label": "First Count (before recount)",
             "insert_after": "sungas_count_section", **ro},
            {"fieldname": "sungas_recounted", "fieldtype": "Check", "label": "Recounted",
             "insert_after": "sungas_first_count", **ro},
            {"fieldname": "sungas_count_witness", "fieldtype": "Data", "label": "Recount Witnessed By",
             "insert_after": "sungas_recounted", **ro},
            {"fieldname": "sungas_cash_lodgement", "fieldtype": "Link", "options": LODGEMENT, "label": "Cash Lodgement",
             "insert_after": "sungas_count_witness", "allow_on_submit": 1, **ro},
        ], "POS Opening Shift": [
            {"fieldname": "sungas_count_log", "fieldtype": "Long Text", "label": "Cash Counts (each Submit count)",
             "allow_on_submit": 1, **ro},
        ]}, update=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.shift_controls.install")
