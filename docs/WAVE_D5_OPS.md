# Wave D-5 — Annex T-07 Worksheet (Operations Note)

**Status:** Shipped — structured variance documentation now required for every block/critical closing shift.

## What it does

The free-text `variance_remarks` field on POS Closing Shift was OK for soft
variances but inadequate for the regulatory paper-trail needed on hard
variances. Annex T-07 replaces it for **block** and **critical** tiers with
a structured submittable doctype that captures:

| Section | What it captures |
|---------|------------------|
| Identification | Auto-fetched from the linked shift: outlet, cashier, period_end_date, severity, variance amount |
| Cash Count by Denomination | Per-NGN-denom row: expected count, actual count, expected/actual/variance values |
| Cause Taxonomy | Single-select primary cause (9 options + "Other" with mandatory detail), plus contributing factors and corrective action |
| Evidence | Cashier statement (mandatory) + native Frappe File Attachments for till photos, deposit slips, CCTV stills |
| Sign-offs | Cashier (auto on submit), Plant Manager, HOD Operations, HOD Finance — each with a notes field + timestamped signature |

## Workflow integration

1. **Auto-create:** the moment a shift's `variance_severity` becomes
   `block` or `critical` (validated server-side), the `on_update` hook
   `sungas.overrides.annex_t07_integration.auto_create_t07` spawns an
   empty draft Annex T-07 Worksheet linked back to the shift via the new
   `annex_t07` field. Idempotent — never duplicates.

2. **Cashier fills it in** before the shift is approved. The worksheet's
   own `validate` recomputes denomination math and ensures the cash-count
   total variance reconciles to the shift's `variance_amount` within
   **NGN 1.00 tolerance** (a tighter recount gate than the legacy
   `variance_remarks` ever provided).

3. **Submission gate:** `sungas.overrides.annex_t07_integration.require_t07_for_hard_variance`
   is chained as a `before_submit` hook on the closing shift. If
   severity is block/critical AND the linked T-07 is missing or
   docstatus≠1, the shift submit is rejected with a clear message.

4. **Role sign-offs** are stamped via a small whitelisted helper
   `sungas.sungas.doctype.annex_t07_worksheet.annex_t07_worksheet.stamp_role_signoff`
   that workflow client scripts can call at each Plant Mgr / HOD Ops /
   HOD Finance transition. The doctype itself enforces `permlevel=0` on
   the sign-off blocks so only roles with that permission can write.

## Reconciliation safety net

The most common reason a cash count looks "right" but the GL is "wrong"
is that the cashier counted the float into a different till or used a
wrong opening balance. Annex T-07's `_reconcile_with_shift` hard-stops
submission if the worksheet's `total_variance` and the shift's
`variance_amount` disagree by more than NGN 1.00.

If you genuinely have rounding noise (e.g. NGN 0.50 coin denominations),
edit the constant in
`sungas/sungas/doctype/annex_t07_worksheet/annex_t07_worksheet.py` ::
`RECONCILIATION_TOLERANCE`.

## Cause taxonomy (current canonical list)

```
Wrong change given
Customer dispute (refund pending)
Theft (suspected)
Cash drop missing / unaccounted
Counterfeit notes accepted
System error (POS / cash float misconfig)
Deposit mis-counted at bank
Float handover error
Other  (mandatory detail field)
```

Add or remove options by editing the `primary_cause` field options in
`annex_t07_worksheet.json` and running `bench --site <site> migrate`.

## Print Format (follow-on)

Not shipped in this wave. The doctype is ready for a Standard print
format — wire one up from Desk → Print Format → New → Doctype =
"Annex T-07 Worksheet". For audit archives consider a dedicated
letterhead layout with one section per signature block.

## Migrate / verify on Frappe Cloud

```bash
bench --site sungasmis.v.frappe.cloud migrate
```

Then in `bench console`:

```python
import frappe, json
print("DocType present:", bool(frappe.db.exists("DocType", "Annex T-07 Worksheet")))
print("Child DocType present:", bool(frappe.db.exists("DocType", "Annex T-07 Denomination Row")))
print("annex_t07 link field:", bool(frappe.db.exists("Custom Field", "POS Closing Shift-annex_t07")))

# Smoke: create a draft worksheet against an existing shift (no submit).
from frappe import _
existing_shift = frappe.db.get_value("POS Closing Shift",
    {"variance_severity": ["in", ["block", "critical"]]}, "name")
print("Sample hard shift:", existing_shift)

if existing_shift:
    annex = frappe.db.get_value("POS Closing Shift", existing_shift, "annex_t07")
    print("Linked T-07:", annex)
```

## Backward compatibility

- Shifts already submitted (e.g. `POSA-CS-26-0000012`) are NOT retroactively
  required to have a T-07 — the gate fires on `before_submit`, not on the
  existing submitted document.
- Soft / no-variance shifts continue to submit freely with no T-07.
- If you legitimately need to backdate the requirement onto historical
  shifts for audit, create T-07 worksheets manually and link them via
  `frappe.db.set_value("POS Closing Shift", "<name>", "annex_t07", "<at07>")`.
