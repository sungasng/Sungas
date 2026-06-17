# Wave D-3 — Variance Approval SLA Timer (Operations Note)

**Status:** Shipped — daily cron `30 8 * * *` (08:30 UTC = 09:30 WAT).

## What it does

Tracks how long every `POS Closing Shift` sits in a `Pending *` workflow
state. Once a day the scheduler scans for overdue approvals and fires
Brevo emails at two escalation tiers:

| Tier | Default Threshold | Recipients |
|------|-------------------|------------|
| L1 — SLA Warning | 48 h | Outlet Manager (≡ Plant Manager) + role currently owning the Pending state |
| L2 — SLA Breach  | 72 h | + everyone with role `LPG Head of Operations` + `LPG Head of Finance`. Doc is stamped `variance_sla_escalation_level=2` — the cue for **Wave E (Path C)** to take over. |

Thresholds are configurable on **Sungas Close Policy → Variance Approval SLA**:
`variance_sla_enabled`, `variance_sla_hours`, `variance_sla_breach_hours`.

## How the timer is anchored

A single `on_update` hook (`sungas.overrides.variance_sla.track_state_entry`)
fires on every `POS Closing Shift` save. It compares the new and previous
`workflow_state`:

- **Entered a Pending state** → stamp `variance_state_entered_at = now()`
  and reset the SLA escalation markers.
- **Left a Pending state** (Approved / Rejected / Draft) → clear the
  timer so stale alerts never fire.
- **No state change** → cheap no-op (one in-memory compare, zero DB writes).

## Performance footprint

- 1 indexed query/day (`docstatus=0 AND workflow_state LIKE 'Pending%' AND
  variance_state_entered_at <= cutoff`).
- Hard cap 200 rows/run; warning logged at ≥ 50 rows.
- Brevo calls isolated per shift — flaky provider never breaks the cron.
- Cron runs at 08:30 UTC (90 min after the open-shift cron) → no overlap
  with peak POS traffic.

## Idempotency

Each `POS Closing Shift` carries three read-only fields (hidden — purely
operational):

- `variance_state_entered_at` — written by the `on_update` hook.
- `variance_sla_escalation_level` — `0/1/2` (cron-owned).
- `variance_sla_escalated_at` — last broadcast timestamp.

The next tier only fires when the shift crosses the next threshold. We
never re-spam the same tier even if Brevo returns 5xx.

## Manual operations

```bash
# Safe probe — counts only, no emails sent.
bench --site <site> execute sungas.scheduled_jobs.variance_sla_breach.run \
  --kwargs "{'dry_run': True}"

# Real run (also runs automatically via cron).
bench --site <site> execute sungas.scheduled_jobs.variance_sla_breach.run
```

## Verification snippet (paste into `bench --site <site> console`)

```python
import frappe, json
from sungas.scheduled_jobs.variance_sla_breach import run
from sungas.overrides.variance_sla import list_breached_shifts

print(json.dumps(run(dry_run=True), indent=2, default=str))
print("Breached >48h:", len(list_breached_shifts(48, 72)))
print("Breached >72h:",
      sum(1 for r in list_breached_shifts(48, 72)
          if (frappe.utils.now_datetime() - frappe.utils.get_datetime(r.variance_state_entered_at)).total_seconds() / 3600 >= 72))
```

## Reset SLA markers for a shift (admin tool)

```python
frappe.db.set_value("POS Closing Shift", "<shift name>", {
    "variance_sla_escalation_level": 0,
    "variance_sla_escalated_at": None,
}, update_modified=False)
frappe.db.commit()
```

## Configuration checklist (one-time)

- [ ] `bench --site <site> migrate` to install custom fields.
- [ ] No other config needed — defaults are sane (48h / 72h).
- [ ] Confirm at least one User holds `LPG Plant Manager` (already true).
- [ ] Confirm at least one User holds `LPG Chief Operating Officer` — only
      required if you use the Pending COO branch. If empty the cron logs a
      "no recipients" warning for the affected shifts (rare path).
