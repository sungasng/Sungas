# Sungas ERPNext Operations Manual

> **Version:** v1.0 — June 2026
> **Audience:** Cashiers, Outlet Managers, Approvers (HOD Ops / HOD Finance / Plant Managers), Accountants, System Administrators.
> **Scope:** Daily operations, variance handling, FIRS receipt compliance, role-based access. Covers everything live in production as of the date above.

---

## 1. Roles & What They Can Do

| Role | Outlet Scope | POS | Closing Shift | Approve Variance | Notes |
|---|---|---|---|---|---|
| **LPG POS User** (Cashier) | Own outlet only | Sell, open shift, attempt close | Can edit own draft; can submit only if variance is below block threshold OR an approver has signed off | ❌ | E.g. Peace @ Ikeja |
| **LPG Plant Manager** | Own outlet only | View own outlet | Can review draft (Wave D will gate this formally) | ❌ (Wave D will add: first signoff for hard variance) | 21 users currently |
| **LPG Head of Operations** | All outlets | Read across | Approve hard-variance shifts | ✅ | E.g. Femi |
| **LPG Head of Finance** | All outlets | Read across | Approve hard-variance shifts | ✅ | 3 users |
| **LPG Head of Sales** | All outlets | Read across | View only | ❌ | |
| **Accounts Manager** | All outlets | — | Approve + create/cancel | ✅ | |
| **System Manager** | All | All | Anything | ✅ | Emergency override |

> **Outlet scoping** is enforced via `permission_query_conditions` + a `has_permission` hook on POS Opening Shift, POS Closing Shift, POS Invoice, and Sales Invoice. The hook resolves a cashier's outlet from User Permissions; if none are set, it falls back to the `POS Profile User` child table assignments. Owners of a document always retain access to it (so a cashier never loses access to her own shift).

---

## 2. Cashier Daily Operations

### 2.1 Opening a Shift

1. Log into POS Awesome at `https://sungasmis.v.frappe.cloud/posawesome`.
2. Select your POS Profile (e.g. `POS - Ikeja`). You will only see profiles you are assigned to.
3. Enter opening cash → **Submit Opening Voucher**.
4. Begin selling.

### 2.2 Selling (Cash, POS, Transfer, Partial Payments)

- Add items, set quantities, choose customer.
- **Partial payments (split tender) are enabled** across all 22 POS profiles. You can split a single invoice across Cash + POS + Transfer in any combination.
- Submit invoice. A FIRS-compliant receipt is generated.

### 2.3 Closing a Shift

1. Click **Close Shift**.
2. Enter the closing cash, POS, and transfer amounts as counted.
3. Fill **Variance Remarks** if you observe any difference between expected and counted. **Remarks are required** if your variance is at warn level or higher (≥ ₦5,000 for shortages, ≥ ₦10,000 for overages by default).
4. Click **Submit Closing Shift**.

**What happens depending on the variance size** (defaults; thresholds are configurable in *Sungas Close Policy*):

| Variance Band | Shortage Trigger | Overage Trigger | What happens |
|---|---|---|---|
| **None** | < ₦5,000 | < ₦10,000 | Shift submits, no remarks required |
| **Warn (soft)** | ₦5,000 – ₦49,999 | ₦10,000 – ₦99,999 | Shift submits with **mandatory remarks**. Variance JE auto-posted |
| **Block (hard)** | ≥ ₦50,000 OR ≥ 2 % when shift ≥ ₦500,000 | ≥ ₦100,000 OR ≥ 2 % when shift ≥ ₦500,000 | Submit is **blocked**. Draft is saved, awaiting approver. See §3 |

> The percentage rules only kick in for shifts whose expected total is ≥ ₦500,000 (the `block_pct_min_expected` floor). This prevents tiny shifts from getting blocked over a 4 % variance that is immaterial in absolute terms.

### 2.4 Continuing to Sell After a Blocked Close

If the close was blocked at the hard band, **the opening shift remains open**. You can keep selling on it; the dispute sits in the background as a draft. Once an approver signs off, you (or anyone with submit rights) can re-submit the draft to close the shift.

---

## 3. Hard-Variance Approval Workflow (Path B)

This is the workflow you saw in the spec — it kicks in whenever variance crosses the block threshold.

### 3.1 What the cashier sees

When submit is blocked, two messages appear in sequence:

1. **Block message:** *"Variance of NGN X,XXX.XX exceeds the block threshold and requires approval from one of: LPG Head of Operations, Accounts Manager, LPG Head of Finance, System Manager."*
2. **Draft confirmation:** *"Draft POSA-CS-26-XXXXXX has been saved and is awaiting approval. Once an approver fills the 'Variance Approved By' field via Desk, you (or a manager) can submit it from /app/pos-closing-shift/POSA-CS-26-XXXXXX."*

The opening shift stays open; the cashier resumes sales.

### 3.2 What the approver does

> **Approver = anyone holding `LPG Head of Operations`, `LPG Head of Finance`, `Accounts Manager`, or `System Manager`.** (Wave D will tighten this to sequential routing.)

1. Open the Desk URL: `https://sungasmis.v.frappe.cloud/app/pos-closing-shift?docstatus=0`. You will see all pending drafts.
2. Click the relevant draft.
3. Review the variance + cashier's remarks at the top (orange banner shows the variance amount and direction).
4. In the **Variance Approved By** field, pick a user — the dropdown is **filtered to approver-role users only**. Pick yourself (or the user delegated to approve).
5. Optionally add a follow-up note in **Variance Remarks**.
6. Press **Ctrl+S** to save. **Do NOT click Submit.**

### 3.3 Closing the shift after approval

Either the cashier or any user with submit rights:

- **Path A (cashier re-submits via POS Awesome):** Click Close Shift again. The dialog is fresh, but our override detects the existing draft for the same opening shift and updates it with the new totals before re-attempting submit. Because the approver is now set, the block lifts and the close proceeds.
- **Path B (admin submits via Desk):** Open `/app/pos-closing-shift/POSA-CS-26-XXXXXX` and click **Submit** at the top right.

When the submit succeeds, `on_submit` fires `post_variance_journal`, which auto-creates a Journal Entry (see §4).

---

## 4. Variance Journal Entries (Auto-Posted)

Whenever a closing shift submits with non-zero variance, a Journal Entry is automatically posted with the following structure:

### 4.1 Shortage (cash short)

| Account | Dr | Cr | Party |
|---|---|---|---|
| **Cashier Recovery (e.g. 2608)** | abs(variance) | — | Employee = cashier's Employee record |
| Cash – \<Outlet\> – SCL | — | abs(variance) | — |

The party tag means the unrecovered cash is tracked against the specific cashier and can be deducted from payroll (or formally written off) by HR.

### 4.2 Overage (cash over)

| Account | Dr | Cr | Party |
|---|---|---|---|
| Cash – \<Outlet\> – SCL | abs(variance) | — | — |
| **Overage Suspense (e.g. 6224)** | — | abs(variance) | — |

### 4.3 JE Remark

Every auto-posted JE includes a full audit trail in `user_remark`:

```
Cash Shortage JE auto-posted by Sungas Close Policy hook.
POS Closing Shift: POSA-CS-26-0000011
Outlet: POS - Ikeja    Cashier: peace.effiong@sungas.org
Variance: NGN -69,000.00
Approved by: femi.lee@sungas.org
Cashier remarks: missing cash
```

The JE name is back-linked to the Closing Shift via the read-only `variance_je` field, so the auditor can pivot either direction.

### 4.4 Configuration

The accounts and policy are stored on the **Sungas Close Policy** single doctype:

- Navigate to `/app/sungas-close-policy`.
- Set `cashier_recovery_account` and `overage_suspense_account` (per-company defaults — currently mapped to SCL).
- Set `approver_roles` (one role per line).
- Tune thresholds (`warn_abs`, `block_abs`, `warn_abs_overage`, `block_abs_overage`, `warn_pct`, `block_pct`, `block_pct_min_expected`).
- Toggle `require_remarks_on_variance` (default ON).

> **Only System Managers should edit this doctype.** It is the single source of truth for all variance enforcement.

---

## 5. FIRS-Compliant Receipts

### 5.1 What's printed

Every POS receipt produced from POS Awesome includes:

1. The mandatory **`RECEIPT`** label above the invoice number (FIRS requirement).
2. **Company TIN** (printed once, in the header).
3. A dedicated **0 % VAT** tax line, rendered explicitly even when the amount is ₦0.00. This is a FIRS-2025 requirement: zero-rated supplies must show the tax line, not omit it.
4. Items list with quantities and totals.
5. Mode-of-payment breakdown with partial-payment support.
6. Cashier and outlet at the footer.

### 5.2 Brand overrides

| Outlet | Brand | TIN | Notes |
|---|---|---|---|
| All Sungas LPG outlets (Ikeja, Ebute, Lekki, etc.) | **Sungas** logo + HQ address | SCL TIN | Default print format |
| **Itele** | **Bobo Gas** wordmark, no Sungas logo, Itele address | Bobo Gas TIN | Custom print format override applied automatically when POS Profile = Itele |

### 5.3 0 % VAT Item Tax Templates

The following Item Group hierarchies have a 0 % VAT Item Tax Template attached (so the FIRS line renders correctly):

- LPG Cylinder (Empty)
- LPG Cylinder (Filled)
- LPG Gas (Bulk)
- LPG Accessories

The same template is attached to all POS Profiles via the `taxes` child table, so it applies automatically to all POS invoices.

> If you add a **new** LPG-related Item Group, attach the existing 0 % VAT Item Tax Template manually (or re-run the `attach_zero_vat_tax_templates.py` script).

---

## 6. Outlet Scoping (Who Sees What)

### 6.1 Cashiers

A cashier (LPG POS User) sees, in any list view (POS Opening Shift, POS Closing Shift, POS Invoice, Sales Invoice):

- Only documents whose POS Profile matches one of their assigned profiles.
- Documents they themselves authored (owner-bypass), even if profile isn't in their scope.

Scope is resolved in this order:

1. Explicit **User Permission** rows (`allow = POS Profile`).
2. Implicit via **POS Profile User** child table (if no explicit User Permission exists). This safety net prevents fail-closed denials for cashiers whose User Permission rows were never seeded.

### 6.2 Cross-outlet roles (exempt from scoping)

The following roles see ALL outlets:

- System Manager
- Accounts Manager
- LPG Head of Operations
- LPG Head of Sales
- LPG Head of Finance
- HR Manager
- POS Manager / Sales Manager / Auditor

### 6.3 Adding a new cashier to an outlet

1. Create the User in Desk.
2. Assign the role **LPG POS User**.
3. Open the relevant POS Profile (e.g. `POS - Ikeja`) → **Applicable Users** child table → add the user.
4. (Recommended) Also seed an explicit User Permission row: User Permission → New → user=…, allow=POS Profile, for_value=POS - Ikeja, apply_to_all_doctypes=1.
5. User logs out and back in.

> Steps 3 and 4 are belt-and-braces. Either alone is sufficient under current scoping; both together is the cleanest setup.

---

## 7. Configuration Reference

### 7.1 Sungas Close Policy (Single)

`/app/sungas-close-policy`

| Field | Default | Purpose |
|---|---|---|
| `warn_abs` | 5,000 | Shortage warn threshold (NGN) |
| `block_abs` | 50,000 | Shortage block threshold (NGN) |
| `warn_abs_overage` | 10,000 | Overage warn threshold (NGN) |
| `block_abs_overage` | 100,000 | Overage block threshold (NGN) |
| `warn_pct` | 0.5 % | Soft variance pct |
| `block_pct` | 2 % | Hard variance pct |
| `block_pct_min_expected` | 500,000 | Min shift size before pct rules apply |
| `require_remarks_on_variance` | ON | Force remarks at warn band+ |
| `approver_roles` | LPG Head of Operations, Accounts Manager, LPG Head of Finance, System Manager | Who can unblock |
| `cashier_recovery_account` | 2608 | Where shortages debit |
| `overage_suspense_account` | 6224 | Where overages credit |

### 7.2 Custom DocPerm rows (POS Closing Shift)

| Role | permlevel | Read | Write | Create | Submit |
|---|---|---|---|---|---|
| LPG Head of Operations | 0 | ✅ | ✅ | ❌ | ❌ |
| LPG Head of Operations | 1 | ✅ | ✅ | ❌ | ❌ |

Permlevel-1 wraps the `variance_approved_by` and `variance_je` fields so only approvers can edit/clear them.

### 7.3 Custom fields on POS Closing Shift

| Field | Type | Permlevel | Purpose |
|---|---|---|---|
| `variance_remarks` | Long Text | 0 | Cashier's explanation |
| `variance_approved_by` | Link (User) | 1 | Set by approver |
| `variance_je` | Link (Journal Entry) | 1 | Back-link to auto-posted JE |

---

## 8. Troubleshooting

### 8.1 Cashier sees "Not allowed via controller permission check"

**Cause:** Their POS Profile assignment is missing from both User Permission and POS Profile User child table.

**Fix:** Add them to the POS Profile's **Applicable Users** table. After the next page load (or logout/login), they have access via the implicit-scope fallback.

### 8.2 Cashier submits a shift with variance but no JE was posted

**Cause 1:** `cashier_recovery_account` (or `overage_suspense_account`) isn't set on Sungas Close Policy for the company in question.

**Fix:** Set it. Then either re-trigger submission or post the JE manually (one-off).

**Cause 2:** The Cash MoP on the POS Profile has no default account for the company.

**Fix:** Open Mode of Payment → Cash → Accounts table → ensure a row exists for the company with the right Cash GL account.

### 8.3 Approver dropdown shows all users (not just approver-role users)

**Cause:** Client script didn't load (browser cache).

**Fix:** Hard refresh (Ctrl+Shift+R). If still wrong, check `sungas/public/js/pos_closing_shift.js` is deployed.

### 8.4 Draft disappeared after a blocked submit

**Cause:** Custom `submit_closing_shift` override isn't being called — Frappe is hitting the upstream POS Awesome endpoint directly.

**Fix:** Verify `hooks.py` contains:
```python
override_whitelisted_methods = {
    "posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift.submit_closing_shift":
        "sungas.overrides.pos_closing_shift_api.submit_closing_shift",
}
```
Then `bench restart` and try again.

---

## 9. Known Gaps vs. Full Spec (Build Roadmap)

The following items from the agreed operations protocol are **not yet implemented** and are tracked for upcoming waves:

### Wave D (next sprint)
- **D-1: Sequential workflow doctype** for POS Closing Shift: Draft → Plant Manager → HOD Ops (Hard) → HOD Finance (Critical / Path B) → Submitted, with optional COO sign-off.
- **D-2: Open Shift Age escalation scheduler** — Brevo emails at 24h (cashier + Outlet Manager), 48h (HOD Ops + HOD Finance, with audit comment on shift doc), 7d (MD + Internal Audit, suspend shift creation on profile).
- **D-3: 48h SLA timer** from variance detection — auto-escalate to Path C investigation track if HOD Finance hasn't acted.
- **D-4: Outlet Manager signature field** on Path A (soft variance), and **COO sign-off field** at the top of the approval chain.
- **D-5: Annex T-07 worksheet doctype** — structured variance documentation (replaces free-text `variance_remarks` for hard variances).

### Wave E (Path C — Suspected Fraud)
- HOD Finance freezes Outlet Bank Deposit privilege (flag on outlet record).
- HR removes cashier POS access automatically.
- COO email ping within 4h.
- Internal Audit case auto-opened.

### Phase 5.8 / 5.9 (Continuity)
- **POS - Backup profile per region** (B.2 fallback selling channel).
- **Manual Sales Book doctype** with pre-numbered serial entries (B.3 last-resort selling channel).

### Phase 9 (Period Close)
- **Month Close Pack workflow**: Draft → HOD Finance → Head of Internal Control (review) → COO (approved) → Locked.

### Other
- **Stock Recon Unit Variance** routing → HOD Operations + HOD Finance approval gate (separate doctype customization).
- **Customer Facing Screen** (dual-screen display for POS Awesome).

---

## 10. Quick Reference — URLs

| Purpose | URL |
|---|---|
| POS Awesome (cashier UI) | `/posawesome` |
| Pending closing shifts (approvers) | `/app/pos-closing-shift?docstatus=0` |
| Close Policy configuration | `/app/sungas-close-policy` |
| Recently posted variance JEs | `/app/journal-entry?title=%25Cash%20Sho%25` |
| User Permissions (scoping admin) | `/app/user-permission` |
| Role list | `/app/role` |

---

## 11. Support & Escalation

- **POS / variance issues:** Contact your Plant Manager first. If unresolved within 4 hours, escalate to HOD Ops (Femi).
- **Account / ledger issues:** HOD Finance.
- **System / config issues:** System Administrator.
- **Suspected fraud:** Follow Path C protocol — COO must be informed within 4 hours.

---

*End of Manual v1.0. Generated automatically from the current Sungas deployment state. Next revision will land with Wave D (sequential workflow + escalation scheduler).*
