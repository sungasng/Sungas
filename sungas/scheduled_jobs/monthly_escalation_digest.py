"""sungas.scheduled_jobs.monthly_escalation_digest
===================================================

Wave B-11 — Monthly Escalation Digest.

Runs on the **1st of every month at 09:00 UTC** and emails a single
HTML digest to HOD Operations + HOD Finance summarising the escalations
fired by the D-2 (Open Shift Age) and D-3 (Variance SLA) schedulers
during the *previous calendar month*.

Sections in the digest:

  1. Open-Shift Age Escalations — count by outlet × tier (L1/L2/L3)
  2. Variance Approval SLA Breaches — count by outlet × tier (L1/L2)
  3. Top Offenders — outlets with the highest combined escalation count
  4. Snapshot of current backlog — open shifts already stale TODAY,
     variance approvals still sitting in Pending states

Performance footprint:
  * 4 indexed queries/month (negligible)
  * One Brevo call per recipient bucket
  * No new fields introduced — reuses the idempotency markers stamped
    by the D-2 and D-3 hooks

Manual probe (dry run, no email)::

    bench --site <site> execute sungas.scheduled_jobs.monthly_escalation_digest.run \\
        --kwargs "{'dry_run': True}"
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import frappe  # type: ignore
from frappe.utils import now_datetime

from sungas.utils.brevo import send_transactional_email


DIGEST_RECIPIENT_ROLES = ("LPG Head of Operations", "LPG Head of Finance")


def run(dry_run: bool = False) -> dict[str, Any]:
    """Scheduled monthly cron entry."""
    period_start, period_end = _previous_calendar_month()

    open_shift_rows = _query_open_shift_escalations(period_start, period_end)
    variance_rows = _query_variance_sla_breaches(period_start, period_end)
    backlog = _current_backlog_snapshot()

    summary = {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "open_shift_total": sum(r["n"] for r in open_shift_rows),
        "variance_total": sum(r["n"] for r in variance_rows),
        "backlog": backlog,
        "dry_run": dry_run,
    }

    recipients = _recipients()
    summary["recipients_count"] = len(recipients)

    if summary["open_shift_total"] == 0 and summary["variance_total"] == 0 \
            and backlog["stale_open_shifts"] == 0 and backlog["pending_variances"] == 0:
        summary["skipped"] = "no_activity"
        return summary

    if not recipients:
        frappe.log_error(
            "monthly_escalation_digest: no users hold the recipient roles — "
            f"{DIGEST_RECIPIENT_ROLES}",
            "Sungas Monthly Digest",
        )
        summary["skipped"] = "no_recipients"
        return summary

    subject, html = _render(
        period_start=period_start,
        period_end=period_end,
        open_shift_rows=open_shift_rows,
        variance_rows=variance_rows,
        backlog=backlog,
    )

    if dry_run:
        summary["preview_subject"] = subject
        summary["preview_recipients"] = [r["email"] for r in recipients]
        return summary

    result = send_transactional_email(
        to=recipients,
        subject=subject,
        html_content=html,
        tags=["sungas-monthly-digest"],
    )
    summary["brevo_ok"] = result["ok"]
    if not result["ok"]:
        frappe.log_error(
            f"monthly_escalation_digest: Brevo failed: {result.get('error')}",
            "Sungas Monthly Digest",
        )
    return summary


@frappe.whitelist()
def dry_run() -> dict[str, Any]:
    """Whitelisted manual probe."""
    frappe.only_for(["System Manager", "Accounts Manager", "LPG Head of Operations"])
    return run(dry_run=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _previous_calendar_month() -> tuple[date, date]:
    today = now_datetime().date()
    # First day of this month, minus one day -> last day of previous month
    first_this_month = today.replace(day=1)
    period_end = first_this_month - timedelta(days=1)
    period_start = period_end.replace(day=1)
    return period_start, period_end


def _query_open_shift_escalations(period_start: date, period_end: date) -> list[dict[str, Any]]:
    rows = frappe.db.sql(
        """
        SELECT pos_profile, escalation_level_sent AS tier, COUNT(*) AS n
        FROM `tabPOS Opening Shift`
        WHERE escalation_level_sent > 0
          AND last_escalation_sent_at >= %(start)s
          AND last_escalation_sent_at < %(end_plus_1)s
        GROUP BY pos_profile, escalation_level_sent
        ORDER BY n DESC
        """,
        {"start": period_start, "end_plus_1": period_end + timedelta(days=1)},
        as_dict=True,
    )
    return rows


def _query_variance_sla_breaches(period_start: date, period_end: date) -> list[dict[str, Any]]:
    rows = frappe.db.sql(
        """
        SELECT pos_profile, variance_sla_escalation_level AS tier, COUNT(*) AS n
        FROM `tabPOS Closing Shift`
        WHERE COALESCE(variance_sla_escalation_level, 0) > 0
          AND variance_sla_escalated_at >= %(start)s
          AND variance_sla_escalated_at < %(end_plus_1)s
        GROUP BY pos_profile, variance_sla_escalation_level
        ORDER BY n DESC
        """,
        {"start": period_start, "end_plus_1": period_end + timedelta(days=1)},
        as_dict=True,
    )
    return rows


def _current_backlog_snapshot() -> dict[str, int]:
    stale_open = frappe.db.count("POS Opening Shift", {"status": "Open"})
    pending_variance = frappe.db.sql(
        """
        SELECT COUNT(*) FROM `tabPOS Closing Shift`
        WHERE docstatus = 0 AND workflow_state LIKE 'Pending%%'
        """
    )[0][0]
    return {
        "stale_open_shifts": int(stale_open or 0),
        "pending_variances": int(pending_variance or 0),
    }


def _recipients() -> list[dict[str, str]]:
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name AS email, u.full_name
        FROM `tabUser` u
        INNER JOIN `tabHas Role` r ON r.parent = u.name
        WHERE u.enabled = 1
          AND r.role IN %(roles)s
          AND u.name NOT IN ('Administrator', 'Guest')
        """,
        {"roles": tuple(DIGEST_RECIPIENT_ROLES)},
        as_dict=True,
    )
    return [
        {"email": r["email"], "name": r["full_name"] or r["email"]}
        for r in rows
        if r["email"]
    ]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render(
    *,
    period_start: date,
    period_end: date,
    open_shift_rows: list[dict[str, Any]],
    variance_rows: list[dict[str, Any]],
    backlog: dict[str, int],
) -> tuple[str, str]:
    month_label = period_start.strftime("%B %Y")
    subject = f"[Sungas] Monthly Escalation Digest — {month_label}"

    open_table = _open_shift_table(open_shift_rows)
    variance_table = _variance_table(variance_rows)
    top_offenders = _top_offenders_table(open_shift_rows, variance_rows)

    site_url = frappe.utils.get_url()
    backlog_color = "#b91c1c" if backlog["stale_open_shifts"] or backlog["pending_variances"] else "#0a7"

    html = f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1f2937;max-width:680px;">
      <h1 style="font-size:20px;margin:0 0 4px 0;color:#111827;">Monthly Escalation Digest</h1>
      <p style="margin:0 0 16px 0;color:#6b7280;">
        Period: <strong>{period_start.strftime('%d %b %Y')} — {period_end.strftime('%d %b %Y')}</strong>
      </p>

      <div style="background:#fafafa;border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px;margin-bottom:18px;">
        <p style="margin:0;color:#374151;">
          <strong>{sum(r['n'] for r in open_shift_rows)}</strong> open-shift age escalations fired ·
          <strong>{sum(r['n'] for r in variance_rows)}</strong> variance SLA breaches ·
          <span style="color:{backlog_color}"><strong>{backlog['stale_open_shifts']}</strong> open shifts &amp;
          <strong>{backlog['pending_variances']}</strong> variances are currently overdue.</span>
        </p>
      </div>

      <h2 style="font-size:14px;margin:18px 0 6px 0;color:#111827;border-bottom:2px solid #111827;padding-bottom:4px;text-transform:uppercase;letter-spacing:.5px;">
        1 · Open-Shift Age Escalations (D-2)
      </h2>
      {open_table}

      <h2 style="font-size:14px;margin:24px 0 6px 0;color:#111827;border-bottom:2px solid #111827;padding-bottom:4px;text-transform:uppercase;letter-spacing:.5px;">
        2 · Variance Approval SLA Breaches (D-3)
      </h2>
      {variance_table}

      <h2 style="font-size:14px;margin:24px 0 6px 0;color:#111827;border-bottom:2px solid #111827;padding-bottom:4px;text-transform:uppercase;letter-spacing:.5px;">
        3 · Top Offenders
      </h2>
      {top_offenders}

      <p style="margin:24px 0 0 0;font-size:11px;color:#9ca3af;text-align:center;">
        Generated by Sungas Operations Engine ·
        <a href="{site_url}" style="color:#9ca3af;">{site_url}</a>
      </p>
    </div>
    """.strip()

    return subject, html


def _open_shift_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return _empty_table_msg("No open-shift age escalations fired this month.")
    by_outlet: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_outlet[r["pos_profile"] or "—"][int(r["tier"])] += int(r["n"])

    tier_label = {24: "L1 (24h)", 48: "L2 (48h)", 168: "L3 (7d)"}
    body = []
    for outlet in sorted(by_outlet):
        cells = by_outlet[outlet]
        row = [f"<td style='padding:6px 10px;border:1px solid #e5e7eb;'>{outlet}</td>"]
        for t in (24, 48, 168):
            n = cells.get(t, 0)
            row.append(
                f"<td style='padding:6px 10px;border:1px solid #e5e7eb;text-align:right;"
                f"{'color:#b91c1c;font-weight:600;' if n else 'color:#9ca3af;'}'>{n or '·'}</td>"
            )
        body.append("<tr>" + "".join(row) + "</tr>")
    header = (
        "<thead><tr>"
        "<th style='padding:6px 10px;border:1px solid #e5e7eb;background:#f9fafb;text-align:left;'>Outlet</th>"
        + "".join(
            f"<th style='padding:6px 10px;border:1px solid #e5e7eb;background:#f9fafb;text-align:right;'>{tier_label[t]}</th>"
            for t in (24, 48, 168)
        )
        + "</tr></thead>"
    )
    return f"<table style='border-collapse:collapse;width:100%;font-size:12px;'>{header}<tbody>{''.join(body)}</tbody></table>"


def _variance_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return _empty_table_msg("No variance SLA breaches this month.")
    by_outlet: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_outlet[r["pos_profile"] or "—"][int(r["tier"])] += int(r["n"])
    tier_label = {1: "L1 Warning", 2: "L2 Breach"}
    body = []
    for outlet in sorted(by_outlet):
        cells = by_outlet[outlet]
        row = [f"<td style='padding:6px 10px;border:1px solid #e5e7eb;'>{outlet}</td>"]
        for t in (1, 2):
            n = cells.get(t, 0)
            row.append(
                f"<td style='padding:6px 10px;border:1px solid #e5e7eb;text-align:right;"
                f"{'color:#b91c1c;font-weight:600;' if n else 'color:#9ca3af;'}'>{n or '·'}</td>"
            )
        body.append("<tr>" + "".join(row) + "</tr>")
    header = (
        "<thead><tr>"
        "<th style='padding:6px 10px;border:1px solid #e5e7eb;background:#f9fafb;text-align:left;'>Outlet</th>"
        + "".join(
            f"<th style='padding:6px 10px;border:1px solid #e5e7eb;background:#f9fafb;text-align:right;'>{tier_label[t]}</th>"
            for t in (1, 2)
        )
        + "</tr></thead>"
    )
    return f"<table style='border-collapse:collapse;width:100%;font-size:12px;'>{header}<tbody>{''.join(body)}</tbody></table>"


def _top_offenders_table(
    open_shift_rows: list[dict[str, Any]],
    variance_rows: list[dict[str, Any]],
) -> str:
    combined: dict[str, int] = defaultdict(int)
    for r in open_shift_rows:
        combined[r["pos_profile"] or "—"] += int(r["n"])
    for r in variance_rows:
        combined[r["pos_profile"] or "—"] += int(r["n"])
    if not combined:
        return _empty_table_msg("No outlets escalated this month.")
    top = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:5]
    body = []
    for outlet, n in top:
        body.append(
            f"<tr><td style='padding:6px 10px;border:1px solid #e5e7eb;'>{outlet}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb;text-align:right;"
            f"color:#b91c1c;font-weight:600;'>{n}</td></tr>"
        )
    header = (
        "<thead><tr>"
        "<th style='padding:6px 10px;border:1px solid #e5e7eb;background:#f9fafb;text-align:left;'>Outlet</th>"
        "<th style='padding:6px 10px;border:1px solid #e5e7eb;background:#f9fafb;text-align:right;'>Total Escalations</th>"
        "</tr></thead>"
    )
    return f"<table style='border-collapse:collapse;width:100%;font-size:12px;'>{header}<tbody>{''.join(body)}</tbody></table>"


def _empty_table_msg(msg: str) -> str:
    return (
        f"<p style='color:#9ca3af;font-style:italic;margin:6px 0 0 0;font-size:12px;'>{msg}</p>"
    )


# `calendar` import retained for potential future use (e.g. period labels);
# silence the unused-import warning without losing the dependency.
_ = calendar
