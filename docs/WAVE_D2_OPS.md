# Wave D-2 — Open Shift Age Escalation (Operations Note)

**Status:** Shipped — daily cron `0 7 * * *` (07:00 UTC = 08:00 WAT).

## What it does

Once per day, before shop open, the scheduler scans every `POS Opening Shift`
with `status = 'Open'` and `period_start_date <= now - L1_threshold`. For each
overdue shift it determines the highest tier it qualifies for and dispatches a
Brevo transactional email — **once per tier**.

| Tier | Default Threshold | Recipients |
|------|-------------------|------------|
| L1   | 24 h              | Outlet Manager — POS Profile → `outlet_manager` (**same person as the Plant Manager**, exposed under a cashier-friendly label) |
| L2   | 48 h              | + everyone with role `LPG Head of Operations` |
| L3   | 168 h (7 days)    | + everyone with role `LPG Head of Finance` |

Thresholds and enable/disable are configurable in **Sungas Close Policy**:
`escalation_enabled`, `escalation_l1_hours`, `escalation_l2_hours`,
`escalation_l3_hours`.

## Performance footprint

- **1 query/day**, indexed on `(status, period_start_date)`.
- Hard cap of 200 rows/run; warning logged at ≥100 rows.
- Per-run cache for role recipient lookups (O(roles) not O(shifts)).
- Brevo calls isolated per shift — a flaky provider never breaks the cron.
- Runs at 07:00 UTC before shop open → zero overlap with POS load.

## Idempotency

Each `POS Opening Shift` carries two read-only fields populated by the cron:

- `escalation_level_sent` — last tier (in hours) already notified.
- `last_escalation_sent_at` — audit timestamp.

The next tier only fires when the shift crosses the next threshold. We never
re-spam the same tier even if Brevo returns a transient 5xx (the failure is
logged to **Error Log** instead).

## Manual operations

```bash
# Safe probe — counts only, no emails sent.
bench --site <site> execute sungas.scheduled_jobs.shift_age_escalation.run \
  --kwargs "{'dry_run': True}"

# Real run (also runs automatically via cron).
bench --site <site> execute sungas.scheduled_jobs.shift_age_escalation.run
```

## Verification snippet (paste into `bench --site <site> console`)

```python
import frappe, json
from sungas.scheduled_jobs.shift_age_escalation import run

# 1) Inspect overdue queue without sending
print(json.dumps(run(dry_run=True), indent=2, default=str))

# 2) Recipients sanity check for a specific outlet
profile = "<your POS Profile name>"
outlet_mgr = frappe.db.get_value("POS Profile", profile, "outlet_manager")
print("Outlet Manager for", profile, "->", outlet_mgr)

# 3) Brevo key wired?
print("brevo_api_key present:", bool(frappe.conf.get("brevo_api_key")))
```

## Reset markers for a shift (admin tool)

If you need to re-trigger an escalation (e.g. address bounced):

```python
frappe.db.set_value("POS Opening Shift", "<shift name>", {
    "escalation_level_sent": 0,
    "last_escalation_sent_at": None,
}, update_modified=False)
frappe.db.commit()
```

## Configuration checklist (one-time)

- [ ] `bench set-config -g brevo_api_key xxxxxxx` (already done).
- [ ] Optional: `bench set-config -g brevo_sender_email no-reply@sungas.org`.
- [ ] Optional: `bench set-config -g brevo_sender_name "Sungas ERP"`.
- [ ] On every active POS Profile, set the `outlet_manager` field.
- [ ] Confirm at least one User holds `LPG Head of Operations`.
- [ ] Confirm at least one User holds `LPG Head of Finance`.
- [ ] `bench --site <site> migrate` to install custom fields.
- [ ] `bench --site <site> scheduler resume` if it was paused.
