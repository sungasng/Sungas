"""POS Closing Shift hooks -- variance enforcement + auto-JE posting.

Architecture:
  before_submit: validate variance against Sungas Close Policy thresholds.
                  - If |variance| >= warn threshold AND require_remarks_on_variance:
                    require non-empty variance_remarks custom field.
                  - If |variance| >= block threshold: require approver.
                    Either current user holds an approver role, OR
                    variance_approved_by custom field is set AND that user
                    holds an approver role.
  on_submit:      after consolidation succeeds, auto-post variance JE:
                    Shortage: Dr 2608 (party=Employee) / Cr Cash Sales account
                    Overage:  Dr Cash Sales account / Cr 6224
                  Backfills variance_je link on the Closing Shift.

Custom fields required on POS Closing Shift (installed via fixture):
  - variance_remarks         (Long Text)
  - variance_approved_by     (Link User)
  - variance_je              (Link Journal Entry, read-only)
"""
from __future__ import annotations
import frappe
from frappe import _
from frappe.utils import flt


def _compute_variance(doc):
    """Return (total_variance, total_expected) summed across all MoP rows.
    Variance > 0 = overage (closing > expected). Variance < 0 = shortage.
    """
    total_var = 0.0
    total_expected = 0.0
    for row in (doc.payment_reconciliation or []):
        expected = flt(row.expected_amount)
        closing = flt(row.closing_amount)
        total_var += (closing - expected)
        total_expected += expected
    return total_var, total_expected


_RANK = {"none": 0, "warn": 1, "block": 2, "critical": 3}


def _mode_differences(doc):
    """Patch 0047: (payment type, closing - expected) -- an overage on one type never offsets a shortage on another."""
    out = []
    for row in (doc.payment_reconciliation or []):
        diff = flt(flt(row.closing_amount) - flt(row.expected_amount), 2)
        if abs(diff) >= 0.01:
            out.append((row.mode_of_payment, diff))
    return out


def _gross_severity(doc, policy):
    """Patch 0047: shortages and overages are added up separately, each judged on its own limits; the worse one wins."""
    diffs = _mode_differences(doc)
    short = sum(-d for _m, d in diffs if d < 0)
    over = sum(d for _m, d in diffs if d > 0)
    expected = _compute_variance(doc)[1]
    s_sev = _variance_severity(-short, expected, policy)[0] if short else "none"
    o_sev = _variance_severity(over, expected, policy)[0] if over else "none"
    gross = short + over
    pct = (gross / expected * 100) if expected > 0 else 0
    return max(s_sev, o_sev, key=_RANK.get), gross, pct


def _row(account, dr, cr, employee=None):
    row = {"account": account, "debit_in_account_currency": dr, "credit_in_account_currency": cr}
    if employee and frappe.get_cached_value("Account", account, "account_type") in ("Receivable", "Payable"):
        row.update(party_type="Employee", party=employee)
    return row


def _mode_rows(doc, short_acct, over_acct, employee):
    """Patch 0047: each payment type's difference is booked against that payment type's own account."""
    rows = []
    for mop, diff in _mode_differences(doc):
        acct = frappe.db.get_value("Mode of Payment Account", {"parent": mop, "company": doc.company}, "default_account")
        if not acct:
            frappe.throw(_("Payment type {0} has no account for {1}.").format(mop, doc.company))
        amt = abs(diff)
        if diff < 0:
            rows += [_row(short_acct, amt, 0, employee), _row(acct, 0, amt)]
        else:
            rows += [_row(acct, amt, 0), _row(over_acct, 0, amt, employee)]
    return rows


def _diff_lines(doc):
    return [f"  {m}: {'Over' if d > 0 else 'Short'} NGN {abs(d):,.2f}" for m, d in _mode_differences(doc)]


def _variance_severity(total_var, total_expected, policy):
    """Classify variance as 'none' | 'warn' | 'block' | 'critical'.

    Asymmetric absolute thresholds:
      - Shortage (total_var < 0): warn_abs / block_abs / critical_abs
        (defaults 5k / 50k / 100k).
      - Overage  (total_var > 0): warn_abs_overage / block_abs_overage /
        critical_abs_overage (defaults 10k / 100k / 200k -- ~2x looser
        because overages don't represent an immediate cash loss).

    Percent rules are symmetric and gated by `block_pct_min_expected`:
    on small shifts the absolute rule is the only one that fires.

    Tier semantics:
      - 'none'     : no enforcement; submit allowed.
      - 'warn'     : remarks required; otherwise submit allowed.
      - 'block'    : submit requires approver (LPG Head of Operations etc.).
      - 'critical' : submit requires HOD Finance + (optional) COO sign-off.
                     Used by Wave D-1 Sequential Workflow routing.
    """
    thr = policy.get_thresholds()
    abs_var = abs(total_var)
    pct = (abs_var / total_expected * 100) if total_expected > 0 else 0
    pct_rules_active = total_expected >= thr["block_pct_min_expected"]

    is_overage = total_var > 0
    warn_abs = thr["warn_abs_overage"] if is_overage else thr["warn_abs"]
    block_abs = thr["block_abs_overage"] if is_overage else thr["block_abs"]
    critical_abs = thr["critical_abs_overage"] if is_overage else thr["critical_abs"]

    critical_by_pct = pct_rules_active and pct >= thr["critical_pct"]
    if abs_var >= critical_abs or critical_by_pct:
        return "critical", abs_var, pct

    block_by_pct = pct_rules_active and pct >= thr["block_pct"]
    if abs_var >= block_abs or block_by_pct:
        return "block", abs_var, pct

    warn_by_pct = pct_rules_active and pct >= thr["warn_pct"]
    if abs_var >= warn_abs or warn_by_pct:
        return "warn", abs_var, pct

    return "none", abs_var, pct


def compute_variance_severity(doc, method=None):
    """validate hook: compute + persist `variance_severity` and auto-route
    block/critical variances into the workflow if not already in one.

    Runs on every save. Idempotent. Short-circuits early when the document
    doesn't have payment_reconciliation populated yet (e.g. autosave with
    bare metadata) -- avoids loading the Sungas Close Policy single doc on
    a no-op save.
    """
    # Fast-fail: nothing to score yet.
    pr_rows = doc.get("payment_reconciliation") or []
    if not pr_rows:
        return
    if not frappe.db.exists("DocType", "Sungas Close Policy"):
        return
    policy = frappe.get_single("Sungas Close Policy")
    total_var, total_expected = _compute_variance(doc)
    severity, _abs_var, _pct = _gross_severity(doc, policy)
    doc.set("variance_severity", severity)
    # Backfill the variance amount so dashboards / list views show real numbers
    # (was previously left at 0). Signed: shortage = negative, overage = positive.
    doc.set("variance_amount", total_var)

    # Stamp signer fields on workflow transitions.
    _stamp_workflow_signers(doc)


def _stamp_workflow_signers(doc) -> None:
    """When workflow_state has just changed, stamp the signer + timestamp on
    the corresponding approval field.

    Detection: compare new workflow_state with the previously saved value.
    Idempotent -- never overwrites an already-stamped field.
    """
    from frappe.utils import now_datetime

    new_state = doc.get("workflow_state")
    if not new_state:
        return

    if doc.is_new():
        old_state = None
    else:
        prev = doc.get_doc_before_save()
        old_state = prev.get("workflow_state") if prev else None

    if old_state == new_state:
        return  # no transition

    # Map: the transition that produces `new_state` was performed by the
    # role that approved the OLD state -- so we stamp the signer that
    # "owns" the OLD state.
    user = frappe.session.user
    ts = now_datetime()
    stamp_map = {
        # When moving from X to Y, stamp X's signer.
        ("Pending Plant Manager", "Pending HOD Operations"):
            ("plant_manager_signed_by", "plant_manager_signed_on"),
        ("Pending HOD Operations", "Approved"):
            ("hod_ops_signed_by", "hod_ops_signed_on"),
        ("Pending HOD Operations", "Pending HOD Finance"):
            ("hod_ops_signed_by", "hod_ops_signed_on"),
        ("Pending HOD Finance", "Approved"):
            ("hod_finance_signed_by", "hod_finance_signed_on"),
        ("Pending HOD Finance", "Pending COO"):
            ("hod_finance_signed_by", "hod_finance_signed_on"),
        ("Pending COO", "Approved"):
            ("coo_signed_by", "coo_signed_on"),
    }
    key = (old_state, new_state)
    if key in stamp_map:
        by_field, on_field = stamp_map[key]
        if not doc.get(by_field):
            doc.set(by_field, user)
            doc.set(on_field, ts)
        # Mirror the latest approver into variance_approved_by so the JE
        # auto-post in on_submit keeps working.
        if new_state == "Approved":
            doc.set("variance_approved_by", user)


def validate_variance(doc, method=None):
    """before_submit hook: enforce variance thresholds.

    For warn-band: just require remarks (Path A).
    For block/critical-band: require the workflow to have reached 'Approved'
    state OR the legacy `variance_approved_by` field to be populated by an
    approver-role user.
    """
    if not frappe.db.exists("DocType", "Sungas Close Policy"):
        return  # policy doctype not installed yet, skip
    policy = frappe.get_single("Sungas Close Policy")
    severity, abs_var, pct = _gross_severity(doc, policy)

    if severity == "none":
        return

    # Remarks check
    remarks = (doc.get("variance_remarks") or "").strip()
    if policy.require_remarks_on_variance and not remarks:
        frappe.throw(
            _("Variance of NGN {0:,.2f} ({1:.2f}%) requires remarks before closing the shift. "
              "Please fill the 'Variance Remarks' field with the explanation and any approvals obtained.").format(
                abs_var, pct
            ),
            title=_("Variance Remarks Required")
        )

    # Block-/Critical-threshold approver check
    if severity in ("block", "critical"):
        # Path 1: workflow has reached Approved -> allow.
        if doc.get("workflow_state") == "Approved":
            return
        # Path 2: legacy single-approver path (for backwards compatibility
        # and admin override) -- variance_approved_by populated AND user
        # holds an approver role.
        approver_roles = policy.get_approver_roles()
        current_user_roles = set(frappe.get_roles(frappe.session.user))
        if current_user_roles.intersection(approver_roles):
            return
        approver = doc.get("variance_approved_by")
        if not approver:
            tier_label = "critical" if severity == "critical" else "block"
            frappe.throw(
                _("Variance of NGN {0:,.2f} ({1:.2f}%) exceeds the {2} threshold and requires "
                  "approval via the sequential workflow (Plant Manager -> HOD Operations"
                  "{3}). Save the draft and have the approvers act on it from "
                  "/app/pos-closing-shift/{4} before re-submitting.").format(
                    abs_var, pct, tier_label,
                    " -> HOD Finance" + (" -> COO" if policy.get("require_coo_on_critical") else "")
                    if severity == "critical" else "",
                    doc.name or "<new>"
                ),
                title=_("Variance Approval Required")
            )
        approver_user_roles = set(frappe.get_roles(approver))
        if not approver_user_roles.intersection(approver_roles):
            frappe.throw(
                _("User {0} does not hold any of the approver roles ({1}). "
                  "Variance cannot be approved.").format(approver, ", ".join(approver_roles)),
                title=_("Invalid Approver")
            )


def _resolve_cash_account(doc):
    """Return the Cash Mode-of-Payment GL account used in this shift, or None."""
    for row in (doc.payment_reconciliation or []):
        mop = row.mode_of_payment or ""
        if "Cash" not in mop:
            continue
        if not flt(row.expected_amount):
            continue
        mop_doc = frappe.get_doc("Mode of Payment", mop)
        for a in mop_doc.accounts:
            if a.company == doc.company:
                return a.default_account
    return None


def _shift_posting_date(doc):
    """Use the shift's own period_end_date so the JE lands in the correct
    accounting period even if approval crosses a month boundary. Falls
    back to today if the date is somehow missing."""
    return doc.get("period_end_date") or frappe.utils.nowdate()


def post_provisional_journal(doc, method=None):
    """on_update hook (Wave D-4 / Option C): post a provisional Suspense JE
    the moment a block/critical variance enters the workflow.

    Effect during investigation window:
        Shortage:  Dr  cash_variance_pending_account
                   Cr  cash_acct                                (party=Employee on Dr)
        Overage:   Dr  cash_acct
                   Cr  cash_variance_pending_account

    Cash GL is reconciled IMMEDIATELY (Day 1); the variance is parked in
    `cash_variance_pending_account` until the workflow approves and the
    reclassification JE moves it to the final suspense (cashier_recovery
    or overage_suspense).

    Idempotent via the `variance_provisional_je` field. Only fires while
    the doc is still Draft (docstatus=0) and in a Pending workflow state.
    """
    if doc.docstatus != 0:
        return  # submitted; provisional window closed
    if doc.get("variance_provisional_je"):
        return  # already posted
    if doc.get("variance_severity") not in ("block", "critical"):
        return  # warn / none don't use provisional path
    state = doc.get("workflow_state") or ""
    if not state.startswith("Pending"):
        return  # not in active workflow yet

    if not frappe.db.exists("DocType", "Sungas Close Policy"):
        return
    policy = frappe.get_single("Sungas Close Policy")
    pending_acct = policy.get("cash_variance_pending_account")
    if not pending_acct:
        frappe.log_error(
            "post_provisional_journal: cash_variance_pending_account not set on Sungas Close Policy",
            "Sungas variance hook",
        )
        return

    total_var, _ = _compute_variance(doc)
    if not _mode_differences(doc):
        return
    employee = frappe.db.get_value("Employee", {"user_id": doc.user}, "name")
    kind = "Variance"

    remark = "\n".join([
        f"Provisional Cash {kind} JE auto-posted by Sungas Close Policy hook.",
        f"POS Closing Shift: {doc.name}  (workflow_state={state})",
        f"Outlet: {doc.pos_profile}    Cashier: {doc.user}",
        "Differences:", *_diff_lines(doc),
        "Reclassification will follow on workflow approval.",
    ])

    try:
        rows = _mode_rows(doc, pending_acct, pending_acct, employee)
        je = frappe.get_doc({
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": doc.company,
            "posting_date": _shift_posting_date(doc),
            "title": f"Provisional Cash {kind} - {doc.name}",
            "user_remark": remark,
            "accounts": rows,
        })
        je.insert(ignore_permissions=True)
        je.submit()
        frappe.db.set_value(
            "POS Closing Shift", doc.name,
            "variance_provisional_je", je.name,
            update_modified=False,
        )
        frappe.db.commit()
    except Exception as e:
        frappe.clear_last_message()
        frappe.log_error(
            f"post_provisional_journal failed for {doc.name}: {e}",
            "Sungas variance hook",
        )


def cancel_provisional_journal(doc, method=None):
    """on_update hook: when the workflow rejects, cancel the provisional JE
    so the books don't carry an orphaned pending entry.

    Triggered on transition into 'Rejected' state. Idempotent: a JE that's
    already cancelled (docstatus=2) is silently skipped.
    """
    if doc.get("workflow_state") != "Rejected":
        return
    je_name = doc.get("variance_provisional_je")
    if not je_name:
        return
    try:
        je = frappe.get_doc("Journal Entry", je_name)
        if je.docstatus == 1:
            je.cancel()
            frappe.db.commit()
    except Exception as e:
        frappe.log_error(
            f"cancel_provisional_journal failed for {doc.name} ({je_name}): {e}",
            "Sungas variance hook",
        )


def post_variance_journal(doc, method=None):
    """on_submit hook: auto-post the final variance JE.

    Two paths:

    1. **Reclassification** (Option C / Wave D-4): if a provisional JE was
       posted during the workflow, post a reclassification JE that moves
       the variance from `cash_variance_pending_account` to either
       `cashier_recovery_account` (shortage) or `overage_suspense_account`
       (overage). The cash account is NOT touched -- that already happened
       on Day 1 via the provisional JE.

    2. **Direct** (legacy / soft+warn paths): if no provisional JE exists,
       behave exactly as the original implementation -- Dr cashier_recovery
       / Cr cash_acct for shortages, Cr overage_suspense / Dr cash_acct for
       overages.
    """
    if not frappe.db.exists("DocType", "Sungas Close Policy"):
        return
    if doc.get("variance_je"):
        return  # already posted (re-submit guard)
    policy = frappe.get_single("Sungas Close Policy")
    total_var, _ = _compute_variance(doc)
    diffs = _mode_differences(doc)
    if not diffs:
        return
    short = sum(-d for _m, d in diffs if d < 0)
    over = sum(d for _m, d in diffs if d > 0)
    employee = frappe.db.get_value("Employee", {"user_id": doc.user}, "name")
    recovery_acct = policy.cashier_recovery_account
    overage_acct = policy.overage_suspense_account
    if (short and not recovery_acct) or (over and not overage_acct):
        frappe.log_error(
            "post_variance_journal: cashier_recovery_account / overage_suspense_account not set on Close Policy",
            "Sungas variance hook",
        )
        return

    provisional_je = doc.get("variance_provisional_je")
    is_reclassification = bool(provisional_je)
    pending_acct = policy.get("cash_variance_pending_account")
    if is_reclassification and not pending_acct:
        frappe.log_error(
            f"post_variance_journal: variance_provisional_je={provisional_je} set "
            f"but cash_variance_pending_account is empty; cannot reclassify.",
            "Sungas variance hook",
        )
        return
    kind = "Variance" if short and over else ("Shortage" if short else "Overage")
    if is_reclassification:
        kind += " Reclassification"

    remark_lines = [
        f"Cash {kind} JE auto-posted by Sungas Close Policy hook.",
        f"POS Closing Shift: {doc.name}",
        f"Outlet: {doc.pos_profile}    Cashier: {doc.user}",
        "Differences:", *_diff_lines(doc),
    ]
    if is_reclassification:
        remark_lines.append(f"Reclassifies provisional JE: {provisional_je}")
    approver = doc.get("variance_approved_by")
    if approver and approver != doc.user:
        remark_lines.append(f"Approved by: {approver}")
    cashier_remarks = (doc.get("variance_remarks") or "").strip()
    if cashier_remarks:
        remark_lines.append(f"Cashier remarks: {cashier_remarks}")
    remark = "\n".join(remark_lines)

    try:
        if is_reclassification:
            rows = []
            if short:
                rows += [_row(recovery_acct, short, 0, employee), _row(pending_acct, 0, short, employee)]
            if over:
                rows += [_row(pending_acct, over, 0, employee), _row(overage_acct, 0, over, employee)]
        else:
            rows = _mode_rows(doc, recovery_acct, overage_acct, employee)
        je = frappe.get_doc({
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": doc.company,
            "posting_date": _shift_posting_date(doc),
            "title": f"Cash {kind} - {doc.name}",
            "user_remark": remark,
            "accounts": rows,
        })
        je.insert(ignore_permissions=True)
        je.submit()
        frappe.db.set_value(
            "POS Closing Shift", doc.name, "variance_je", je.name, update_modified=False
        )
        frappe.db.commit()
    except Exception as e:
        frappe.clear_last_message()
        frappe.log_error(
            title="Sungas variance JE failed",
            message=(
                f"post_variance_journal failed for {doc.name}: {e}\n\n"
                f"{frappe.get_traceback()}"
            ),
        )

