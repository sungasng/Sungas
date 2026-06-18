# Sungas ERPNext — CONSOLIDATED ROADMAP (FULL SCOPE)

> **Last updated:** June 2026
> **Status:** Complete catalogue across all phases. Supersedes prior v1 roadmap that focused only on Wave C/D. This document is the master backlog.

---

## Legend

| Symbol | Meaning |
|---|---|
| ✅ | Live in production (tested) |
| 🚧 | In progress / partially shipped |
| ⏸ | Deferred / blocked on external input |
| 🔴 | P0 — blocks core ops or finance close |
| 🟠 | P1 — material improvement, next 1-2 sprints |
| 🟡 | P2 — important but not blocking |
| 🟢 | P3 — nice-to-have / future |
| 📦 | Backlog — scope captured, not scheduled |

---

## 1. Phase Index

| Phase | Title | Status | Items |
|---|---|---|---|
| **Phase 1-4** | Foundation, masters, CoA, Customer migration | ✅ DONE | — |
| **Phase 5** | POS Awesome — Pricing tier engine + cart UI | ✅ DONE | — |
| **Phase 5.5** | POS Profile cloning, role profiles, cashier rollout, thermal receipt | ✅ DONE | — |
| **Phase 5.7** | POS Awesome Hardening + variance accounts (4 new GLs) | ✅ DONE | — |
| **Wave A-C** | Sungas Close Policy + variance enforcement + UX + lockdown | ✅ DONE | — |
| **Phase 6** | HRMS + Nigeria Payroll Cutover | 🚧 95 % DONE | 3 remaining items |
| **Wave D** | Sequential workflow + escalations + Ops routing | 🔴 NEXT | 9 items |
| **Wave E** | Path C Fraud Protocol | 🟠 PLANNED | 4 items |
| **Phase 5.8** | POS Backup profiles per region | 🟡 PLANNED | 1 item (6 profiles) |
| **Phase 5.9** | Manual Sales Book doctype | 🟡 PLANNED | 1 item |
| **Phase 7** | Helpdesk (SLA, ticket flows, email) | 🟢 PLANNED | scope only |
| **Phase 8** | CRM (pipeline + weekly dashboard) | 🟢 PLANNED | scope only |
| **Phase A v1.1** | Engagement App expansion | 🟠 PLANNED | 9 items |
| **Phase 9** | Period Close + UAT + opening balances | 🟢 PLANNED | 3 items |
| **Phase 10** | Budgeting Module | 🟢 PLANNED | 1 item |
| **Engineering** | Equipment/Services onboarding + Manufacturing hygiene | 🟢 BACKLOG | 3 items |
| **Bank Statement App** | Already-built doctypes — needs deployment + UAT | 🟡 BACKLOG | UAT |
| **Stakeholder SLA + KPI** | Cross-cutting reporting layer | 🟠 PLANNED | 4 items |

---

## 2. ✅ DONE (full inventory)

### Foundation
- ✅ Fresh ERPNext v15 install on Frappe Cloud (`sungasmis.v.frappe.cloud`)
- ✅ Cleaned Customer + Chart of Accounts data migration
- ✅ Company, Cost Centers (21 outlet CCs), HRMS Branches, Sungas Region accounting dimensions
- ✅ `sungasng/HR-Enhancements` v13 → v15 port (commit `c802054`)
- ✅ `sungasng/Sungas` v13 → v15 port (commit `7a95d5a`)

### Phase 5 — POS Awesome Core
- ✅ LPG Outlet Price Tier engine (Item × Customer Group × Territory × Qty)
- ✅ LPG Price Change Request (PCR) workflow: Draft → Head of Sales → Head of Finance → Approved → tier upsert
- ✅ 64-row price matrix seeded (`seed_all_lpg_tier_rates.py`)
- ✅ Strict tier mode (no tier → no sale)
- ✅ Cash-overage rounding with round-off account wiring
- ✅ Barcode receipt + Code 128 encoding `INVOICE|QTY`
- ✅ Mobile + search UI polish

### Phase 5.5 — POS Rollout
- ✅ 22 POS Profiles cloned per-outlet (Cost Centers, Cash/Transfer/POS-Incoming accounts, HRMS Branches)
- ✅ `POS - Bulk Sales Benin` disabled (wholesale via Sales Invoice)
- ✅ 4 LPG Role Profiles: POS User / Plant Manager / Head of Sales / Head of Finance
- ✅ 18 Plant Managers + 41 cashiers assigned profiles
- ✅ 2 missing cashiers provisioned (Emmanuel Nnorom, Nimota Sulaimon)
- ✅ POS Awesome switched to POS Invoice mode
- ✅ Custom DocPerm for `LPG POS User` (POS Invoice / Opening / Closing Shift)
- ✅ Sungas Thermal 58mm print format
- ✅ Customer lockdown (cashier cannot edit existing customers; new ones forced to Retail group)

### Phase 5.7 — POS Hardening + Variance Accounts
- ✅ 5-bucket COGS (8101 LPG / 8102 Cylinders / 8103 Retail / 8104 Equipment / 8105 Services)
- ✅ 5 Income accounts (7101 LPG / 7102 Cylinders / 7103 Retail / 7104 Services / 7105 Cylinders Revenue)
- ✅ `expense_account` + `income_account` set on all 143 sales items
- ✅ **4 cash variance GL accounts** (2608 Cashier Recovery, 6224 Overage Suspense, 9246 Shortage Written Off, 7205 Overage Time-Barred Income)
- ✅ Backfilled 3 historical variance JEs (₦5k + ₦24k + ₦200k against Peace HR-EMP-00053)
- ✅ User ↔ Employee linkage (67/245 employees linked, all active cashiers + plant managers)
- ✅ Outlet scoping via `permission_query_conditions` + `has_permission`
- ✅ Implicit-scope fallback (POS Profile User child table)
- ✅ Owner-bypass on has_permission
- ✅ FIRS compliance: TIN, RECEIPT label, 0 % VAT explicit line on print
- ✅ Bobo Gas brand override for Itele (separate TIN, no Sungas logo, Itele address)
- ✅ Tax IDs set: Sungas `00201561-0001`, Bobogas `2501110131157`

### Wave A-C — Variance Enforcement
- ✅ `Sungas Close Policy` single doctype (thresholds, accounts, approver roles)
- ✅ Asymmetric thresholds (shortage ₦5k/₦50k, overage ₦10k/₦100k)
- ✅ Percentage rules gated by `block_pct_min_expected = ₦500k`
- ✅ `before_submit` variance enforcement (warn requires remarks, block requires approver)
- ✅ `on_submit` auto-post variance JE with party tagging
- ✅ `variance_approved_by` + `variance_je` walled off at permlevel 1
- ✅ Custom DocPerm: `LPG Head of Operations` level-0 read/write on POS Closing Shift
- ✅ Variance Approved By link filter (only approver-role users)
- ✅ Partial payments (split tender) on all 22 POS profiles
- ✅ POS Awesome Vue: unconditional variance remarks textarea + tonal severity alert
- ✅ `submit_closing_shift` override: draft persists on block
- ✅ Idempotent re-submission

### Phase 6 — HRMS / Nigeria Payroll (95 % DONE)
- ✅ Employee data audit (217 active staff verified)
- ✅ Master backfill (departments, designations, branches, employment types)
- ✅ 12 Salary Components (earnings + statutory + HMO + Co-op + Staff Loan)
- ✅ HMO custom fields + `Sungas Standard` salary structure
- ✅ 4 new payable accounts (HMO, COOP loan/contrib, Staff Loan receivable)
- ✅ 21 new payroll Cost Centers + `Employee.payroll_cost_center` + 217 SSAs
- ✅ Fix 10x SSA base bug (148 SSAs cancelled+resubmitted with correct Gross col)
- ✅ Residual audit + 3 missing SSAs created via fuzzy matcher
- ✅ **PAYE NTAA 2025 formula live** (6-bracket annualised, excludes Non-Exec/Chairman/Independent Directors)
- ✅ Operational Manuals (10 docs, 1,885 lines)
- ✅ Holiday Lists (HQ Sat+Sun, Outlets no weekly off), 233 employees assigned
- ✅ Grade Level (G1-G7) + 13th_month_eligible custom fields, 4 service providers excluded
- ✅ 6 Leave Types + 3 Policies + 229 Assignments (Annual G1=20d, G2=15d, G3-G7=10d, etc.)
- ✅ Leave Allowance (10 % basic, anniversary) + 13th Month components attached to Sungas Standard
- ✅ HR Migration Checklist + 5 templates (Bank Details, Rent Decl, Leave App, Onboarding, Exit)
- ✅ 3 Workflows: Leave + Expense (tiered) + Payroll Entry with email alerts
- ✅ NIBSS Bank Codes seeded (45 banks, Tier-1 + commercial)
- ✅ Bank Upload Generator (Stanbic + Fidelity CSVs generated for `HR-PRUN-2026-00001`)
- ✅ Sungas Payslip print format (clean Nigerian layout, hides India internals)
- ✅ Parallel Payroll Run preflight + slip creation (216/216 slips, 0 failed; validated to-the-kobo)

### Engagement App v1.0
- ✅ Initial scaffolding (per handoff)

### Documentation
- ✅ Operations Manual v1.1 (DOCX + Markdown shipped 2026-06)

---

## 3. 🔴 Phase 6 (HRMS) — Outstanding (3 items)

| # | Item | Priority | Status | Notes |
|---|---|---|---|---|
| **6.7** | Confidentiality lockdown | 🔴 P0 | NOT STARTED | Permlevels on Salary Slip / SSA / Bank Details; 2FA enforced for HR + Finance roles; IP whitelists for sensitive doctypes |
| **6.8b** | Finance sign-off on Stanbic + Fidelity bank upload CSVs | 🔴 P0 | ⏸ AWAITING FINANCE | CSVs sent 2026-05-23 |
| **6.8c** | Parallel run reconciliation vs Excel | 🔴 P0 | ⏸ AWAITING USER | Re-engage once May 2026 Excel baseline uploaded to `/tmp/payroll_excel_baseline.csv` |

---

## 4. 🔴 Wave D — POS Closing Workflow + Ops Routing (NEXT)

| # | Item | Priority | Dependencies |
|---|---|---|---|
| **D-1** | Sequential Workflow doctype for POS Closing Shift (Draft → Plant Mgr → HOD Ops → HOD Finance → Submitted [+ optional COO]) with severity tiers Soft/Hard/Critical | ✅ DONE | C done |
| **D-2** | Open Shift Age escalation scheduler (24h Outlet Mgr, 48h HOD Ops, 7d HOD Finance) | ✅ DONE | Brevo integration |
| **D-3** | 48h SLA timer (variance approval) — auto-escalate to Path C | ✅ DONE | D-2 |
| **D-4** | Provisional Suspense JE on Draft (Option C) + COO informational notification + variance_amount backfill | ✅ DONE | D-1, D-2 (Brevo) |
| **D-5** | Annex T-07 worksheet doctype (count-by-denom, cause taxonomy, photo evidence) | 🟠 P1 | — |
| **D-6** | Returns / refund approval gate (Vue rebuild — manager PIN above threshold) | 🟠 P1 | Vue rebuild |
| **D-7** | Inventory Purchase / Transfer / GIT routing + 48h GIT audit flag | 🟠 P1 | In-Transit warehouse setup |
| **D-8** | Stock Adjustment routing (Plant+OM / HOD Ops+Finance / COO tiers) | 🟠 P1 | — |
| **D-9** | Sales Register report filtered by `tax_id` (Rev360 export prep) | 🟡 P2 | — |

**Cross-cutting infra needed:**
- Brevo email integration (gates D-2, D-3, D-7, Wave E-3)
- Frappe Workflow JSON for severity routing (reusable across D-1, D-7, D-8)

---

## 5. 🟠 Wave E — Path C Fraud Protocol (4 items)

| # | Item | Priority |
|---|---|---|
| **E-1** | Outlet Bank Deposit Freeze flag | 🟠 P1 |
| **E-2** | Cashier POS access auto-disable workflow | 🟠 P1 |
| **E-3** | COO 4h notification (Brevo SMS+email) | 🟠 P1 |
| **E-4** | Internal Audit case auto-open (Fraud Investigation doctype) | 🟠 P1 |

---

## 6. 🟠 Stakeholder SLA + KPI Reporting (cross-cutting)

| # | Item | Priority |
|---|---|---|
| **K-1** | `Stakeholder SLA Event` doctype (KPI logging for HR appraisal) | 🟠 P1 |
| **K-2** | Cashier Variance Ledger report (per-cashier ageing of 2608 balances) | 🟠 P1 |
| **K-3** | Stakeholder Performance L1-L5 dashboards | 🟠 P1 |
| **K-4** | Month Close Health dashboard | 🟠 P1 |

---

## 7. 🟠 Phase A v1.1 — Engagement App Expansion

> Brief received 2026-05-31 from Senior BA. Significant expansion over Sprint 0.

| # | Item | Priority |
|---|---|---|
| **A-1** | **21 SCL Locations doctype** (region / state / PTL / CSE / FO mapping) | 🟠 P1 |
| **A-2** | Customer Segmentation custom fields on Customer (segment, assigned_team, assigned_cse, assigned_location, preferred_channel, status, last_interaction_date, last_order_date, lifetime_gas_volume_kg, dnc_flag, churn_suggested_date, avg_purchase_cycle_days) | 🟠 P1 |
| **A-3** | **Interaction Log** master doctype (customer-facing record across channels) | 🟠 P1 |
| **A-4** | **Support Ticket** doctype (formal complaints with SLA Policy + escalation levels) | 🟠 P1 |
| **A-5** | **Internal SLA Task** doctype (cross-team handoffs with SLA breach detection) | 🟠 P1 |
| **A-6** | **Weekly Engagement Plan** workflow (Draft → Pending → Approved → Outcome Reported → Closed) + auto-suggest churned customers | 🟠 P1 |
| **A-7** | **SLA Policy** doctype (auto-assignment by category+segment) | 🟠 P1 |
| **A-8** | **Churn Detection** daily job (Retail >35d/>60d; Commercial/Bulk avg_cycle+2/+7) | 🟠 P1 |
| **A-9** | Brevo WhatsApp + SMS channel for outbound + inbound | 🟢 P3 |

---

## 8. 🟡 Phase 5.8 / 5.9 — Continuity

| # | Item | Priority |
|---|---|---|
| **5.8** | POS Backup profiles per region (Lagos1, Ogun1, Ogun2, Edo1, Delta1, Rivers1 — 6 shared profiles for Path B.2 fallback selling) | 🟡 P2 |
| **5.9** | Manual Sales Book doctype + Sales Invoice batch import (Path B.3) | 🟡 P2 |

---

## 9. 🟢 Phase 7 — Helpdesk

| # | Item | Priority | Notes |
|---|---|---|---|
| **7-1** | SLA Policy doctype | 🟢 P3 | Possibly merged with Engagement App A-7 |
| **7-2** | Ticket flows + assignment rules | 🟢 P3 | — |
| **7-3** | Email integration | 🟢 P3 | Already have helpdesk app installed |
| **7-4** | Customer-facing portal | 🟢 P3 | — |

---

## 10. 🟢 Phase 8 — CRM

| # | Item | Priority |
|---|---|---|
| **8-1** | Lead/Opportunity pipeline | 🟢 P3 |
| **8-2** | Weekly engagement dashboard | 🟢 P3 |
| **8-3** | CRM ↔ Engagement App data sync | 🟢 P3 |

---

## 11. 🟢 Phase 9 — Period Close + Cutover

| # | Item | Priority |
|---|---|---|
| **9-1** | Month Close Pack workflow doctype (Draft → HOD Finance → Head Internal Control → COO → Locked) | 🟢 P3 |
| **9-2** | Opening Balances import | 🟢 P3 |
| **9-3** | UAT + cutover | 🟢 P3 |
| **9-4** | **POS Invoice archival / partitioning strategy** — at 22k invoices/day (8M/year), plan MySQL year-partition on `tabPOS Invoice` and a cold-archive doctype for closed periods (>13 months). Needed by mid-Year-2 to keep list-view + report performance constant. | 🟡 P2 |

---

## 12. 🟢 Phase 10 — Budgeting

| # | Item | Priority |
|---|---|---|
| **10-1** | ERPNext Budget doctype against Cost Centers | 🟢 P3 |
| **10-2** | Annual Compensation Cost dashboard (month-by-month forecast incl. 13th Month spike + Leave Allowance bumps) | 🟢 P3 |

---

## 13. 🟢 Engineering / Manufacturing Backlog

| # | Item | Priority |
|---|---|---|
| **ENG-1** | Equipment & Services inventory onboarding (engineering equipment avg ₦6M — reticulation/combustion/conversion/fabrication/corrosion-control under Item Group `Equipment`; service items under `Services`) | 🟢 P3 |
| **ENG-2** | Services Quotation + Project Costing workflow (Project + BOM + Sales Order with sub-assemblies) | 🟢 P3 |
| **ENG-3** | Manufacturing data hygiene — flip `is_sales_item=0` on Raw Material + Sub Assemblies items (143 sales items today) | 🟢 P3 |

---

## 14. 🟡 Bank Statement App (Existing, Needs UAT)

23 doctypes already built in `/app/forks/Bank-Statement` (bank_account_limit, bank_statement, bank_statement_format, bank_statement_item, bank_statement_mapping_item, bank_transaction_type, document_party_type, document_type_to_be_paid, merged_payment_beneficiaries, payment_advice, payment_advice_item, payment_instruction, payment_proposal_item, payment_run, payment_run_filter, payment_run_filter_item, payment_run_settings, third_party_search_fields, transaction_type_journal_template, voucher_search_key, voucher_search_specifications, …).

| # | Item | Priority |
|---|---|---|
| **B-1** | Deploy Bank-Statement app to Frappe Cloud bench | 🟡 P2 |
| **B-2** | Wire bank statement formats per Sungas bank (Stanbic, Fidelity, GTB, etc.) | 🟡 P2 |
| **B-3** | Payment Run UAT with finance team | 🟡 P2 |
| **B-4** | Decide: integrate this app's Payment Advice with HR bank upload (6b)? | 🟡 P2 |

---

## 15. 🟡 Compliance / Reporting Backlog

| # | Item | Priority |
|---|---|---|
| **R-1** | NRS Rev360 monthly VAT Schedule export (bench command, ~45 min build) | 🟡 P2 |
| **R-2** | ERPNext Sales Register quick-win for VAT (configure filtered view by tax_id, monthly close pack input) | 🟡 P2 |

---

## 16. 📦 Other / Misc Backlog

| # | Item | Priority |
|---|---|---|
| **B-5** | `Head of Finance` (non-LPG) duplicate role cleanup — merge 1 user into `LPG Head of Finance` | 🟡 P2 |
| **B-6** | Vue rebuild for "Draft Saved" follow-up banner in ClosingDialog (currently uses Frappe msgprint) | 🟢 P3 |
| **B-7** | Customer Facing Screen (dual-display POS Awesome) | 🟢 P3 |
| **B-8** | UpdateCustomer.vue z-index nit (toast hidden behind modal) | 🟢 P3 |
| **B-9** | Test bench / staging site provisioning | 🟡 P2 |
| **B-10** | PAT rotation policy (7-day rotation, "Save to GitHub" guidance) | 🟡 P2 |
| **B-11** | Monthly Escalation Digest — HOD Ops summary of every L1/L2/L3 escalation fired in prior month (count by outlet, avg age-to-close, top offenders). Reuses Brevo helper from D-2. | 🟢 P3 |

---

## 17. Suggested Build Order (next 6-8 weeks)

```
Week 1  ─── Phase 6.8b/6.8c HRMS close-out (P0 — payroll cutover sign-off)
        └── Brevo integration playbook + sandbox account

Week 2  ─── Wave D-1 (Sequential Workflow doctype) build + UAT
        └── Phase 6.7 (Confidentiality lockdown)

Week 3  ─── Wave D-2 (Open Shift Age scheduler) build + UAT
        └── Wave D-3 (48h SLA timer)

Week 4  ─── Wave D-4 (Outlet Mgr / COO signatures)
        └── Wave D-5 (Annex T-07 worksheet)

Week 5  ─── Wave D-6 (Returns approval — Vue rebuild)
        └── Wave D-7 (Purchase / Transfer / GIT routing) — In-Transit warehouse setup

Week 6  ─── Wave D-8 (Stock Adjustment routing) + Wave D-9 (Sales Register / Rev360)
        └── K-1, K-2 (Stakeholder SLA Event doctype + Cashier Variance Ledger report)

Week 7  ─── Wave E (Path C fraud protocol: E-1..E-4)
        └── K-3, K-4 (Stakeholder Performance + Month Close Health dashboards)

Week 8  ─── Phase A v1.1 (Engagement App expansion: A-1 Locations + A-2 Segmentation + A-3 Interaction Log)
        └── Phase 5.8 (Backup profiles) + 5.9 (Manual Sales Book)

Stretch ─ Phase A v1.1 continued (A-4..A-8: Tickets, Internal SLA, Engagement Plan, SLA Policy, Churn)
        ├── Bank Statement app UAT + deploy
        ├── R-1 (Rev360 export) + R-2 (Sales Register)
        ├── Phase 9 (Month Close Pack)
        ├── Phase 10 (Budgeting)
        └── Engineering / Manufacturing onboarding
```

---

## 18. Open Questions for User Decision

Before Wave D-1 build starts:

1. **Severity tiers for D-1** — define Soft / Hard / Critical band cutoffs. Today: Warn ₦5k, Block ₦50k. Need a third "Critical" tier (e.g. ₦200k+ ? or 5 %+ ?) to trigger HOD Finance + COO routing.
2. **Outlet Manager mapping** — for D-2 (24h email). Custom field on POS Profile, or Employee doctype with designation filter?
3. **Brevo account** — does Sungas already have one? Otherwise we need to provision + get API key.
4. **Phase 6 close-out** — May 2026 Excel reconciliation baseline upload + Finance bank-CSV sign-off. Are these still on track?
5. **Staging bench** — provision a clone of `sungasmis.v.frappe.cloud` for Wave D testing, or continue direct-to-prod?
6. **Engagement App v1.1 ordering** — A-1 (21 Locations) is foundational and the rest depend on it. Build now or wait until after Wave D?
7. **Bank Statement app** — fully spec'd out, just needs UAT. Schedule UAT week for finance team?

---

## 19. What I missed in the v1 roadmap (full disclosure)

For transparency — these were dropped from the prior consolidation and are now restored:

- **Phase 6 (HRMS)** — listed as "active" with 5 items, but PRD shows it's 95 % done with only 3 outstanding (6.7 confidentiality, 6.8b finance sign-off, 6.8c reconciliation). My prior table over-stated remaining work.
- **Phase 7 (Helpdesk)**, **Phase 8 (CRM)** — entire phases missing from v1.
- **Phase A v1.1** — listed only 3 items; the actual spec has 9.
- **Stakeholder SLA + KPI** layer — entire cross-cutting area missing from v1.
- **Phase 10 (Budgeting)** — missing.
- **Engineering / Manufacturing backlog** (Equipment onboarding, Services quotation, manufacturing hygiene) — missing.
- **Bank Statement app** — already-built 23 doctypes that need UAT, missing from v1.
- **Variance lifecycle accounts** — full chain (2608 → 9246 written off, 6224 → 7205 time-barred income) was not described.
- **Compliance / Reporting backlog** (Rev360 export, Sales Register VAT) — missing.

This v2 roadmap is the canonical version. Treat the prior v1 (`ROADMAP.md` commit `ff003aa`) as superseded.

---

*End of Roadmap v2. Re-issued at each Wave completion. Will be re-circulated post Wave D-2 with timing actuals.*
