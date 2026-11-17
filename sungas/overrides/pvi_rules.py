"""Patch 0045 -- POS Variance Investigation: each person writes and signs only their own box.

1. Cashier (the shift's cashier only) writes her statement and signs it (sign_statement) within 24 hours.
2. Plant Manager of the till investigates (cause, corrective action, notes) and submits = PM signature.
   Cashier silent 48 hours -> PM may record 'cashier unavailable' with a witness (record_unavailable).
3. Head of Operations and Head of Finance sign through the closing-shift approval (stamped automatically).
Nobody signs two boxes; the cashier's statement is locked once signed.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

DT = "POS Variance Investigation"
CASHIER_HOURS, UNAVAILABLE_HOURS = 24, 48
HEADS = {"LPG Head of Operations", "LPG Head of Finance", "System Manager"}
PM_FIELDS = ("primary_cause", "other_cause_detail", "contributing_factors", "corrective_action", "plant_manager_notes")
LOCKED = ("cashier_signed_by", "cashier_signed_on", "plant_manager_signed_by", "plant_manager_signed_on",
          "hod_ops_signed_by", "hod_ops_signed_on", "hod_finance_signed_by", "hod_finance_signed_on",
          "cashier_unavailable", "unavailable_witness", "unavailable_reason")


def _plant(doc):
    return frappe.db.get_value("POS Profile", doc.pos_profile, "warehouse") if doc.pos_profile else None


def is_plant_manager(doc, user) -> bool:
    from sungas.lpg_fill import user_plants

    return "LPG Plant Manager" in frappe.get_roles(user) and _plant(doc) in user_plants(user)


def signers(doc) -> set:
    return {doc.get(f) for f in ("cashier_signed_by", "plant_manager_signed_by", "hod_ops_signed_by",
                                 "hod_finance_signed_by") if doc.get(f)}


def validate(doc):
    # Patch 0048: the amount follows the close (a corrected close used to leave the old figure here).
    if doc.shift:
        doc.set("variance_amount", frappe.db.get_value("POS Closing Shift", doc.shift, "variance_amount"))
    if doc.flags.sungas_internal or frappe.flags.in_install or frappe.flags.in_migrate:
        return
    user = frappe.session.user
    if user == "Administrator":
        return
    old = doc.get_doc_before_save()
    changed = (lambda f: (old.get(f) if old else None) != doc.get(f)) if old else (lambda f: bool(doc.get(f)))
    # Patch 0049: signatures are only ever set by the system -- a page opened before an approver signed
    # (stale form) used to block the save; now the stored signatures are simply kept.
    for f in LOCKED:
        doc.set(f, old.get(f) if old else None)
    if user == doc.cashier and any(changed(f) for f in PM_FIELDS):
        for f in PM_FIELDS:
            doc.set(f, old.get(f) if old else None)
        frappe.msgprint(_("Your statement is saved. The cause and corrective action are filled by the Plant Manager, "
                          "so what you typed there was not kept."), indicator="orange", alert=True)
    if changed("cashier_statement"):
        if old and old.cashier_signed_by:
            frappe.throw(_("The cashier's statement is signed and can no longer be changed."))
        if user != doc.cashier:
            frappe.throw(_("Only the cashier of this shift ({0}) can write her statement. If she is unavailable "
                           "for {1} hours, the Plant Manager records that instead.").format(doc.cashier, UNAVAILABLE_HOURS))
    outs = lambda d: [(r.outcome, r.mode_of_payment, float(r.amount or 0), r.note) for r in (d.get("outcomes") or [])]
    pm_changed = any(changed(f) for f in PM_FIELDS) or (outs(old) if old else []) != outs(doc)
    if pm_changed:
        if user == doc.cashier:
            doc.set("outcomes", old.get("outcomes") if old else [])
            pm_changed = False
        elif not (is_plant_manager(doc, user) or HEADS & set(frappe.get_roles(user))):
            frappe.throw(_("Only the Plant Manager of this till can fill the investigation."))
    # Patch 0055: each Head writes only his own note, and only while the case is waiting for him.
    for f, role, state in (("hod_ops_notes", "LPG Head of Operations", "Waiting for Head of Operations"),
                           ("hod_finance_notes", "LPG Head of Finance", "Waiting for Head of Finance")):
        if changed(f) and not (role in frappe.get_roles(user) and doc.get("case_status") == state):
            doc.set(f, old.get(f) if old else None)
            frappe.msgprint(_("Only the {0} writes that note, while the case is waiting for him - your change to it "
                              "was not kept.").format(role.replace("LPG ", "")), indicator="orange", alert=True)
    # Patch 0052: once sent for approval the finding is frozen -- an approver sends it back to change it.
    if pm_changed and doc.get("case_status") in ("Waiting for Head of Operations", "Waiting for Head of Finance"):
        frappe.throw(_("This case has been sent for approval. Ask the approver to send it back to change the "
                       "finding or outcome."), title=_("Waiting for approval"))


def before_submit(doc):
    # Patch 0052: a case is closed by its final approval (variance_case.finalize), never by the Submit button.
    if not doc.flags.sungas_final:
        frappe.throw(_("A variance case closes when its last approver approves it. Use the buttons at the top of the "
                       "case."), title=_("Use the case buttons"))


@frappe.whitelist(methods=["POST"])
def sign_statement(name: str) -> dict:
    doc = frappe.get_doc(DT, name)
    if frappe.session.user != doc.cashier:
        frappe.throw(_("Only {0} can sign this statement.").format(doc.cashier))
    if doc.docstatus != 0 or doc.cashier_signed_by:
        frappe.throw(_("Already signed."))
    if not (doc.cashier_statement or "").strip():
        frappe.throw(_("Write your statement first, save, then sign."))
    doc.flags.sungas_internal = True
    doc.cashier_signed_by, doc.cashier_signed_on = doc.cashier, now_datetime()
    doc.save(ignore_permissions=True)
    # Patch 0052: the case moves to the Plant Manager (who is told by variance_case.notify).
    from sungas.variance_case import advance_after_cashier

    advance_after_cashier(doc)
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def record_unavailable(name: str, witness: str, reason: str) -> dict:
    doc = frappe.get_doc(DT, name)
    user = frappe.session.user
    if not is_plant_manager(doc, user) and "LPG Head of Operations" not in frappe.get_roles(user):
        frappe.throw(_("Only the Plant Manager of this till can record this."))
    if doc.docstatus != 0 or doc.cashier_signed_by:
        frappe.throw(_("The cashier has already signed."))
    if get_datetime(doc.creation) > add_to_date(now_datetime(), hours=-UNAVAILABLE_HOURS):
        frappe.throw(_("Give the cashier {0} hours to write her statement (from {1}).").format(
            UNAVAILABLE_HOURS, frappe.utils.format_datetime(doc.creation, "dd-MM-yyyy HH:mm")))
    if not (witness or "").strip() or not (reason or "").strip() or witness.strip() == user:
        frappe.throw(_("Name a witness (not yourself) and the reason."))
    doc.flags.sungas_internal = True
    doc.cashier_unavailable, doc.unavailable_witness, doc.unavailable_reason = 1, witness.strip(), reason.strip()
    doc.save(ignore_permissions=True)
    from sungas.variance_case import advance_after_cashier

    advance_after_cashier(doc)
    return {"ok": True}


def _tell_pm(doc, subject):
    from sungas.overrides.closing_approval_alerts import approvers
    from sungas.utils.bell import ring

    pms = approvers(frappe._dict(pos_profile=doc.pos_profile), "Pending Plant Manager")
    ring(pms, subject, f"<p>{subject}</p>", DT, doc.name)


def stamp_from_closing(closing, old_state, user):
    """Closing-shift approval moved off old_state -> sign that box on the investigation."""
    box = {"Pending HOD Operations": "hod_ops", "Pending HOD Finance": "hod_finance"}.get(old_state)
    pvi = closing.get("pos_variance_investigation")
    if not box or not pvi:
        return
    frappe.db.set_value(DT, pvi, {f"{box}_signed_by": user, f"{box}_signed_on": now_datetime()}, update_modified=False)


def check_closing_approver(closing, method=None):
    """POS Closing Shift validate: the approver must not have signed another box of its investigation."""
    old = closing.get_doc_before_save()
    if not old or old.workflow_state == closing.workflow_state or not closing.get("pos_variance_investigation"):
        return
    if old.workflow_state not in ("Pending Plant Manager", "Pending HOD Operations", "Pending HOD Finance"):
        return
    user = frappe.session.user
    if user == "Administrator":
        return
    pvi = frappe.get_doc(DT, closing.pos_variance_investigation)
    # Patch 0050: nobody approves a close (Plant Manager included) until its investigation is finished.
    if closing.workflow_state != "Rejected" and pvi.docstatus != 1:
        frappe.throw(_("Investigation {0} is not finished yet. The cashier writes and signs her statement, then the "
                       "Plant Manager fills the cause and corrective action and submits it. Approve this close after "
                       "that.").format(pvi.name), title=_("Investigation not finished"))
    mine = {"Pending Plant Manager": pvi.plant_manager_signed_by}.get(old.workflow_state)
    if user == closing.user or (user in signers(pvi) and user != mine):
        frappe.throw(_("You already signed this case in another role (or it is your own shift). "
                       "Another approver must take this step."), title=_("Separation of duties"))
    if old.workflow_state in ("Pending HOD Operations", "Pending HOD Finance") and closing.workflow_state != "Rejected":
        stamp_from_closing(closing, old.workflow_state, user)


def tell_cashier(pvi_name):
    """Patch 0050: the cashier is told (bell + WhatsApp) the moment her investigation opens."""
    from frappe.utils import flt

    from sungas.utils import whatsapp
    from sungas.utils.bell import ring

    d = frappe.get_doc(DT, pvi_name)
    if not d.cashier or d.cashier_signed_by:
        return
    link = whatsapp.doc_url(DT, d.name)
    amt = abs(flt(d.variance_amount))
    ring([d.cashier], _("Write and sign your statement on {0}").format(d.name),
         f"<p>Your shift close {d.shift} has a cash difference of NGN {amt:,.2f}. Open <a href=\"{link}\">{d.name}</a>, "
         "write what happened in your own words, press <b>Save</b>, then <b>Sign my statement</b>. "
         "Your till stays locked until the case is approved.</p>", DT, d.name)
    whatsapp.send([d.cashier], "sungas_approval_needed", {
        "approver_name": whatsapp.first_name(d.cashier), "doc_label": f"Variance investigation {d.name}",
        "summary": f"Shift close {d.shift}, difference NGN {amt:,.0f}",
        "state": "Write and sign your statement - tap the link", "link": link}, ref=f"PVI:{d.name}:cashier")


def nudge() -> int:
    """Patch 0050 (hourly): cashier has not signed 4 hours after the investigation opened -> her Plant Manager."""
    from sungas.overrides.closing_approval_alerts import approvers
    from sungas.utils.bell import ring

    n = 0
    for r in frappe.get_all(DT, filters={"docstatus": 0, "cashier_signed_by": ["is", "not set"], "cashier_unavailable": 0,
                                         "creation": ["<", add_to_date(now_datetime(), hours=-4)]},
                            fields=["name", "cashier", "pos_profile", "shift"]):
        subject = f"{r.name}: {r.cashier} has not signed her statement after 4 hours"
        for u in approvers(frappe._dict(pos_profile=r.pos_profile), "Pending Plant Manager"):
            if not frappe.db.exists("Notification Log", {"for_user": u, "subject": subject}):
                ring([u], subject, f"<p>Shift close {r.shift} is waiting on the cashier's statement. Please follow up "
                                   "with her today.</p>", DT, r.name)
                n += 1
    frappe.db.commit()
    return n


def sweep() -> dict:
    from sungas.utils.bell import ring

    out = {"cashier": 0, "pm": 0}
    now = now_datetime()
    for r in frappe.get_all(DT, filters={"docstatus": 0, "cashier_signed_by": ["is", "not set"], "cashier_unavailable": 0},
                            fields=["name", "cashier", "pos_profile", "creation"]):
        age = (now - get_datetime(r.creation)).total_seconds() / 3600
        if age >= UNAVAILABLE_HOURS:
            subject = f"{r.name}: cashier has not signed after {UNAVAILABLE_HOURS} hours - record 'cashier unavailable'"
            from sungas.overrides.closing_approval_alerts import approvers

            for u in approvers(frappe._dict(pos_profile=r.pos_profile), "Pending Plant Manager"):
                if not frappe.db.exists("Notification Log", {"for_user": u, "subject": subject}):
                    ring([u], subject, f"<p>{subject} with a witness, then submit.</p>", DT, r.name)
                    out["pm"] += 1
        elif age >= CASHIER_HOURS:
            subject = f"Write and sign your statement on {r.name} today"
            if r.cashier and not frappe.db.exists("Notification Log", {"for_user": r.cashier, "subject": subject}):
                ring([r.cashier], subject, f"<p>Your shift close has a large cash difference. Open {r.name}, write what "
                                           "happened in your own words, save, then press 'Sign my statement'.</p>", DT, r.name)
                out["cashier"] += 1
    frappe.db.commit()
    return out


# Patch 0061: a Plant Manager sees only his own plants' cases (PMs also hold Accounts User,
# which used to open every plant's cases to them).
FULL_VIEW = {"LPG Head of Operations", "LPG Head of Finance", "System Manager", "Internal Control", "COO",
             "Chief Operating Officer", "LPG Chief Operating Officer", "Accounts Manager"}


def _scope(user):
    """None = every case; else the POS Profiles whose cases this user may see (besides own / watched)."""
    roles = set(frappe.get_roles(user))
    if user == "Administrator" or FULL_VIEW & roles:
        return None
    if "LPG Plant Manager" not in roles:
        return None if "Accounts User" in roles else []
    from sungas.lpg_fill import user_plants

    return frappe.get_all("POS Profile", filters={"warehouse": ["in", list(user_plants(user)) or [""]]}, pluck="name")


def pvi_query(user=None):
    user = user or frappe.session.user
    profiles = _scope(user)
    if profiles is None:
        return ""
    t = "`tabPOS Variance Investigation`"
    conds = [f"{t}.cashier = {frappe.db.escape(user)}", f"{t}.watchers like {frappe.db.escape('%' + user + '%')}"]
    if profiles:
        conds.append(f"{t}.pos_profile in ({', '.join(frappe.db.escape(p) for p in profiles)})")
    return "(" + " or ".join(conds) + ")"


def pvi_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    profiles = _scope(user)
    if profiles is None:
        return True
    watching = user in (doc.get("watchers") or "").split("\n")
    return doc.cashier == user or doc.pos_profile in profiles or (watching and ptype in (None, "read", "print"))


@frappe.whitelist(methods=["POST"])
def send_for_review(closing: str) -> dict:
    """Patch 0047: a submitted close whose difference was never posted goes to the Plant Manager first;
    its entry posts when the investigation is submitted."""
    frappe.only_for(("System Manager", "LPG Head of Finance", "LPG Head of Operations"))
    from sungas.overrides.pos_closing_shift import _diff_lines, _mode_differences

    doc = frappe.get_doc("POS Closing Shift", closing)
    if doc.docstatus != 1 or doc.get("variance_je") or not _mode_differences(doc):
        frappe.throw(_("{0} is not a submitted close with an unposted difference.").format(closing))
    dt = DT
    pvi = doc.get("pos_variance_investigation") or frappe.db.get_value(dt, {"shift": closing, "docstatus": ["!=", 2]}, "name")
    if not pvi:
        pvi = frappe.get_doc({
            "doctype": dt, "shift": closing, "variance_severity": "review",
            "variance_amount": doc.get("variance_amount"), "pos_profile": doc.pos_profile,
            "cashier": doc.user, "period_end_date": doc.get("period_end_date"),
        }).insert(ignore_permissions=True, ignore_mandatory=True).name
        frappe.db.set_value("POS Closing Shift", closing, "pos_variance_investigation", pvi, update_modified=False)
    from sungas.utils.bell import ring

    detail = "<br>".join(_diff_lines(doc))
    ring([doc.user], _("Write your statement on {0} for close {1}").format(pvi, closing),
         f"<p>{detail}</p>", dt, pvi)
    _tell_pm(frappe.get_doc(dt, pvi), _("Review close {0} ({1}) - investigate and submit").format(closing, pvi))
    return {"pvi": pvi}
