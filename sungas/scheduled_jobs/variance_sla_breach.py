"""sungas.scheduled_jobs.variance_sla_breach
=============================================

Wave D-3 — 48h SLA timer for stuck variance approvals.

Runs once daily at **08:30 UTC (09:30 WAT)**, 90 minutes after the open-shift
escalation cron, to flag any `POS Closing Shift` that has sat in a
``Pending *`` workflow state past the SLA threshold.

Two escalation tiers (configurable in **Sungas Close Policy**):

    L1 — `variance_sla_hours` (default 48h)
         Notifies the role that owns the current Pending state +
         Outlet Manager (== Plant Manager — same human).

    L2 — `variance_sla_breach_hours` (default 72h)
         Adds HOD Operations and HOD Finance. Marks the shift's
         ``variance_sla_escalation_level = 2``. This is the hand-off cue
         for **Wave E (Path C fraud protocol)** when it ships — until then
         the breach is captured on the doc and broadcast by email.

Performance footprint:

    1. Single indexed query/day, filtered by docstatus=0 + workflow_state LIKE.
    2. Idempotent via ``variance_sla_escalation_level`` (never re-spams a tier).
    3. Hard cap of 200 rows/run; alert logged at >= 50 rows.
    4. Brevo failures isolated per shift; cron never breaks.

Manual probe::

    bench --site <site> execute sungas.scheduled_jobs.variance_sla_breach.run \\
        --kwargs "{'dry_run': True}"
"""

from __future__ import annotations

from typing import Any

import frappe  # type: ignore
from frappe.utils import get_datetime, now_datetime

from sungas.overrides.variance_sla import list_breached_shifts
from sungas.utils.brevo import send_transactional_email


ALERT_THRESHOLD = 50


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> dict[str, Any]:
    """Scheduled cron entry — escalate stuck variance approvals."""
    policy = frappe.get_single("Sungas Close Policy")
    if not policy.get("variance_sla_enabled"):
        return {"checked": 0, "sent": 0, "skipped": "sla_disabled"}

    sla_hours = int(policy.get("variance_sla_hours") or 48)
    breach_hours = int(policy.get("variance_sla_breach_hours") or 72)
    if breach_hours < sla_hours:
        breach_hours = sla_hours  # defensive against admin mis-config

    rows = list_breached_shifts(sla_hours=sla_hours, breach_hours=breach_hours)

    if len(rows) >= ALERT_THRESHOLD:
        frappe.log_error(
            f"variance_sla_breach: {len(rows)} stuck variance approvals — operational backlog.",
            "Sungas Variance SLA Alert",
        )

    now = now_datetime()
    role_cache: dict[str, list[dict[str, str]]] = {}
    sent_count = 0

    for r in rows:
        try:
            entered_at = get_datetime(r.variance_state_entered_at)
            age_hours = (now - entered_at).total_seconds() / 3600.0
            level_due = 2 if age_hours >= breach_hours else 1

            if int(r.variance_sla_escalation_level or 0) >= level_due:
                continue

            _send_breach(
                shift=r,
                level=level_due,
                age_hours=age_hours,
                sla_hours=sla_hours,
                breach_hours=breach_hours,
                role_cache=role_cache,
                dry_run=dry_run,
            )
            sent_count += 1
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"variance_sla_breach: failed for {r.name}",
            )

    if not dry_run:
        frappe.db.commit()

    return {
        "checked": len(rows),
        "sent": sent_count,
        "sla_hours": sla_hours,
        "breach_hours": breach_hours,
        "dry_run": dry_run,
    }


@frappe.whitelist()
def dry_run() -> dict[str, Any]:
    """Whitelisted probe — counts only, no emails sent."""
    frappe.only_for(["System Manager", "Accounts Manager", "LPG Head of Operations"])
    return run(dry_run=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Mapping: workflow state → role that should be pinged for an L1 breach.
PENDING_STATE_ROLE = {
    "Pending Plant Manager": "LPG Plant Manager",
    "Pending HOD Operations": "LPG Head of Operations",
    "Pending HOD Finance": "LPG Head of Finance",
    "Pending COO": "LPG Chief Operating Officer",
}


def _send_breach(
    *,
    shift: dict,
    level: int,
    age_hours: float,
    sla_hours: int,
    breach_hours: int,
    role_cache: dict[str, list[dict[str, str]]],
    dry_run: bool,
) -> None:
    recipients = _resolve_recipients(shift, level, role_cache)
    if not recipients:
        frappe.log_error(
            f"variance_sla_breach: no recipients for {shift.name} L{level} state={shift.workflow_state}",
            "Sungas Variance SLA",
        )
        if not dry_run:
            _mark_escalated(shift.name, level)
        return

    subject, html = _render_email(
        shift=shift,
        level=level,
        age_hours=age_hours,
        sla_hours=sla_hours,
        breach_hours=breach_hours,
    )

    if dry_run:
        frappe.logger().info(
            f"[DRY-RUN] variance SLA L{level} for {shift.name} → {[r['email'] for r in recipients]}"
        )
        return

    result = send_transactional_email(
        to=recipients,
        subject=subject,
        html_content=html,
        tags=["sungas-variance-sla", f"L{level}"],
    )
    _mark_escalated(shift.name, level)

    if not result["ok"]:
        frappe.log_error(
            f"variance_sla_breach: Brevo failed for {shift.name} L{level}: {result.get('error')}",
            "Sungas Variance SLA",
        )


def _mark_escalated(shift_name: str, level: int) -> None:
    frappe.db.set_value(
        "POS Closing Shift",
        shift_name,
        {
            "variance_sla_escalation_level": level,
            "variance_sla_escalated_at": now_datetime(),
        },
        update_modified=False,
    )


def _resolve_recipients(
    shift: dict,
    level: int,
    cache: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    """Build recipient list for the breach tier."""
    bucket: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(rec: dict[str, str] | None) -> None:
        if rec and rec["email"] not in seen:
            bucket.append(rec)
            seen.add(rec["email"])

    # Plant Manager from the POS Profile (== Outlet Manager).
    _add(_outlet_manager(shift.pos_profile, cache))

    # Owner-role of the current Pending state.
    pending_role = PENDING_STATE_ROLE.get(shift.workflow_state)
    if pending_role:
        for rec in _role_recipients(pending_role, cache):
            _add(rec)

    if level >= 2:
        for role in ("LPG Head of Operations", "LPG Head of Finance"):
            for rec in _role_recipients(role, cache):
                _add(rec)

    return bucket


def _outlet_manager(pos_profile: str | None, cache: dict[str, list[dict[str, str]]]) -> dict[str, str] | None:
    if not pos_profile:
        return None
    key = f"outlet_mgr::{pos_profile}"
    if key in cache:
        return cache[key][0] if cache[key] else None

    user_id = frappe.db.get_value("POS Profile", pos_profile, "outlet_manager")
    if not user_id:
        cache[key] = []
        return None
    full_name = frappe.db.get_value("User", user_id, "full_name") or user_id
    rec = {"email": user_id, "name": full_name}
    cache[key] = [rec]
    return rec


def _role_recipients(role: str, cache: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    key = f"role::{role}"
    if key in cache:
        return cache[key]

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
    recipients = [{"email": r["email"], "name": r["full_name"] or r["email"]} for r in rows if r["email"]]
    cache[key] = recipients
    return recipients


def _render_email(
    *,
    shift: dict,
    level: int,
    age_hours: float,
    sla_hours: int,
    breach_hours: int,
) -> tuple[str, str]:
    tier_label = "L1 — SLA Warning" if level == 1 else "L2 — SLA BREACH"
    threshold = sla_hours if level == 1 else breach_hours

    site_url = frappe.utils.get_url()
    shift_url = f"{site_url}/app/pos-closing-shift/{shift.name}"

    subject = (
        f"[Sungas] {tier_label} — Variance approval stuck >{threshold}h "
        f"({shift.workflow_state}) — {shift.name}"
    )

    color = "#ca8a04" if level == 1 else "#b91c1c"

    html = f"""
    <div style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; color:#1f2937; max-width:560px;">
      <h2 style="color:{color}; margin:0 0 8px 0;">Variance Approval SLA — {tier_label}</h2>
      <p style="margin:0 0 16px 0;">A POS Closing Shift variance approval has been
      sitting in <strong>{shift.workflow_state}</strong> for more than
      <strong>{threshold} hours</strong>.</p>

      <table style="border-collapse:collapse; width:100%; margin-bottom:16px;">
        <tr><td style="padding:6px 0; color:#6b7280;">Shift</td>
            <td style="padding:6px 0;"><strong>{shift.name}</strong></td></tr>
        <tr><td style="padding:6px 0; color:#6b7280;">Outlet (POS Profile)</td>
            <td style="padding:6px 0;">{shift.pos_profile or '—'}</td></tr>
        <tr><td style="padding:6px 0; color:#6b7280;">Severity</td>
            <td style="padding:6px 0;">{shift.variance_severity or '—'}</td></tr>
        <tr><td style="padding:6px 0; color:#6b7280;">Workflow State</td>
            <td style="padding:6px 0;">{shift.workflow_state}</td></tr>
        <tr><td style="padding:6px 0; color:#6b7280;">Time in state</td>
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
        Configure thresholds in <em>Sungas Close Policy → Variance Approval SLA</em>.
      </p>
    </div>
    """.strip()

    return subject, html
