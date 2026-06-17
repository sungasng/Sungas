"""sungas.scheduled_jobs.shift_age_escalation
==============================================

Wave D-2 — Open Shift Age escalation scheduler.

Runs once daily at **07:00 UTC (08:00 WAT)** and notifies the operations
chain when a `POS Opening Shift` has been left open beyond the configured
thresholds:

    L1 (default 24h)  -> Outlet Manager (== Plant Manager — same human, label kept
                         cashier-friendly on the POS Profile)
    L2 (default 48h)  -> Outlet Manager + HOD Operations
    L3 (default 168h) -> Outlet Manager + HOD Operations + HOD Finance

Performance safeguards (see ROADMAP "Wave D-2"):

    1. Single indexed query (status='Open' AND period_start_date <= cutoff).
    2. Idempotent: each opening shift carries `escalation_level_sent`;
       once a tier is sent we never resend the same tier.
    3. Brevo failures are logged but never break the cron — each shift is
       wrapped in its own try/except.
    4. Hard cap of 200 rows per pass; if >= 100 overdue shifts we emit an
       Error Log entry so HOD Ops can investigate the operational backlog.
    5. Recipient resolution is cached per run (HOD role lookups are O(1)).
    6. Cron runs BEFORE shop open (07:00 UTC) so no overlap with POS load.

Manual invocation::

    bench --site <site> execute sungas.scheduled_jobs.shift_age_escalation.run
    bench --site <site> execute sungas.scheduled_jobs.shift_age_escalation.run \\
        --kwargs "{'dry_run': True}"
"""

from __future__ import annotations

from typing import Any

import frappe  # type: ignore
from frappe.utils import add_to_date, get_datetime, now_datetime

from sungas.utils.brevo import send_transactional_email


# Hard cap on rows per scheduler pass to prevent runaway queries.
MAX_ROWS_PER_RUN = 200
# Threshold at which we emit an operational alert via Error Log.
ALERT_THRESHOLD = 100


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> dict[str, Any]:
    """Scheduled cron entry — process all stale Open POS Opening Shifts."""
    policy = frappe.get_single("Sungas Close Policy")
    if not policy.get("escalation_enabled"):
        return {"checked": 0, "sent": 0, "skipped": "escalation_disabled"}

    l1 = int(policy.get("escalation_l1_hours") or 24)
    l2 = int(policy.get("escalation_l2_hours") or 48)
    l3 = int(policy.get("escalation_l3_hours") or 168)
    tiers = sorted({l1, l2, l3})  # de-dupe if admin sets equal values

    now = now_datetime()
    cutoff = add_to_date(now, hours=-tiers[0], as_datetime=True)

    rows = frappe.db.sql(
        """
        SELECT name, pos_profile, user, period_start_date,
               COALESCE(escalation_level_sent, 0) AS escalation_level_sent
        FROM `tabPOS Opening Shift`
        WHERE status = 'Open'
          AND period_start_date <= %(cutoff)s
        ORDER BY period_start_date ASC
        LIMIT %(cap)s
        """,
        {"cutoff": cutoff, "cap": MAX_ROWS_PER_RUN},
        as_dict=True,
    )

    if len(rows) >= ALERT_THRESHOLD:
        frappe.log_error(
            f"shift_age_escalation: {len(rows)} overdue open shifts — investigate operational backlog.",
            "Sungas Escalation Alert",
        )

    # Per-run cache for role-based recipients so we don't hammer the user table.
    recipient_cache: dict[str, list[dict[str, str]]] = {}
    sent_count = 0

    for r in rows:
        try:
            age_hours = (now - get_datetime(r.period_start_date)).total_seconds() / 3600.0
            level_due = _level_due(age_hours, tiers)
            if not level_due or int(r.escalation_level_sent or 0) >= level_due:
                continue

            _send_escalation(
                opening_shift=r,
                level_hours=level_due,
                age_hours=age_hours,
                policy=policy,
                recipient_cache=recipient_cache,
                dry_run=dry_run,
            )
            sent_count += 1
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"shift_age_escalation: failed for {r.name}",
            )

    if not dry_run:
        frappe.db.commit()

    return {
        "checked": len(rows),
        "sent": sent_count,
        "tiers": tiers,
        "cutoff": str(cutoff),
        "dry_run": dry_run,
    }


@frappe.whitelist()
def dry_run() -> dict[str, Any]:
    """Whitelisted manual probe — does NOT send any email, only reports counts."""
    frappe.only_for(["System Manager", "Accounts Manager", "LPG Head of Operations"])
    return run(dry_run=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _level_due(age_hours: float, tiers: list[int]) -> int:
    """Return the HIGHEST tier (in hours) the shift currently qualifies for."""
    eligible = [t for t in tiers if age_hours >= t]
    return max(eligible) if eligible else 0


def _send_escalation(
    *,
    opening_shift: dict[str, Any],
    level_hours: int,
    age_hours: float,
    policy: Any,
    recipient_cache: dict[str, list[dict[str, str]]],
    dry_run: bool,
) -> None:
    """Send one escalation email and update the opening shift idempotency markers."""
    pos_profile = opening_shift.pos_profile
    recipients = _resolve_recipients(level_hours, pos_profile, policy, recipient_cache)
    if not recipients:
        frappe.log_error(
            f"No recipients resolved for {opening_shift.name} (L{level_hours}h, profile={pos_profile})",
            "Sungas Escalation",
        )
        # Still mark as sent to prevent infinite retries on misconfigured outlets.
        if not dry_run:
            _mark_sent(opening_shift.name, level_hours)
        return

    subject, html = _render_email(
        opening_shift=opening_shift,
        level_hours=level_hours,
        age_hours=age_hours,
    )

    if dry_run:
        frappe.logger().info(
            f"[DRY-RUN] would send L{level_hours}h escalation for {opening_shift.name} "
            f"to {[r['email'] for r in recipients]}"
        )
        return

    result = send_transactional_email(
        to=recipients,
        subject=subject,
        html_content=html,
        tags=["sungas-shift-escalation", f"L{level_hours}h"],
    )

    # Mark sent regardless of Brevo outcome — failures are already logged and
    # we don't want a flaky email provider to spam users on the next cron pass.
    _mark_sent(opening_shift.name, level_hours)

    if not result["ok"]:
        frappe.log_error(
            f"Brevo send failed for {opening_shift.name} L{level_hours}h: {result.get('error')}",
            "Sungas Escalation",
        )


def _mark_sent(opening_shift_name: str, level_hours: int) -> None:
    """Update idempotency fields without firing doc events (cheap UPDATE)."""
    frappe.db.set_value(
        "POS Opening Shift",
        opening_shift_name,
        {
            "escalation_level_sent": level_hours,
            "last_escalation_sent_at": now_datetime(),
        },
        update_modified=False,
    )


def _resolve_recipients(
    level_hours: int,
    pos_profile: str | None,
    policy: Any,
    cache: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    """Build the recipient bucket for a given level.

    L1 -> Outlet Manager only.
    L2 -> Outlet Manager + HOD Operations.
    L3 -> Outlet Manager + HOD Operations + HOD Finance.
    """
    l2 = int(policy.get("escalation_l2_hours") or 48)
    l3 = int(policy.get("escalation_l3_hours") or 168)

    bucket: list[dict[str, str]] = []
    seen: set[str] = set()

    outlet_mgr = _outlet_manager_recipient(pos_profile, cache)
    if outlet_mgr:
        bucket.append(outlet_mgr)
        seen.add(outlet_mgr["email"])

    if level_hours >= l2:
        for r in _role_recipients("LPG Head of Operations", cache):
            if r["email"] not in seen:
                bucket.append(r)
                seen.add(r["email"])

    if level_hours >= l3:
        for r in _role_recipients("LPG Head of Finance", cache):
            if r["email"] not in seen:
                bucket.append(r)
                seen.add(r["email"])

    return bucket


def _outlet_manager_recipient(
    pos_profile: str | None,
    cache: dict[str, list[dict[str, str]]],
) -> dict[str, str] | None:
    """Lookup the outlet_manager User for this POS Profile and return their email."""
    if not pos_profile:
        return None
    cache_key = f"outlet_mgr::{pos_profile}"
    if cache_key in cache:
        return cache[cache_key][0] if cache[cache_key] else None

    user_id = frappe.db.get_value("POS Profile", pos_profile, "outlet_manager")
    if not user_id:
        cache[cache_key] = []
        return None

    full_name = frappe.db.get_value("User", user_id, "full_name") or user_id
    rec = {"email": user_id, "name": full_name}
    cache[cache_key] = [rec]
    return rec


def _role_recipients(role: str, cache: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    """Return all enabled Users carrying the given role (cached per run)."""
    cache_key = f"role::{role}"
    if cache_key in cache:
        return cache[cache_key]

    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name AS email, u.full_name
        FROM `tabUser` u
        INNER JOIN `tabHas Role` r ON r.parent = u.name
        WHERE u.enabled = 1
          AND r.role = %(role)s
          AND u.name NOT IN ('Administrator', 'Guest')
        """,
        {"role": role},
        as_dict=True,
    )
    recipients = [
        {"email": r["email"], "name": r["full_name"] or r["email"]}
        for r in rows
        if r["email"]
    ]
    cache[cache_key] = recipients
    return recipients


def _render_email(
    *,
    opening_shift: dict[str, Any],
    level_hours: int,
    age_hours: float,
) -> tuple[str, str]:
    """Render subject + minimal inline HTML body. Kept self-contained to avoid
    a hard dependency on a Frappe Email Template doctype during early rollout."""
    tier_label = {24: "L1 — 24 Hour", 48: "L2 — 48 Hour", 168: "L3 — 7 Day"}.get(
        level_hours, f"{level_hours}h"
    )

    site_url = frappe.utils.get_url()
    shift_url = f"{site_url}/app/pos-opening-shift/{opening_shift.name}"

    subject = (
        f"[Sungas] {tier_label} Stale Open Shift Alert — {opening_shift.pos_profile or 'Outlet'} "
        f"({opening_shift.name})"
    )

    html = f"""
    <div style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; color:#1f2937; max-width:560px;">
      <h2 style="color:#b91c1c; margin:0 0 8px 0;">Stale POS Opening Shift — {tier_label}</h2>
      <p style="margin:0 0 16px 0;">A POS opening shift has been open beyond the
      <strong>{level_hours}-hour</strong> threshold and requires immediate closure.</p>

      <table style="border-collapse:collapse; width:100%; margin-bottom:16px;">
        <tr><td style="padding:6px 0; color:#6b7280;">Shift</td>
            <td style="padding:6px 0;"><strong>{opening_shift.name}</strong></td></tr>
        <tr><td style="padding:6px 0; color:#6b7280;">Outlet (POS Profile)</td>
            <td style="padding:6px 0;">{opening_shift.pos_profile or '—'}</td></tr>
        <tr><td style="padding:6px 0; color:#6b7280;">Cashier</td>
            <td style="padding:6px 0;">{opening_shift.user or '—'}</td></tr>
        <tr><td style="padding:6px 0; color:#6b7280;">Opened</td>
            <td style="padding:6px 0;">{opening_shift.period_start_date}</td></tr>
        <tr><td style="padding:6px 0; color:#6b7280;">Age</td>
            <td style="padding:6px 0;"><strong>{age_hours:.1f} hours</strong></td></tr>
      </table>

      <p style="margin:0 0 16px 0;">
        <a href="{shift_url}"
           style="background:#1f2937; color:#fff; padding:10px 18px; border-radius:6px;
                  text-decoration:none; display:inline-block;">
          Open Shift in ERPNext
        </a>
      </p>

      <p style="font-size:12px; color:#6b7280; margin:24px 0 0 0;">
        This is an automated alert from the Sungas Operations Engine.
        Configure thresholds in <em>Sungas Close Policy</em>.
      </p>
    </div>
    """.strip()

    return subject, html
