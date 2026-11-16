"""Patch 0052 (Workflow v2, Phase 1) -- the close always completes; big differences become a Variance Case.

At close (block / critical): each payment type's difference is held in Cash Variance Pending (cashier as party)
and a case opens.  Case: Cashier statement -> Plant Manager finding + outcomes -> Head of Operations
-> Head of Finance (critical only) -> one clearing entry.  Approvers may send the case back to the Plant Manager.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, get_datetime, getdate, now_datetime

DT = "POS Variance Investigation"
W_CASHIER, W_PM, W_HOO, W_HOF, CLOSED = ("Waiting for Cashier", "Waiting for Plant Manager",
                                         "Waiting for Head of Operations", "Waiting for Head of Finance", "Closed")
STATE_FOR = {W_PM: "Pending Plant Manager", W_HOO: "Pending HOD Operations", W_HOF: "Pending HOD Finance"}
# outcome -> (side, where the money goes: "mop" = the payment type's own account, else a Close Policy account)
OUTCOMES = {
    "Cash recovered": ("short", "mop"),
    "Charge the cashier": ("short", "cashier_recovery_account"),
    "Count error (short)": ("short", "mop"),
    "Write off": ("short", "shortage_writeoff_account"),
    "Keep as overage": ("over", "overage_suspense_account"),
    "Count error (over)": ("over", "mop"),
}
NEEDS_NOTE = ("Count error (short)", "Count error (over)", "Write off")
SLA_FIELDS = {W_CASHIER: ("sla_cashier_hours", 4), W_PM: ("sla_pm_hours", 24),
              W_HOO: ("sla_hoo_hours", 24), W_HOF: ("sla_hof_hours", 48)}
UP_CHAIN = {W_CASHIER: W_PM, W_PM: W_HOO, W_HOO: W_HOF, W_HOF: "Pending COO"}


# ---------------------------------------------------------------- opening
def open_case(closing):
    """on_submit of a block / critical close: hold the differences and open the case."""
    from sungas.overrides.pos_closing_shift import _diff_lines, _mode_differences, _mode_rows, _shift_posting_date

    diffs = _mode_differences(closing)
    if not diffs or closing.get("pos_variance_investigation"):
        return None
    policy = frappe.get_single("Sungas Close Policy")
    pending = policy.get("cash_variance_pending_account")
    employee = frappe.db.get_value("Employee", {"user_id": closing.user}, "name")
    short = sum(-d for _m, d in diffs if d < 0)
    over = sum(d for _m, d in diffs if d > 0)
    holding = None
    try:
        je = frappe.get_doc({
            "doctype": "Journal Entry", "voucher_type": "Journal Entry", "company": closing.company,
            "posting_date": _shift_posting_date(closing), "title": f"Cash Variance Held - {closing.name}",
            "user_remark": "\n".join([f"Held for the variance case on POS Closing Shift {closing.name} "
                                      f"(cashier {closing.user}).", "Differences:", *_diff_lines(closing)]),
            "accounts": _mode_rows(closing, pending, pending, employee),
        })
        je.flags.ignore_permissions = True
        je.insert()
        je.submit()
        holding = je.name
        closing.db_set("variance_provisional_je", holding, update_modified=False)
    except Exception:
        frappe.clear_last_message()
        frappe.log_error(frappe.get_traceback(), f"sungas.variance_case holding entry failed for {closing.name}")
    case = frappe.get_doc({
        "doctype": DT, "shift": closing.name, "pos_profile": closing.pos_profile, "cashier": closing.user,
        "period_end_date": getdate(closing.period_end_date), "variance_severity": closing.variance_severity,
        "variance_amount": closing.variance_amount, "shortage_total": short, "overage_total": over,
        "holding_je": holding, "case_status": W_CASHIER, "waiting_since": now_datetime(),
    })
    case.flags.sungas_internal = True
    case.insert(ignore_permissions=True, ignore_mandatory=True)
    closing.db_set("pos_variance_investigation", case.name, update_modified=False)
    notify(case)
    if frappe.session.user == closing.user:
        frappe.msgprint(
            _("Your shift is closed. It has a cash difference (Short NGN {0:,.2f} / Over NGN {1:,.2f}), so variance case "
              "<b>{2}</b> has been opened.<br><br>Open it from the bell (top right) or the link we sent you, write what "
              "happened, press <b>Save</b>, then <b>Sign my statement</b>. You can open your next shift now.")
            .format(short, over, case.name), title=_("Write your statement"), indicator="orange")
    return case.name


# ---------------------------------------------------------------- moving the case
def _set_status(case, status, **fields):
    fields.update(case_status=status, waiting_since=now_datetime())
    case.flags.sungas_internal = True
    case.update(fields)
    case.save(ignore_permissions=True)
    notify(case)


def advance_after_cashier(case):
    """Cashier signed (or PM recorded her unavailable) -> Plant Manager's turn."""
    if case.case_status == W_CASHIER:
        _set_status(case, W_PM)


def _is_pm(case, user):
    from sungas.overrides.pvi_rules import is_plant_manager

    return is_plant_manager(case, user) or "System Manager" in frappe.get_roles(user)


def check_outcomes(case):
    rows = case.get("outcomes") or []
    if not rows:
        frappe.throw(_("Add the outcome: what happened to the money (recovered, charged to the cashier, count error, "
                       "write off or kept as overage)."), title=_("Outcome missing"))
    sides = {"short": 0.0, "over": 0.0}
    for r in rows:
        if r.outcome not in OUTCOMES or flt(r.amount) <= 0:
            frappe.throw(_("Row {0}: choose an outcome and an amount above zero.").format(r.idx))
        side, target = OUTCOMES[r.outcome]
        if target == "mop" and not r.mode_of_payment:
            frappe.throw(_("Row {0}: choose the payment type ({1}).").format(r.idx, r.outcome))
        # Patch 0055: only this till's payment types; not used for the other outcomes.
        if target != "mop":
            r.mode_of_payment = None
        elif r.mode_of_payment not in till_modes(case):
            frappe.throw(_("Row {0}: {1} is not a payment type of this till.").format(r.idx, r.mode_of_payment))
        if r.outcome in NEEDS_NOTE and not (r.note or "").strip():
            frappe.throw(_("Row {0}: give the reason for '{1}'.").format(r.idx, r.outcome))
        sides[side] += flt(r.amount)
    for side, total in (("short", flt(case.shortage_total)), ("over", flt(case.overage_total))):
        if abs(sides[side] - total) > 0.01:
            frappe.throw(_("The {0} outcomes add up to NGN {1:,.2f} but the {0} is NGN {2:,.2f}.").format(
                _("shortage") if side == "short" else _("overage"), sides[side], total), title=_("Outcomes do not add up"))


def till_modes(case) -> list:
    return frappe.get_all("POS Closing Shift Detail",
                          filters={"parent": case.shift, "parenttype": "POS Closing Shift"}, pluck="mode_of_payment")


@frappe.whitelist()
def case_payment_types(doctype, txt, searchfield, start, page_len, filters):
    """Patch 0055: the outcome's payment type list shows only this till's payment types."""
    case = frappe.get_doc(DT, (filters or {}).get("case"))
    case.check_permission("read")
    return [[m] for m in till_modes(case) if (txt or "").lower() in m.lower()]


@frappe.whitelist(methods=["POST"])
def send_for_approval(name: str) -> dict:
    case = frappe.get_doc(DT, name)
    user = frappe.session.user
    if case.case_status != W_PM:
        frappe.throw(_("This case is not waiting for the Plant Manager ({0}).").format(case.case_status))
    if not _is_pm(case, user) or user == case.cashier:
        frappe.throw(_("Only the Plant Manager of this till can send the case for approval."))
    if not (case.cashier_signed_by or case.cashier_unavailable):
        frappe.throw(_("The cashier has not signed her statement yet."))
    if not case.primary_cause or not (case.corrective_action or "").strip():
        frappe.throw(_("Fill the Primary Cause and the Corrective Action first."))
    if case.primary_cause == "Other" and not (case.get("other_cause_detail") or "").strip():
        frappe.throw(_("Describe the cause (Primary Cause is 'Other')."))
    check_outcomes(case)
    _set_status(case, W_HOO, plant_manager_signed_by=user, plant_manager_signed_on=now_datetime())
    return {"status": case.case_status}


def _approver_check(case, user):
    roles = set(frappe.get_roles(user))
    need = {W_HOO: "LPG Head of Operations", W_HOF: "LPG Head of Finance"}.get(case.case_status)
    if not need:
        frappe.throw(_("This case is not waiting for an approval ({0}).").format(case.case_status))
    if need not in roles and "System Manager" not in roles:
        frappe.throw(_("{0} approves this step.").format(need.replace("LPG ", "")))
    from sungas.overrides.pvi_rules import signers

    if user == case.cashier or user in signers(case):
        frappe.throw(_("You already took part in this case, so another person must approve it."))


@frappe.whitelist(methods=["POST"])
def approve(name: str, notes: str = "") -> dict:
    case = frappe.get_doc(DT, name)
    user = frappe.session.user
    _approver_check(case, user)
    if case.case_status == W_HOO:
        stamp = dict(hod_ops_signed_by=user, hod_ops_signed_on=now_datetime(), hod_ops_notes=notes or case.hod_ops_notes)
        if case.variance_severity == "critical":
            _set_status(case, W_HOF, **stamp)
            return {"status": case.case_status}
        case.update(stamp)
    else:
        case.update(dict(hod_finance_signed_by=user, hod_finance_signed_on=now_datetime(),
                         hod_finance_notes=notes or case.hod_finance_notes))
    finalize(case)
    return {"status": case.case_status, "clearing_je": case.clearing_je}


@frappe.whitelist(methods=["POST"])
def send_back(name: str, reason: str) -> dict:
    case = frappe.get_doc(DT, name)
    user = frappe.session.user
    _approver_check(case, user)
    if not (reason or "").strip():
        frappe.throw(_("Say what the Plant Manager must correct."))
    who = frappe.db.get_value("User", user, "full_name") or user
    case.add_comment("Comment", _("Sent back to the Plant Manager by {0}: {1}").format(who, reason.strip()))
    _set_status(case, W_PM, send_back_reason=f"{who}: {reason.strip()}", plant_manager_signed_by=None,
                plant_manager_signed_on=None, hod_ops_signed_by=None, hod_ops_signed_on=None)
    return {"status": case.case_status}


# ---------------------------------------------------------------- closing the case
def clearing_rows(case, closing, policy, employee):
    from sungas.overrides.pos_closing_shift import _row

    pending = policy.get("cash_variance_pending_account")
    rows = []
    for r in case.outcomes:
        side, target = OUTCOMES[r.outcome]
        acct = (frappe.db.get_value("Mode of Payment Account", {"parent": r.mode_of_payment, "company": closing.company},
                                    "default_account") if target == "mop" else policy.get(target))
        if not acct:
            frappe.throw(_("No account for '{0}' ({1}).").format(r.outcome, r.mode_of_payment or target))
        amt = flt(r.amount, 2)
        if side == "short":
            rows += [_row(acct, amt, 0, employee), _row(pending, 0, amt, employee)]
        else:
            rows += [_row(pending, amt, 0, employee), _row(acct, 0, amt, employee)]
    return rows


def finalize(case):
    closing = frappe.get_doc("POS Closing Shift", case.shift)
    if not case.holding_je:
        frappe.throw(_("The holding entry for {0} is missing, so the case cannot be cleared. Ask Accounts to check "
                       "the Error Log.").format(closing.name))
    policy = frappe.get_single("Sungas Close Policy")
    employee = frappe.db.get_value("Employee", {"user_id": closing.user}, "name")
    je = frappe.get_doc({
        "doctype": "Journal Entry", "voucher_type": "Journal Entry", "company": closing.company,
        "posting_date": getdate(), "title": f"Cash Variance Cleared - {case.name}",
        "user_remark": "\n".join([f"Variance case {case.name} for POS Closing Shift {closing.name} approved.",
                                  *[f"  {r.outcome}: NGN {flt(r.amount):,.2f}" + (f" ({r.mode_of_payment})"
                                    if r.mode_of_payment else "") + (f" - {r.note}" if r.note else "")
                                    for r in case.outcomes]]),
        "accounts": clearing_rows(case, closing, policy, employee),
    })
    je.flags.ignore_permissions = True
    je.insert()
    je.submit()
    closing.db_set("variance_je", je.name, update_modified=False)
    case.flags.sungas_internal = case.flags.sungas_final = case.flags.ignore_permissions = True
    case.update(dict(clearing_je=je.name, case_status=CLOSED, waiting_since=None))
    case.submit()
    notify(case)


# ---------------------------------------------------------------- telling people
def actors(case, status=None):
    from sungas.overrides.closing_approval_alerts import approvers

    status = status or case.case_status
    if status == W_CASHIER:
        return [case.cashier]
    state = STATE_FOR.get(status, status)
    return approvers(frappe._dict(pos_profile=case.pos_profile), state) if state.startswith("Pending") else []


def _send(users, subject, line, case):
    from sungas.utils import brevo, whatsapp

    users = [u for u in dict.fromkeys(users) if u and u not in ("Administrator", "lmd-bot@sungas.org")]
    if not users:
        return
    link = whatsapp.doc_url(DT, case.name)
    html = f"<p>{line}</p><p><a href=\"{link}\">Open {case.name}</a></p>"
    to = [{"email": u, "name": frappe.db.get_value("User", u, "full_name") or u} for u in users]
    brevo.send_transactional_email(to, subject, html, tags=["variance-case"], ref_doctype=DT, ref_name=case.name)
    for u in users:
        whatsapp.send([u], "sungas_approval_needed", {
            "approver_name": whatsapp.first_name(u), "doc_label": f"Variance case {case.name}",
            "summary": f"{case.pos_profile} - short NGN {flt(case.shortage_total):,.0f} / over NGN "
                       f"{flt(case.overage_total):,.0f}", "state": line[:120], "link": link},
            ref=f"VC:{case.name}:{case.case_status}:{u}")


def notify(case):
    who = frappe.db.get_value("User", case.cashier, "full_name") or case.cashier
    amounts = f"short NGN {flt(case.shortage_total):,.2f} / over NGN {flt(case.overage_total):,.2f}"
    s = case.case_status
    if s == CLOSED:
        outs = "; ".join(f"{r.outcome} NGN {flt(r.amount):,.2f}" for r in case.outcomes)
        everyone = [case.cashier, case.plant_manager_signed_by, case.hod_ops_signed_by, case.hod_finance_signed_by]
        _send(everyone, f"{case.name} closed", f"Variance case for {who}'s close {case.shift} is closed: {outs}.", case)
        return
    line = {
        W_CASHIER: f"Your close {case.shift} has a cash difference ({amounts}). Write and sign your statement.",
        W_PM: (f"{case.name}: {who}'s close {case.shift} ({amounts}) is waiting for your finding and outcome."
               + (f" Sent back - {case.send_back_reason}" if case.send_back_reason else "")),
        W_HOO: f"{case.name}: {who}'s close {case.shift} ({amounts}) is waiting for your approval.",
        W_HOF: f"{case.name}: {who}'s close {case.shift} ({amounts}, critical) is waiting for your approval.",
    }[s]
    _send(actors(case), f"{case.name}: {s}", line, case)


def _sla_hours(policy, status):
    field, default = SLA_FIELDS[status]
    return flt(policy.get(field)) or default


def nudge() -> int:
    """Hourly: a case past its SLA reminds the person waited on and alerts the next one up (once per step)."""
    policy = frappe.get_single("Sungas Close Policy")
    n = 0
    for r in frappe.get_all(DT, filters={"docstatus": 0, "case_status": ["in", list(SLA_FIELDS)]},
                            fields=["name", "case_status", "waiting_since"]):
        if not r.waiting_since:
            continue
        hours = _sla_hours(policy, r.case_status)
        if get_datetime(r.waiting_since) > add_to_date(now_datetime(), hours=-hours):
            continue
        case = frappe.get_doc(DT, r.name)
        subject = f"{case.name}: overdue - {case.case_status} for more than {hours:g} h"
        if frappe.db.exists("Notification Log", {"subject": subject}):
            continue
        up = UP_CHAIN[case.case_status]
        _send(actors(case) + actors(case, up), subject,
              f"{case.name} has been '{case.case_status}' for more than {hours:g} hours. Please act today.", case)
        n += 1
    frappe.db.commit()
    return n


# ---------------------------------------------------------------- install
def install():
    """after_migrate: SLA hours on the Close Policy page."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    try:
        fields = [{"fieldname": "case_sla_section", "fieldtype": "Section Break", "label": "Variance Case Time Limits (hours)",
                   "insert_after": "max_shift_age_hours"}]
        prev = "case_sla_section"
        for status, (fn, default) in SLA_FIELDS.items():
            fields.append({"fieldname": fn, "fieldtype": "Float", "label": status, "default": str(default),
                           "insert_after": prev})
            prev = fn
        create_custom_fields({"Sungas Close Policy": fields}, update=True)
        for status, (fn, default) in SLA_FIELDS.items():
            if not frappe.db.get_single_value("Sungas Close Policy", fn):
                frappe.db.set_single_value("Sungas Close Policy", fn, default)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.variance_case.install")
