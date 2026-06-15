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
    severity, _abs_var, _pct = _variance_severity(total_var, total_expected, policy)
    doc.set("variance_severity", severity)

    # Auto-route into the workflow when block/critical and not yet in one.
    if severity in ("block", "critical"):
        current_state = doc.get("workflow_state")
        if not current_state or current_state in ("", "Draft"):
            doc.set("workflow_state", "Pending Plant Manager")
    else:
        # Warn / none: keep workflow_state in Draft (Path A).
        if not doc.get("workflow_state"):
            doc.set("workflow_state", "Draft")

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
    total_var, total_expected = _compute_variance(doc)
    severity, abs_var, pct = _variance_severity(total_var, total_expected, policy)

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


def post_variance_journal(doc, method=None):
    """on_submit hook: auto-post variance JE."""
    if not frappe.db.exists("DocType", "Sungas Close Policy"):
        return
    if doc.get("variance_je"):
        # Already posted (re-submit guard / idempotency)
        return
    policy = frappe.get_single("Sungas Close Policy")
    total_var, _ = _compute_variance(doc)
    if abs(total_var) < 0.01:
        return  # zero variance, nothing to post

    # Resolve Cash Sales account from the Cash MoP row used in this shift
    cash_acct = None
    for row in (doc.payment_reconciliation or []):
        mop = row.mode_of_payment or ""
        if "Cash" not in mop:
            continue
        if not flt(row.expected_amount):
            continue
        mop_doc = frappe.get_doc("Mode of Payment", mop)
        for a in mop_doc.accounts:
            if a.company == doc.company:
                cash_acct = a.default_account
                break
        if cash_acct:
            break
    if not cash_acct:
        frappe.log_error(
            f"post_variance_journal: no Cash MoP account resolved for "
            f"POS Closing Shift {doc.name} (company={doc.company})",
            "Sungas variance hook"
        )
        return

    abs_var = abs(total_var)
    employee = frappe.db.get_value("Employee", {"user_id": doc.user}, "name")
    recovery_acct = policy.cashier_recovery_account
    overage_acct = policy.overage_suspense_account
    if total_var < 0 and not recovery_acct:
        frappe.log_error(
            "post_variance_journal: cashier_recovery_account not set on Close Policy",
            "Sungas variance hook"
        )
        return
    if total_var > 0 and not overage_acct:
        frappe.log_error(
            "post_variance_journal: overage_suspense_account not set on Close Policy",
            "Sungas variance hook"
        )
        return

    if total_var < 0:
        kind = "Shortage"
        row_first = {
            "account": recovery_acct,
            "debit_in_account_currency": abs_var,
            "credit_in_account_currency": 0,
        }
        if employee:
            row_first["party_type"] = "Employee"
            row_first["party"] = employee
        rows = [row_first, {
            "account": cash_acct,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": abs_var,
        }]
    else:
        kind = "Overage"
        rows = [
            {
                "account": cash_acct,
                "debit_in_account_currency": abs_var,
                "credit_in_account_currency": 0,
            },
            {
                "account": overage_acct,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": abs_var,
            },
        ]

    remark_lines = [
        f"Cash {kind} JE auto-posted by Sungas Close Policy hook.",
        f"POS Closing Shift: {doc.name}",
        f"Outlet: {doc.pos_profile}    Cashier: {doc.user}",
        f"Variance: NGN {total_var:+,.2f}",
    ]
    approver = doc.get("variance_approved_by")
    if approver and approver != doc.user:
        remark_lines.append(f"Approved by: {approver}")
    cashier_remarks = (doc.get("variance_remarks") or "").strip()
    if cashier_remarks:
        remark_lines.append(f"Cashier remarks: {cashier_remarks}")
    remark = "\n".join(remark_lines)

    try:
        je = frappe.get_doc({
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": doc.company,
            "posting_date": frappe.utils.nowdate(),
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
        frappe.log_error(
            f"post_variance_journal failed for {doc.name}: {e}",
            "Sungas variance hook"
        )
