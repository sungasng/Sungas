# Sungas ERPNext — Consolidated Roadmap

> **Last updated:** June 2026
> **Status:** Single source of truth for all in-flight, planned, and backlog initiatives. Supersedes scattered references in the User Manual, PRD, and handoff notes.

---

## Legend

| Symbol | Meaning |
|---|---|
| ✅ | Live in production (tested) |
| 🚧 | In progress / partially shipped |
| 🔴 | P0 — next sprint, blocks core ops or finance close |
| 🟠 | P1 — next 1-2 sprints, material ops improvement |
| 🟡 | P2 — important but not blocking |
| 🟢 | P3 — nice-to-have / future |
| 📦 | Backlog — scope captured, not yet scheduled |

---

## 1. Wave Summary (one line each)

| Wave | Title | State | Items |
|---|---|---|---|
| **A** | Engagement App foundation | 🚧 Partial (v1.0 shipped) | 1 (v1.1 expansion) |
| **C** | POS Closing Variance & FIRS Compliance | ✅ DONE | — |
| **D** | POS Closing Workflow + Ops Routing | 🔴 NEXT | 8 items (D-1 … D-8) |
| **E** | Path C Fraud Protocol | 🟠 PLANNED | 4 items |
| **5.7** | POS Awesome Hardening | ✅ DONE | — |
| **5.8** | POS Backup Profiles (Continuity B.2) | 🟡 PLANNED | 1 item |
| **5.9** | Manual Sales Book (Continuity B.3) | 🟡 PLANNED | 1 item |
| **6** | HRMS + Nigeria Payroll Cutover | 🔴 ACTIVE | Run May 2026 payroll parallel |
| **9** | Month Close Pack Workflow | 🟢 PLANNED | 1 item |

---

## 2. ✅ Completed (this session + prior)

### Wave C — POS Closing Variance & FIRS Compliance (LIVE & TESTED)

- ✅ **C-1** Variance Remarks textarea unconditionally surfaced in POS Awesome Closing Dialog (Vue patch + manual Vite rebuild).
- ✅ **C-2** Desk-side lockdown — `variance_approved_by` + `variance_je` walled off at permlevel 1.
- ✅ **C-3** Asymmetric variance thresholds (shortage ₦50k, overage ₦100k) with percentage rules gated by `block_pct_min_expected = ₦500k`.
- ✅ **C-4** `Sungas Close Policy` single doctype: thresholds, approver roles, recovery + overage accounts, require-remarks flag.
- ✅ **C-5** `before_submit` variance enforcement (block, warn, require remarks).
- ✅ **C-6** `on_submit` auto-post variance JE: shortage → Cashier Recovery (party=Employee) / Cash; overage → Cash / Overage Suspense.
- ✅ **C-7** Draft persistence: `submit_closing_shift` override commits before submit so the variance block leaves an actionable draft for the approver.
- ✅ **C-8** Idempotent submit: re-submission reuses the existing draft for the same opening shift rather than creating a duplicate.
- ✅ **C-9** Custom DocPerm: `LPG Head of Operations` granted level-0 read/write so approvers can open drafts.
- ✅ **C-10** Variance Approved By link filter — dropdown only shows users with approver roles (read from policy).
- ✅ **C-11** Approver-side dashboard banner on draft shifts with variance.
- ✅ **C-12** Partial payments / split tender enabled across all 22 POS profiles.

### Phase 5.7 — POS Awesome Hardening (DONE)

- ✅ Outlet scoping via `permission_query_conditions` on POS Opening Shift, POS Closing Shift, POS Invoice, Sales Invoice.
- ✅ Implicit-scope fallback via `POS Profile User` child table (no more fail-closed denials for unseeded cashiers).
- ✅ Owner-bypass on `has_permission` — users always retain access to docs they authored.
- ✅ FIRS compliance: `RECEIPT` label, company TIN, 0 % VAT explicit line on print formats.
- ✅ Bobo Gas (Itele) brand override — separate TIN, no Sungas logo, Itele address.
- ✅ 0 % VAT Item Tax Templates seeded for LPG Item Groups + attached to all POS Profiles.
- ✅ Cashier scoping script (`p57_scope_cashiers_to_outlets.py`) — seeds User Permission rows for POS Profile / Cost Center / Warehouse / Branch.

### Pricing (Pre-existing, live)

- ✅ LPG Outlet Price Tier engine: (Item × Customer Group × Territory × Qty Window).
- ✅ LPG Price Change Request (PCR) workflow: Draft → Pending Head of Sales → Pending Head of Finance → Approved → auto-upsert tier.
- ✅ Bulk seed script (`seed_all_lpg_tier_rates.py`) for initial price matrix load.

### Wave A v1.0 (Engagement App Foundation)

- ✅ Initial scaffolding (per handoff note — details in PRD.md).

### Documentation

- ✅ Operations Manual v1.1 (DOCX + Markdown shipped at `/docs/`).

---

## 3. 🔴 Wave D — POS Closing Workflow + Ops Routing (NEXT)

Driven by the full Variance / Stock-Adjustment spec the user shared (Paths A / B / C, Open Shift Age, Stock Recon).

| # | Item | Priority | Description | Dependencies |
|---|---|---|---|---|
| **D-1** | Sequential Workflow doctype for POS Closing Shift | 🔴 P0 | Replace today's flat "any approver unblocks" with: **Draft → Plant Manager → HOD Ops (if Hard) → HOD Finance (if Critical / Path B) → Submitted [+ optional COO sign-off]**. Includes severity tiers (Soft / Hard / Critical). | C-7 (draft persistence — done) |
| **D-2** | Open Shift Age Escalation Scheduler | 🔴 P0 | Brevo emails at **24h** (cashier + Outlet Manager), **48h** (HOD Ops + HOD Finance + comment posted on shift doc), **7d** (MD + Internal Audit + suspend new opening shifts on that profile). | Brevo integration (new) |
| **D-3** | 48h SLA Timer (Variance Approval) | 🟠 P1 | Auto-escalate to Path C investigation track if HOD Finance hasn't acted within 48h of variance detection. | D-2 (scheduler infra) |
| **D-4** | Outlet Manager Signature (Path A) + COO Sign-off (Path B) | 🟠 P1 | Two new fields on POS Closing Shift: `outlet_manager_signed_by` (required at warn band) + `coo_signed_by` (optional at block band). | D-1 |
| **D-5** | Annex T-07 Worksheet doctype | 🟠 P1 | Structured variance documentation (count-by-denomination, cause taxonomy, photo evidence). Replaces free-text `variance_remarks` for hard variances. | — |
| **D-6** | Returns / Refund Approval Gate (POS Awesome) | 🟠 P1 | Manager PIN required for refunds above configurable threshold (default ₦20k). Currently any cashier can refund. | Vue rebuild |
| **D-7** | Inventory Routing — Purchase / Transfer / GIT | 🟠 P1 | Sungas-specific approval gates: **Purchase Receipt** with PO-variance flag → HOD Ops if > 5 % shortfall. **Material Transfer** above qty/value threshold → Plant Manager + HOD Ops. **GIT (In-Transit)** with 48h audit flag on any region's In-Transit warehouse. | New In-Transit warehouses (setup) |
| **D-8** | Stock Adjustment Routing | 🟠 P1 | Tiered approval on Stock Reconciliation + Stock Entry (Material Issue): Plant + Outlet Mgr (small variance) → HOD Ops + HOD Finance (medium) → COO (critical). Photo evidence required for damage. | — |
| **D-9** | Sales Register report filtered by `tax_id` | 🟡 P2 | Enables Rev360 export support for FIRS. | — |

**Cross-cutting infra needed for Wave D:**

- **Brevo email integration** (used by D-2, D-3, D-4 escalation notifications, D-7 GIT alerts). Must be done before D-2 ships.
- **Workflow doctype JSON** for severity routing (D-1, D-7, D-8 all use the same pattern — Frappe's native Workflow).

---

## 4. 🟠 Wave E — Path C Fraud Protocol

| # | Item | Priority | Description |
|---|---|---|---|
| **E-1** | Outlet Bank Deposit Freeze flag | 🟠 P1 | HOD Finance can toggle a freeze on the outlet record; downstream cash deposit submissions are blocked while flag is on. |
| **E-2** | Cashier POS Access auto-disable | 🟠 P1 | HR action: revoke all POS Profile assignments + disable user login. Tied to a Workflow State transition. |
| **E-3** | COO 4h Notification | 🟠 P1 | Brevo SMS + email to COO within 4 hours of fraud-flag toggle. |
| **E-4** | Internal Audit Case auto-open | 🟠 P1 | Creates a "Fraud Investigation" doctype record linked to the closing shift, with HR + Internal Audit + COO as watchers. |

**Trigger:** Any approver can flag a shift as "Suspected Fraud" during Wave D approval workflow → Wave E protocol fires automatically.

---

## 5. 🟡 Continuity Layer (Phase 5.8 / 5.9)

| # | Item | Priority | Description |
|---|---|---|---|
| **5.8-1** | POS Backup Profile per region | 🟡 P2 | One shared backup POS Profile per region (e.g. `POS - Backup - Lagos`). Points to the same warehouse; sales continue cleanly with separate ledger trail. Used when an outlet's primary profile is sealed (Path B fallback B.2). |
| **5.9-1** | Manual Sales Book doctype | 🟡 P2 | Pre-numbered triplicate receipts (paper). New doctype `Manual Sales Book Entry` with serial number, customer, items, amount. Batch-keyed within 24h, dated correctly. Audit-friendly because of pre-numbered serials (Path B fallback B.3). |

---

## 6. 🔴 Phase 6 — HRMS + Nigeria Payroll Cutover (ACTIVE)

This is the original fast-track driver. Status from PRD: "Run May 2026 payroll parallel to current system."

| # | Item | Priority | Description |
|---|---|---|---|
| **6-1** | Salary Structure Assignment for all active employees | 🔴 P0 | All 100+ Nigeria staff. |
| **6-2** | PAYE / Pension / NHF / NSITF deductions configured | 🔴 P0 | Per current Nigeria tax tables. |
| **6-3** | Bank upload generation (.csv per bank) | 🔴 P0 | One file per bank with account number + amount columns. |
| **6-4** | Parallel run reconciliation | 🔴 P0 | Compare ERPNext payroll output against legacy system; explain any deltas. |
| **6-5** | Sign-off + cutover | 🔴 P0 | HOD Finance + COO sign-off. |

> **Note:** Current handoff didn't track HRMS line-items in detail. To be re-confirmed with the HR team before Wave D-1 starts so the two threads can run in parallel.

---

## 7. 🟢 Phase A v1.1 — Engagement App Expansion

| # | Item | Priority | Description |
|---|---|---|---|
| **A-1.1** | Helpdesk module integration | 🟢 P3 | Customer support ticketing inside the Engagement App. |
| **A-1.2** | CRM module integration | 🟢 P3 | Lead capture + conversion. |
| **A-1.3** | Brevo WhatsApp channel | 🟢 P3 | Outbound notifications + inbound replies via WhatsApp Business API. |

---

## 8. 🟢 Phase 9 — Month Close Pack Workflow

| # | Item | Priority | Description |
|---|---|---|---|
| **9-1** | Month Close Pack doctype | 🟢 P3 | New doctype aggregating per-month: total sales, variance JEs, stock recon entries, payroll posting, bank rec. |
| **9-2** | Workflow | 🟢 P3 | **Draft → HOD Finance (prepare) → Head of Internal Control (review) → COO (approved) → Locked**. Once Locked, no further GL postings allowed in that period (uses ERPNext's period closing voucher). |

---

## 9. 📦 Misc / Backlog

| # | Item | Priority | Description |
|---|---|---|---|
| **B-1** | Customer Facing Screen | 🟢 P3 | Dual-screen display showing items + total to the customer while the cashier rings up. |
| **B-2** | Stock Recon Unit Variance routing | 🟠 P1 | (Covered under D-8 above — listed here for backlog hygiene.) |
| **B-3** | GIT 48h audit alert | 🟠 P1 | (Covered under D-7 above.) |
| **B-4** | Sales Register report by tax_id | 🟡 P2 | (Covered under D-9 above.) |
| **B-5** | `Head of Finance` duplicate role cleanup | 🟡 P2 | One legacy non-LPG role with 1 user — merge into `LPG Head of Finance` and delete the duplicate. |
| **B-6** | Vue rebuild for "Draft Saved" follow-up message in ClosingDialog | 🟢 P3 | Today the cashier sees the variance error + a Frappe `msgprint` follow-up. Smoother UX would be a dedicated banner in ClosingDialog. |
| **B-7** | Brevo SMS channel (in addition to email) | 🟢 P3 | For COO 4h notification (Wave E-3) and 7-day escalation (Wave D-2). |
| **B-8** | "Save to GitHub" PAT rotation policy | 🟡 P2 | Document a 7-day PAT rotation policy so we don't hand-share long-lived tokens. |
| **B-9** | Test bench / staging site | 🟡 P2 | Currently all changes deploy direct to `sungasmis.v.frappe.cloud`. Spin up a staging clone for Wave D testing. |

---

## 10. Suggested Build Order (next 6 weeks)

> Tight sequencing assuming a single full-time engineer + the user's review bandwidth. Brevo integration is the gate for several items.

```
Week 1 ─── Brevo integration playbook + sandbox account
       └── Wave D-1 (Sequential Workflow doctype) build + test
Week 2 ─── Wave D-1 ship + UAT
       └── Wave D-2 (Open Shift Age scheduler) build
Week 3 ─── Wave D-2 ship + Wave D-3 (48h SLA timer)
       └── Wave D-5 (Annex T-07) build
Week 4 ─── Wave D-4 (Outlet Mgr / COO signature) ship
       └── Wave D-6 (Returns approval) build (Vue rebuild required)
Week 5 ─── Phase 6 HRMS parallel run for May payroll
       └── Wave D-7 build (Purchase / Transfer / GIT routing)
Week 6 ─── Phase 6 cutover + sign-off
       └── Wave D-8 (Stock adjustment routing) build

Stretch ─ Wave E (Path C protocol)
       ├── Phase 5.8 (Backup Profiles)
       ├── Phase 5.9 (Manual Sales Book)
       └── Phase 9 (Month Close Pack)
```

---

## 11. Open Questions for User

These need a decision before the build can proceed cleanly:

1. **Severity tiers for Wave D-1** — Soft / Hard / Critical band cutoffs. Today we have Warn (₦5k) and Block (₦50k) for shortages. Need a third "Critical" tier (e.g. ₦200k+? 5 %+?) to trigger HOD Finance + COO routing.
2. **Outlet Manager mapping** — for D-2 (Open Shift 24h email) we need a way to resolve "the Outlet Manager of POS - Ikeja". Is there a custom field on POS Profile, or should we use the `Employee` doctype with a designation filter?
3. **Brevo account** — does Sungas already have a Brevo account, or do we provision a new one? Will need API key.
4. **HRMS / Phase 6 status** — last touched in handoff. Is May 2026 payroll cutover still on track, or does it need a refresh / re-plan?
5. **Test bench** — should we provision a staging site for Wave D testing, or continue direct-to-prod with the discipline we've shown so far?

---

*End of Roadmap. Re-issued at each Wave completion.*
