"""Patch v1 — Seed cash_variance_pending_account for Wave D-4.

Creates an Account named **"Cash Variance Pending"** under the same parent
hierarchy and company as the existing `cashier_recovery_account` from
`Sungas Close Policy`, then wires the new account onto the policy.

Why introspect cashier_recovery_account?
    It's already in use, it's already linked to the right Company in the
    right Receivable subtree, and it survives a fresh CoA import. By
    mirroring its parent_account + company we automatically inherit
    whatever CoA conventions Bobo Gas / Sungas have adopted (suffix,
    parent group, etc.) without hard-coding company-specific strings.

Idempotent across all branches:
    * If policy already has `cash_variance_pending_account` set -> skip.
    * If an Account named "Cash Variance Pending - <abbr>" already exists
      for the company -> reuse it.
    * If cashier_recovery_account isn't set yet -> log + skip (the patch
      will be safe to re-run after the admin configures recovery account).

Manual invocation::

    bench --site <site> execute sungas.patches.v1.seed_cash_variance_pending_account.execute
"""

from __future__ import annotations

import frappe  # type: ignore


NEW_ACCOUNT_NAME = "Cash Variance Pending"


def execute() -> dict[str, object]:
    if not frappe.db.exists("DocType", "Sungas Close Policy"):
        return {"status": "skipped", "reason": "Sungas Close Policy doctype absent"}

    policy = frappe.get_single("Sungas Close Policy")

    if policy.get("cash_variance_pending_account"):
        return {
            "status": "ok",
            "reason": "policy already configured",
            "account": policy.cash_variance_pending_account,
        }

    recovery_acct_name = policy.get("cashier_recovery_account")
    if not recovery_acct_name:
        msg = (
            "seed_cash_variance_pending_account: cashier_recovery_account is "
            "not configured on Sungas Close Policy. Set it first, then re-run "
            "this patch via `bench execute "
            "sungas.patches.v1.seed_cash_variance_pending_account.execute`."
        )
        frappe.log_error(msg, "Sungas D-4 seed")
        return {"status": "aborted", "reason": "recovery_acct_missing"}

    try:
        recovery = frappe.get_doc("Account", recovery_acct_name)
    except frappe.DoesNotExistError:
        frappe.log_error(
            f"cashier_recovery_account references missing Account {recovery_acct_name}",
            "Sungas D-4 seed",
        )
        return {"status": "aborted", "reason": "recovery_acct_doc_missing"}

    company = recovery.company
    parent = recovery.parent_account  # mirror the same parent group
    if not parent:
        frappe.log_error(
            f"recovery account {recovery.name} has no parent_account — cannot mirror.",
            "Sungas D-4 seed",
        )
        return {"status": "aborted", "reason": "recovery_acct_has_no_parent"}

    abbr = frappe.db.get_value("Company", company, "abbr") or ""
    # Frappe convention: leaf account names are stored as "<name> - <abbr>".
    target_name = f"{NEW_ACCOUNT_NAME} - {abbr}" if abbr else NEW_ACCOUNT_NAME

    if frappe.db.exists("Account", target_name):
        new_acct_name = target_name
    else:
        new_acct = frappe.get_doc({
            "doctype": "Account",
            "account_name": NEW_ACCOUNT_NAME,
            "parent_account": parent,
            "company": company,
            "is_group": 0,
            # Mirror the recovery account's posture so the GL is consistent.
            "account_type": recovery.get("account_type") or "Receivable",
            "root_type": recovery.get("root_type") or "Asset",
            "report_type": recovery.get("report_type") or "Balance Sheet",
            "account_currency": recovery.get("account_currency"),
        })
        new_acct.insert(ignore_permissions=True)
        new_acct_name = new_acct.name

    policy.cash_variance_pending_account = new_acct_name
    policy.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "ok",
        "account": new_acct_name,
        "parent_account": parent,
        "company": company,
        "mirrored_from": recovery.name,
    }
