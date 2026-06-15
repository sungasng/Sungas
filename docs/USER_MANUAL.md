# Sungas ERPNext Operations Manual

> **Version:** v1.1 — June 2026
> **Audience:** Cashiers, Outlet Managers, Sales Managers, Approvers (Plant Manager / Head of Sales / Head of Operations / Head of Finance), Accountants, Inventory Officers, System Administrators.
> **Scope:** Daily operations, POS Awesome, pricing tier engine + price change request workflow, variance handling, FIRS receipt compliance, role-based access. Covers everything live in production as of the date above. Roadmap items are explicitly flagged in §13.

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

## 2. POS Awesome — How to Use

POS Awesome is the front-of-house selling tool. It replaces the standard ERPNext POS screen with a tablet-friendly interface tuned for high-throughput LPG retail.

### 2.1 Logging In

1. Open `https://sungasmis.v.frappe.cloud/posawesome` (mobile/tablet friendly).
2. Sign in with your work email.
3. You'll be taken to the POS Profile selector. **You only see POS Profiles you're assigned to** (your outlet only; see §6 for the scoping logic).
4. Pick a POS Profile (e.g. `POS - Ikeja`) → click **Open Shift** if you don't have one open already.

### 2.2 Opening Cash Voucher

1. Enter the cash balance you start the day with (in the **Balance Detail** table — Cash, POS, Transfer rows pre-populated from the POS Profile).
2. Click **Submit Opening Voucher**.
3. POS Awesome flips to the selling screen.

> **Important:** A user can have **multiple opening shifts** open simultaneously if they cover more than one POS Profile (e.g. an Outlet Manager covering two registers at the same outlet). The variance/closing rules apply independently to each shift.

### 2.3 Selling Workflow

**A. Pick the customer**

- Top right has the Customer selector. Start typing the customer name or phone number — POS Awesome searches across name, phone, email, and tax ID.
- If the customer is new: click **+ New Customer**, fill name + phone + Customer Group (Retail / Commercial / Distributor / Bulk) + Territory (the outlet's territory). Customer Group + Territory determine the price tier (see §3).
- Walk-in retail customers default to the configured "Walk-In Customer" record on the POS Profile.

**B. Add items**

- Search box: type item name, item code, or scan a barcode. Click an item card to add to the cart.
- Item categories are shown as tabs (LPG Cylinder Filled, LPG Cylinder Empty, LPG Bulk, Accessories).
- **Quantity** can be edited inline in the cart. Press the input → tap up/down arrows or type directly.
- **Rate** is auto-populated from the LPG Outlet Price Tier matrix (see §3) based on the customer's Customer Group + Territory. **Cashiers cannot override rates** unless the POS Profile has "Allow Rate Change" enabled.

**C. Discounts**

- Two discount mechanisms are available, depending on POS Profile config:
  - **Line-level discount** (per item): click the percentage icon next to the item in the cart.
  - **Invoice-level discount**: in the cart summary at the bottom, expand "Additional Discount" → choose Percentage or Amount.
- All discount lines are logged on the POS Invoice for audit. Roles without discount permission see the field disabled.

**D. Payment**

- Click **Pay** at the bottom of the cart.
- Choose Mode of Payment (Cash / POS / Transfer / cheque if enabled on the profile).
- **Partial payments / split tender** are enabled across all 22 POS profiles — you can split a single invoice across multiple MoPs. Just enter the amount paid in each row; the dialog shows the remaining balance live.
- Click **Submit Payment** → invoice generates → FIRS-compliant receipt prints (see §5).

**E. Held / Saved Carts**

- During selling: click the **Hold** icon to park the current cart and start a new one (useful when a customer steps away to fetch their cylinder).
- Held carts are listed in the left side panel. Click to resume.
- Held carts persist across browser refresh but are user-scoped to your session.

**F. Returns / Refunds**

- Click **Search Invoice** (top toolbar) → find the original invoice by number or customer.
- Click **Return** → enter quantities to return → submit.
- Returns are created as a separate POS Invoice with negative quantities, linked to the original. Cash is refunded via the original Mode of Payment.
- **Authority:** Returns above the configured threshold (default ₦20,000) require Outlet Manager approval — the dialog will block the cashier and prompt for a manager PIN. *(This is roadmap — currently any LPG POS User can process a return; will be tightened in Wave D-6.)*

**G. Closing the shift** — see §4.

### 2.4 Keyboard Shortcuts (Desktop POS)

| Shortcut | Action |
|---|---|
| `Ctrl+P` | Open Pay dialog |
| `Ctrl+H` | Hold current cart |
| `Ctrl+N` | New customer |
| `Ctrl+F` | Focus item search |
| `Esc` | Close any open dialog |

### 2.5 Offline Behaviour

POS Awesome assumes a live connection. There is **no offline mode** in the current deployment — outlets must have working internet. If the connection drops:

1. Don't refresh. The cart in memory is preserved.
2. Once internet returns, click **Sync** (cloud icon at the top right) to flush any queued invoices.
3. If a sale was rung up during the outage and never reached the server, retry once. If still failing, fall back to the Manual Sales Book *(roadmap — Phase 5.9)* and key it in later.

---

## 3. Pricing — LPG Outlet Price Tier Engine

LPG selling rates in Sungas are NOT set on the standard ERPNext Item Price doctype. They live in a **custom matrix** keyed on `(Item × Customer Group × Territory × Quantity Window)`.

### 3.1 Why a custom tier engine

The official Sungas price list (Pricelist.xlsx, 2026-02 revision) is structured as a matrix:

| Outlet group | Retail | Commercial | Distributor | Bulk |
|---|---|---|---|---|
| OGUN 1 (Maba / Sefu / Ebute / Aseese) | 1,350 | 1,300 | 1,160 | — |
| OGUN 2 (Itele / Iju-Ota / Osi-Ota / Ijoko) | 1,350 | 1,300 | 1,150 | — |
| LAGOS 1 (Ikeja / Oworo / Pedro / Bolade / Mafoluku) | 1,360 | 1,300 | 1,140 | — |
| RIVERS 1 (Eleme / Reclamation) | 1,380 | 1,350 | 1,180 | — |
| EDO 1 (Ekehuan / Upper Mission / Idowina / Idokpa / Okhuoromi) | 1,320 | 1,305 | 1,170 | — (Ekehuan: Bulk 1,200) |
| DELTA 1 (Asaba) | 1,365 | 1,365 | 1,180 | — |

Standard ERPNext Item Price (single rate per item or per Price List) can't express the territory dimension cleanly. The custom **LPG Outlet Price Tier** doctype does.

### 3.2 How the engine picks a rate

When a cashier adds an item to the cart, POS Awesome calls the tier resolver with:

- `item_code` (e.g. `LPG-REFILL`)
- `customer.customer_group`
- `customer.territory`
- `quantity` (for tier-bucketed pricing)

The resolver finds the **most specific enabled row** in `LPG Outlet Price Tier` that matches and whose `min_qty` ≤ quantity ≤ `max_qty` and whose `valid_from` … `valid_to` window covers today. If multiple rows match, the most recently modified wins.

If no tier row matches, the system falls back to the standard ERPNext Item Price (default Price List on the POS Profile) — but in practice every (item × customer_group × territory) combo in the matrix above has a seeded tier row.

### 3.3 Where to view / manage tier rows

- Desk URL: `/app/lpg-outlet-price-tier`
- Filter by Item, Customer Group, or Territory to find specific rates.
- Each row has: `enabled`, `min_qty`, `max_qty`, `rate`, `currency`, `valid_from`, `valid_to`, `notes`.
- **Do not edit tier rows directly in production.** Use the Price Change Request workflow (§3.5) so the approval chain captures the decision.

### 3.4 Bulk seeding / one-shot upload

Two paths exist for bulk loading:

**A. Script-based (used during initial rollout):**

The seed script lives at `apps/posawesome/scripts/seed_all_lpg_tier_rates.py` on the bench. It encodes the price matrix above in Python and idempotently upserts each row. Run with:

```bash
bench --site sungasmis.v.frappe.cloud execute \
  "exec(open('apps/posawesome/scripts/seed_all_lpg_tier_rates.py').read())"
```

The script:
- Diagnoses available Customer Groups + Territories first
- Honours alias mappings (e.g. "Ebute" = "Ebutte")
- Reports skipped / created / updated rows per combo
- Preserves the protected `(LPG-REFILL, Retail, Pedro) = NGN 3,000` test row unless `PROTECT_PEDRO_RETAIL_TEST = False`
- Commits + clears the cache at the end

**B. ERPNext Data Import (ad-hoc):**

- Go to `/app/data-import/new`
- DocType = `LPG Outlet Price Tier`
- Action = Insert New Records *or* Update Existing Records
- Download the template, fill in `item_code`, `customer_group`, `territory`, `min_qty`, `max_qty`, `rate`, `currency`, `valid_from`, `valid_to`, `enabled`
- Upload → click **Start Import**.

> Either method bypasses the Price Change Request approval flow. Use them only for the **initial load** or for bulk corrections approved out-of-band (e.g. company-wide reprice signed off by the MD). Day-to-day price moves should go through §3.5.

### 3.5 Price Change Request (PCR) Workflow

For ongoing price changes, use the **LPG Price Change Request** doctype (`/app/lpg-price-change-request`). It enforces a 3-step approval before any tier row is touched.

**Workflow states:**

```
Draft  →  Pending Head of Sales  →  Pending Head of Finance  →  Approved  →  (auto-upserts tier)
```

**Naming:** `PCR-####` (auto-incremented).

**Step-by-step:**

1. **Requester** (typically Plant Manager or Sales rep) creates a new PCR:
   - `item_code` (e.g. `LPG-REFILL`)
   - `customer_group` (Retail / Commercial / Distributor / Bulk)
   - `territory` (specific outlet, e.g. Ikeja)
   - `current_rate` (auto-filled from the existing tier row, if any)
   - `proposed_rate`
   - `min_qty` / `max_qty` (quantity tier window — defaults 0 / 0 means "any qty")
   - `valid_from` / `valid_to` (date window the new rate is active)
   - `reason` (text justification — required)
   - `supporting_docs` (attach LPG supplier price update, market survey, board memo, etc.)
2. Set workflow state to **Pending Head of Sales** → Save. The system stamps `plant_manager = <you>` and `plant_manager_approved_on = now`.
3. **Head of Sales** reviews the request in their inbox notifications. If approved, advance to **Pending Head of Finance**. The system stamps `head_of_sales = <user>` and timestamp.
4. **Head of Finance** reviews. If approved, advance to **Approved**. The system stamps `head_of_finance = <user>` and timestamp.
5. On submit (state = Approved), the controller **automatically upserts the matching LPG Outlet Price Tier row** with the new rate + qty window + validity dates. The new tier name is back-linked on the PCR via `created_tier` for audit.
6. POS Awesome picks up the new rate on the next cart add (cache TTL ≈ 30 s).

**Rejection / re-loop:**

- At any stage the reviewer can set state back to **Draft** with a comment. The requester revises and re-submits.

**Audit trail:**

- The doc captures who approved at each stage with a timestamp — see the **Workflow** section of the PCR record.
- The created tier row's `notes` field contains: `Updated by PCR PCR-XXXX on YYYY-MM-DD (was NGN X,XXX.XX)`.

### 3.6 Removing / disabling a tier

To stop using a tier row (e.g. discontinue a discount):

1. Either open the **LPG Outlet Price Tier** row directly (System Manager only) and untick `enabled`, **OR**
2. Raise a PCR with `proposed_rate` = the new "back to standard" rate and let the workflow run.

The recommended path is (2) — keeps the audit chain intact.

---

## 4. Cashier Daily Operations (Variance Handling)

### 4.1 Opening a Shift

1. Log into POS Awesome at `https://sungasmis.v.frappe.cloud/posawesome`.
2. Select your POS Profile (e.g. `POS - Ikeja`). You will only see profiles you are assigned to.
3. Enter opening cash → **Submit Opening Voucher**.
4. Begin selling.

### 4.2 Selling (Cash, POS, Transfer, Partial Payments)

- Add items, set quantities, choose customer.
- **Rates are auto-applied from the LPG Outlet Price Tier matrix** (see §3). Cashiers cannot manually override rates unless the POS Profile permits it.
- **Partial payments (split tender) are enabled** across all 22 POS profiles. You can split a single invoice across Cash + POS + Transfer in any combination.
- Submit invoice. A FIRS-compliant receipt is generated.

### 4.3 Closing a Shift

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

### 4.4 Continuing to Sell After a Blocked Close

If the close was blocked at the hard band, **the opening shift remains open**. You can keep selling on it; the dispute sits in the background as a draft. Once an approver signs off, you (or anyone with submit rights) can re-submit the draft to close the shift.

---

## 5. Hard-Variance Approval Workflow (Path B)

This is the workflow you saw in the spec — it kicks in whenever variance crosses the block threshold.

### 5.1 What the cashier sees

When submit is blocked, two messages appear in sequence:

1. **Block message:** *"Variance of NGN X,XXX.XX exceeds the block threshold and requires approval from one of: LPG Head of Operations, Accounts Manager, LPG Head of Finance, System Manager."*
2. **Draft confirmation:** *"Draft POSA-CS-26-XXXXXX has been saved and is awaiting approval. Once an approver fills the 'Variance Approved By' field via Desk, you (or a manager) can submit it from /app/pos-closing-shift/POSA-CS-26-XXXXXX."*

The opening shift stays open; the cashier resumes sales.

### 5.2 What the approver does

> **Approver = anyone holding `LPG Head of Operations`, `LPG Head of Finance`, `Accounts Manager`, or `System Manager`.** (Wave D will tighten this to sequential routing.)

1. Open the Desk URL: `https://sungasmis.v.frappe.cloud/app/pos-closing-shift?docstatus=0`. You will see all pending drafts.
2. Click the relevant draft.
3. Review the variance + cashier's remarks at the top (orange banner shows the variance amount and direction).
4. In the **Variance Approved By** field, pick a user — the dropdown is **filtered to approver-role users only**. Pick yourself (or the user delegated to approve).
5. Optionally add a follow-up note in **Variance Remarks**.
6. Press **Ctrl+S** to save. **Do NOT click Submit.**

### 5.3 Closing the shift after approval

Either the cashier or any user with submit rights:

- **Path A (cashier re-submits via POS Awesome):** Click Close Shift again. The dialog is fresh, but our override detects the existing draft for the same opening shift and updates it with the new totals before re-attempting submit. Because the approver is now set, the block lifts and the close proceeds.
- **Path B (admin submits via Desk):** Open `/app/pos-closing-shift/POSA-CS-26-XXXXXX` and click **Submit** at the top right.

When the submit succeeds, `on_submit` fires `post_variance_journal`, which auto-creates a Journal Entry (see §6).

---

## 6. Variance Journal Entries (Auto-Posted)

Whenever a closing shift submits with non-zero variance, a Journal Entry is automatically posted with the following structure:

### 6.1 Shortage (cash short)

| Account | Dr | Cr | Party |
|---|---|---|---|
| **Cashier Recovery (e.g. 2608)** | abs(variance) | — | Employee = cashier's Employee record |
| Cash – \<Outlet\> – SCL | — | abs(variance) | — |

The party tag means the unrecovered cash is tracked against the specific cashier and can be deducted from payroll (or formally written off) by HR.

### 6.2 Overage (cash over)

| Account | Dr | Cr | Party |
|---|---|---|---|
| Cash – \<Outlet\> – SCL | abs(variance) | — | — |
| **Overage Suspense (e.g. 6224)** | — | abs(variance) | — |

### 6.3 JE Remark

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

### 6.4 Configuration

The accounts and policy are stored on the **Sungas Close Policy** single doctype:

- Navigate to `/app/sungas-close-policy`.
- Set `cashier_recovery_account` and `overage_suspense_account` (per-company defaults — currently mapped to SCL).
- Set `approver_roles` (one role per line).
- Tune thresholds (`warn_abs`, `block_abs`, `warn_abs_overage`, `block_abs_overage`, `warn_pct`, `block_pct`, `block_pct_min_expected`).
- Toggle `require_remarks_on_variance` (default ON).

> **Only System Managers should edit this doctype.** It is the single source of truth for all variance enforcement.

---

## 7. FIRS-Compliant Receipts

### 7.1 What's printed

Every POS receipt produced from POS Awesome includes:

1. The mandatory **`RECEIPT`** label above the invoice number (FIRS requirement).
2. **Company TIN** (printed once, in the header).
3. A dedicated **0 % VAT** tax line, rendered explicitly even when the amount is ₦0.00. This is a FIRS-2025 requirement: zero-rated supplies must show the tax line, not omit it.
4. Items list with quantities and totals.
5. Mode-of-payment breakdown with partial-payment support.
6. Cashier and outlet at the footer.

### 7.2 Brand overrides

| Outlet | Brand | TIN | Notes |
|---|---|---|---|
| All Sungas LPG outlets (Ikeja, Ebute, Lekki, etc.) | **Sungas** logo + HQ address | SCL TIN | Default print format |
| **Itele** | **Bobo Gas** wordmark, no Sungas logo, Itele address | Bobo Gas TIN | Custom print format override applied automatically when POS Profile = Itele |

### 7.3 0 % VAT Item Tax Templates

The following Item Group hierarchies have a 0 % VAT Item Tax Template attached (so the FIRS line renders correctly):

- LPG Cylinder (Empty)
- LPG Cylinder (Filled)
- LPG Gas (Bulk)
- LPG Accessories

The same template is attached to all POS Profiles via the `taxes` child table, so it applies automatically to all POS invoices.

> If you add a **new** LPG-related Item Group, attach the existing 0 % VAT Item Tax Template manually (or re-run the `attach_zero_vat_tax_templates.py` script).

---

## 9. Inventory Operations — Purchase, Transfer, GIT, Stock Adjustment

> **⚠️ Status: NOT YET BUILT — on roadmap.** The team is currently operating these flows manually (either via standard ERPNext stock doctypes without Sungas-specific controls, or out-of-system). The customisations listed below are scheduled for Wave D-7 onward. This section documents the **target design** so finance + ops can review and confirm before build.

### 9.1 Inventory Purchase (Goods Receipt from Supplier)

**Target flow:**

1. Procurement creates **Purchase Order** (PO) — standard ERPNext.
2. When goods arrive at the outlet, the Inventory Officer creates a **Purchase Receipt** referencing the PO.
3. Purchase Receipt requires:
   - Plant Manager signature (count + condition confirmation)
   - Auto-comparison vs PO quantity → flag any shortfall
4. On submit → stock is increased in the outlet warehouse + a stock ledger entry posts.
5. Supplier Invoice is matched later (3-way match: PO ↔ Receipt ↔ Invoice).

**Approval gate (planned):** Receipts with >5 % qty variance vs PO require HOD Operations sign-off before submit.

**Status:** Standard ERPNext Purchase Receipt is usable today. Sungas-specific approval gate + variance flag = **roadmap (Wave D-7)**.

### 9.2 Inventory Transfer (Inter-Outlet, Single-Step)

**Target flow:**

1. Sending outlet creates **Stock Entry** of type **Material Transfer**.
2. Source warehouse + target warehouse selected (both must belong to same Company).
3. On submit → stock moves immediately from source to target.

**Approval gate (planned):** Transfers above a configurable value/qty threshold (e.g. 50 cylinders) require Plant Manager + HOD Operations approval before submit.

**Use case:** Short-distance same-day transfers where physical receipt at the target outlet is immediate (e.g. one Lagos outlet to another).

**Status:** Standard ERPNext Stock Entry is usable today. Approval gate = **roadmap (Wave D-7)**.

### 9.3 Goods in Transit (GIT — Two-Step Transfer)

**Target flow:**

GIT is required when a transfer spans more than a few hours (e.g. Lagos → Ogun, or any cross-state move). Stock should NOT count in the destination outlet until physically received.

1. Sending outlet creates **Stock Entry** of type **Material Transfer (In Transit)**.
   - Source warehouse: e.g. `Stores - Ikeja`
   - **In-Transit warehouse:** a dedicated warehouse per region (e.g. `GIT - Lagos`) — created during initial setup.
   - Target warehouse: e.g. `Stores - Itele`
2. On submit → stock moves Source → In-Transit. The destination outlet does **not** see it in their stock yet.
3. When the truck arrives at the destination outlet, the Inventory Officer there creates a follow-up **Stock Entry** of type **Material Receipt** referencing the first Stock Entry.
4. On submit of the receipt entry → stock moves In-Transit → Target. Destination outlet now sees the stock.

**Reconciliation:** Stock sitting in any `GIT - <region>` warehouse for > 48 hours flags an audit item. *(Planned automation: Wave D-7.)*

**Status:** ERPNext supports In-Transit warehouse natively — needs initial setup (creating GIT warehouses per region) + Sungas wrapper for the audit-trail and 48h flag = **roadmap (Wave D-7)**.

### 9.4 Stock Adjustment (Reconciliation / Damaged / Missing)

**Target flow:**

For inventory differences discovered during count (cylinders missing, damaged, expired, found):

1. **Routine cycle counts:** create a **Stock Reconciliation** entry — list items + actual counted qty per warehouse. ERPNext computes the difference and posts a JE to the Stock Adjustment account.
2. **Damaged / write-off:** create a **Stock Entry** of type **Material Issue** against the damage/scrap warehouse. Requires photographic evidence attached.
3. **Found / overage on count:** **Material Receipt** entry against the original outlet warehouse, with explanation.

**Approval gate (planned):**
- Stock variance ≤ configured threshold (e.g. 2 cylinders or NGN 30k): Plant Manager + Outlet Manager.
- Stock variance > threshold: HOD Operations + HOD Finance (per spec). Above critical threshold (e.g. 10 cylinders): COO sign-off.

**Status:** Standard ERPNext Stock Reconciliation + Stock Entry are usable today. Sungas-specific routing per the spec = **roadmap (Wave D-8)**.

### 9.5 Stock Custodian Tagging (recommended even pre-Wave D)

For every outlet warehouse, configure:

- **Default Cost Center** (so stock GL entries hit the outlet's P&L)
- **Allow to be edited only by:** Plant Manager + Inventory Officer of that outlet (use Custom DocPerm)

This guardrail prevents accidental cross-outlet stock entries even while the full approval workflow is being built.

---

## 10. Outlet Scoping (Who Sees What)

### 10.1 Cashiers

A cashier (LPG POS User) sees, in any list view (POS Opening Shift, POS Closing Shift, POS Invoice, Sales Invoice):

- Only documents whose POS Profile matches one of their assigned profiles.
- Documents they themselves authored (owner-bypass), even if profile isn't in their scope.

Scope is resolved in this order:

1. Explicit **User Permission** rows (`allow = POS Profile`).
2. Implicit via **POS Profile User** child table (if no explicit User Permission exists). This safety net prevents fail-closed denials for cashiers whose User Permission rows were never seeded.

### 10.2 Cross-outlet roles (exempt from scoping)

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

## 11. Configuration Reference

### 11.1 Sungas Close Policy (Single)

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

### 11.2 Custom DocPerm rows (POS Closing Shift)

| Role | permlevel | Read | Write | Create | Submit |
|---|---|---|---|---|---|
| LPG Head of Operations | 0 | ✅ | ✅ | ❌ | ❌ |
| LPG Head of Operations | 1 | ✅ | ✅ | ❌ | ❌ |

Permlevel-1 wraps the `variance_approved_by` and `variance_je` fields so only approvers can edit/clear them.

### 11.3 Custom fields on POS Closing Shift

| Field | Type | Permlevel | Purpose |
|---|---|---|---|
| `variance_remarks` | Long Text | 0 | Cashier's explanation |
| `variance_approved_by` | Link (User) | 1 | Set by approver |
| `variance_je` | Link (Journal Entry) | 1 | Back-link to auto-posted JE |

---

## 12. Troubleshooting

### 12.1 Cashier sees "Not allowed via controller permission check"

**Cause:** Their POS Profile assignment is missing from both User Permission and POS Profile User child table.

**Fix:** Add them to the POS Profile's **Applicable Users** table. After the next page load (or logout/login), they have access via the implicit-scope fallback.

### 12.2 Cashier submits a shift with variance but no JE was posted

**Cause 1:** `cashier_recovery_account` (or `overage_suspense_account`) isn't set on Sungas Close Policy for the company in question.

**Fix:** Set it. Then either re-trigger submission or post the JE manually (one-off).

**Cause 2:** The Cash MoP on the POS Profile has no default account for the company.

**Fix:** Open Mode of Payment → Cash → Accounts table → ensure a row exists for the company with the right Cash GL account.

### 12.3 Approver dropdown shows all users (not just approver-role users)

**Cause:** Client script didn't load (browser cache).

**Fix:** Hard refresh (Ctrl+Shift+R). If still wrong, check `sungas/public/js/pos_closing_shift.js` is deployed.

### 12.4 Draft disappeared after a blocked submit

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

## 13. Known Gaps vs. Full Spec (Build Roadmap)

The following items from the agreed operations protocol are **not yet implemented** and are tracked for upcoming waves:

### Wave D (next sprint)
- **D-1: Sequential workflow doctype** for POS Closing Shift: Draft → Plant Manager → HOD Ops (Hard) → HOD Finance (Critical / Path B) → Submitted, with optional COO sign-off.
- **D-2: Open Shift Age escalation scheduler** — Brevo emails at 24h (cashier + Outlet Manager), 48h (HOD Ops + HOD Finance, with audit comment on shift doc), 7d (MD + Internal Audit, suspend shift creation on profile).
- **D-3: 48h SLA timer** from variance detection — auto-escalate to Path C investigation track if HOD Finance hasn't acted.
- **D-4: Outlet Manager signature field** on Path A (soft variance), and **COO sign-off field** at the top of the approval chain.
- **D-5: Annex T-07 worksheet doctype** — structured variance documentation (replaces free-text `variance_remarks` for hard variances).
- **D-6: Returns / refund approval gate** in POS Awesome — manager PIN above configurable threshold (currently no enforcement; any cashier can refund).
- **D-7: Inventory Purchase / Transfer / GIT routing** — Sungas-specific approval gates on Purchase Receipt, Stock Entry (Material Transfer + In-Transit). See §9.
- **D-8: Stock Adjustment routing** — Plant Manager / HOD Ops / HOD Finance / COO gates per variance band on Stock Reconciliation + Stock Entry (Material Issue). See §9.4.

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
- **Stock Recon Unit Variance** routing → HOD Operations + HOD Finance approval gate (covered by D-8 above).
- **Customer Facing Screen** (dual-screen display for POS Awesome).
- **GIT 48h audit flag** — automated email if any region's In-Transit warehouse holds stock for > 48 hours.

---

## 14. Quick Reference — URLs

| Purpose | URL |
|---|---|
| POS Awesome (cashier UI) | `/posawesome` |
| Pending closing shifts (approvers) | `/app/pos-closing-shift?docstatus=0` |
| Close Policy configuration | `/app/sungas-close-policy` |
| LPG Outlet Price Tier matrix | `/app/lpg-outlet-price-tier` |
| Price Change Requests (PCR) | `/app/lpg-price-change-request` |
| Stock Entries | `/app/stock-entry` |
| Stock Reconciliation | `/app/stock-reconciliation` |
| Purchase Receipts | `/app/purchase-receipt` |
| Recently posted variance JEs | `/app/journal-entry?title=%25Cash%20Sho%25` |
| User Permissions (scoping admin) | `/app/user-permission` |
| Role list | `/app/role` |

---

## 15. Support & Escalation

- **POS / variance issues:** Contact your Plant Manager first. If unresolved within 4 hours, escalate to HOD Ops (Femi).
- **Pricing issues / tier disputes:** Head of Sales first, then HOD Finance.
- **Stock / inventory issues:** Plant Manager → HOD Operations.
- **Account / ledger issues:** HOD Finance.
- **System / config issues:** System Administrator.
- **Suspected fraud:** Follow Path C protocol — COO must be informed within 4 hours.

---

*End of Manual v1.1. Generated from the current Sungas deployment state. Sections 1–8 and 10–12 document live functionality; §9 documents the inventory operations design (not yet built); §13 lists the roadmap. Next revision (v1.2) will land with Wave D-1 (sequential workflow + escalation scheduler).*
