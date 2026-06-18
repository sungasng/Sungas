# Wave D-4 — Provisional Suspense JE on Draft (Option C) + COO Informational Notification

**Status:** Shipped — provisional Suspense JE posts at workflow entry; reclassification on approval; COO notified by email at final approval.

## Why this exists

Before D-4 the variance JE only posted **at workflow approval** (`on_submit`),
which left the Cash GL overstated by the variance amount for the full 1-7 day
investigation window. With ~22k POS invoices/day and multi-day approvals, this
created real month-close cleanup work and made the Trial Balance during the
window inaccurate.

D-4 fixes this by posting two narrowly-scoped JEs:

| Event | JE | Effect |
|-------|----|--------|
| Workflow entry (`on_update` → `Pending Plant Manager`) | **Provisional** | Cash GL reconciled on Day 1. Variance parked in `cash_variance_pending_account`. |
| Approval (`on_submit`) | **Reclassification** | Move variance from `cash_variance_pending_account` → `cashier_recovery_account` (shortage) or `overage_suspense_account` (overage). Cash GL untouched on this leg. |
| Rejection (`on_update` → `Rejected`) | **Cancellation** | Provisional JE cancelled. No orphaned pending entry. |

Both JEs use `posting_date = period_end_date` (shift's own date), so the
variance lands in the **correct accounting month** even when approval crosses
a month boundary.

## Shortage example (NGN 78,240)

Cashier shift `POSA-CS-26-XXXX` opens with a critical shortage at outlet
`POS - Ikeja`, period_end_date = 2026-03-31.

### Day 1 (variance detected, doc saves into `Pending Plant Manager`)
```
Provisional Cash Shortage - POSA-CS-26-XXXX   (posting_date = 2026-03-31)
  Dr  2607 Cash Variance Pending - SCL   (party=Employee)        78,240.00
  Cr  1101 Cash Sales - Ikeja - SCL                                78,240.00
```
Cash GL is back in balance immediately.

### Day 5 (HOD Finance approves; doc submits)
```
Cash Shortage Reclassification - POSA-CS-26-XXXX   (posting_date = 2026-03-31)
  Dr  2608 Cash Suspense - Cashier Recovery - SCL  (party=Employee)  78,240.00
  Cr  2607 Cash Variance Pending - SCL                                78,240.00
```
Variance now sits in the final receivable suspense, ready for cashier recovery.

### Net effect over both JEs
```
Dr  2608 Cash Suspense - Cashier Recovery   78,240.00
Cr  1101 Cash Sales - Ikeja                                       78,240.00
```
Identical to the pre-D-4 single-JE outcome, but distributed across two
auditable events with the correct posting date.

## COO informational notification

The variance approval chain **officially ends at HOD Finance**. The COO is
not a required approver — they receive a single Brevo email the moment a
critical variance reaches `Approved` status:

- Trigger: `on_update` of POS Closing Shift, `workflow_state` → `Approved`,
  `variance_severity == "critical"`.
- Recipients: all enabled users carrying role `LPG Chief Operating Officer`.
- Idempotent via `coo_notified_at` field. Re-saves never re-fire.
- If you want the COO to be an explicit workflow approver instead, enable
  `require_coo_on_critical` on Sungas Close Policy — the `Pending COO`
  workflow state is still defined and ready.

## New custom fields installed

On **POS Closing Shift** (all read-only, all `permlevel=1`):
- `variance_provisional_je` (Link → Journal Entry)
- `coo_notified_at` (Datetime, hidden)

On **Sungas Close Policy**:
- `cash_variance_pending_account` (Link → Account)

Plus `variance_amount` is now stamped automatically in `validate`, so list
view and dashboards finally show real numbers.

## One-time configuration on the bench

```bash
bench --site sungasmis.v.frappe.cloud migrate
```

Then in `bench --site sungasmis.v.frappe.cloud console`:

```python
import frappe

# 1) Create or pick the suspense account.
#    Recommended: a NEW Current Asset under your Receivables hierarchy.
acct = frappe.get_doc({
    "doctype": "Account",
    "account_name": "Cash Variance Pending",
    "parent_account": "Current Assets - SCL",   # adjust to your CoA
    "account_type": "Receivable",
    "company": "Sungas Comprehensive Limited",  # adjust to your company name
    "is_group": 0,
    "root_type": "Asset",
}).insert(ignore_permissions=True)
print("Created:", acct.name)

# 2) Wire it into the policy.
policy = frappe.get_single("Sungas Close Policy")
policy.cash_variance_pending_account = acct.name
policy.save(ignore_permissions=True)
frappe.db.commit()
print("Policy updated:", policy.cash_variance_pending_account)
```

## Verification snippet (paste in `bench console` after the next critical variance flows through)

```python
import frappe, json

# Pick a recent shift that went through the workflow on a critical variance.
cs = frappe.get_doc("POS Closing Shift", "<your shift>")
print(json.dumps({
    "docstatus": cs.docstatus,
    "workflow_state": cs.workflow_state,
    "variance_severity": cs.variance_severity,
    "variance_amount": float(cs.variance_amount or 0),
    "variance_provisional_je": cs.variance_provisional_je,
    "variance_je": cs.variance_je,
    "coo_notified_at": str(cs.get("coo_notified_at")),
}, indent=2, default=str))

# Inspect both JEs.
for je_name in (cs.variance_provisional_je, cs.variance_je):
    if not je_name:
        continue
    je = frappe.get_doc("Journal Entry", je_name)
    print(f"\n--- {je.name}  docstatus={je.docstatus}  posting_date={je.posting_date} ---")
    for a in je.accounts:
        print(f"  {a.account:55s}  Dr={a.debit_in_account_currency:>12.2f}  Cr={a.credit_in_account_currency:>12.2f}")
```

## Backward compatibility

- **Already-submitted shifts** (e.g. `POSA-CS-26-0000012`) are untouched —
  they have `variance_je` populated and no `variance_provisional_je`, so the
  reclassification path is never invoked.
- **Soft / warn shifts** still post a single direct JE on submit (no
  provisional needed). The new code only kicks in for `block` and `critical`.
- **Shifts currently in Pending states** when D-4 deploys will post their
  provisional JE on the next save (the `on_update` hook fires). If you want
  the provisional JE to use today's date for those, fine — but if you'd
  rather they backdate to `period_end_date`, that already happens by design.
