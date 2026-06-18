"""sungas.overrides.coo_notification
=====================================

Wave D-4: COO informational notification on critical variance approval.

The COO is NOT a workflow approver — the variance approval process
officially ends at HOD Finance. The COO is notified by email as soon
as a critical variance hits the Approved state so the executive team
has zero-latency visibility without being in the approval critical path.

Trigger: `on_update` of a POS Closing Shift, when the workflow_state
transitions to "Approved" AND the variance_severity is "critical".

Idempotent via `coo_notified_at` field. Brevo failures are logged but
never block the closing-shift save.
"""

from __future__ import annotations

import frappe  # type: ignore
from frappe.utils import now_datetime

from sungas.utils.brevo import send_transactional_email


# Configurable role used to resolve COO recipients. Kept in code for now;
# move to Sungas Close Policy if multiple roles ever need to be notified.
COO_ROLE = "LPG Chief Operating Officer"


def notify_coo_on_critical_approval(doc, method=None) -> None:
    """Send the informational COO email exactly once per shift."""
    if doc.get("workflow_state") != "Approved":
        return
    if doc.get("variance_severity") != "critical":
        return
    if doc.get("coo_notified_at"):
        return  # already sent

    # Detect that THIS save is the transition into Approved (not just a
    # re-save of a previously-Approved doc). On is_new() there's no prior
    # state, but a brand-new doc can't be Approved anyway.
    before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
    old_state = (before.get("workflow_state") if before else None) or ""
    if old_state == "Approved":
        return  # idempotent guard for cosmetic re-saves

    recipients = _coo_recipients()
    if not recipients:
        frappe.log_error(
            f"notify_coo_on_critical_approval: no users hold role '{COO_ROLE}' — "
            f"skipping for {doc.name}",
            "Sungas COO notification",
        )
        # Still mark as notified to prevent retries on misconfigured sites.
        _mark_notified(doc.name)
        return

    subject, html = _render(doc)
    result = send_transactional_email(
        to=recipients,
        subject=subject,
        html_content=html,
        tags=["sungas-coo-notification", "critical-variance"],
    )
    _mark_notified(doc.name)

    if not result["ok"]:
        frappe.log_error(
            f"notify_coo_on_critical_approval: Brevo failed for {doc.name}: "
            f"{result.get('error')}",
            "Sungas COO notification",
        )


def _coo_recipients() -> list[dict[str, str]]:
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name AS email, u.full_name
        FROM `tabUser` u
        INNER JOIN `tabHas Role` r ON r.parent = u.name
        WHERE u.enabled = 1
          AND r.role = %(role)s
          AND u.name NOT IN ('Administrator', 'Guest')
        """,
        {"role": COO_ROLE},
        as_dict=True,
    )
    return [
        {"email": r["email"], "name": r["full_name"] or r["email"]}
        for r in rows
        if r["email"]
    ]


def _mark_notified(shift_name: str) -> None:
    frappe.db.set_value(
        "POS Closing Shift",
        shift_name,
        "coo_notified_at",
        now_datetime(),
        update_modified=False,
    )


def _render(doc) -> tuple[str, str]:
    site_url = frappe.utils.get_url()
    shift_url = f"{site_url}/app/pos-closing-shift/{doc.name}"
    variance_amount = float(doc.get("variance_amount") or 0)
    approver = doc.get("variance_approved_by") or "—"

    subject = (
        f"[Sungas] Critical Variance Approved — {doc.pos_profile or 'Outlet'} "
        f"({doc.name}) — NGN {variance_amount:+,.2f}"
    )

    html = f"""
    <div style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; color:#1f2937; max-width:560px;">
      <h2 style="color:#1f2937; margin:0 0 8px 0;">Critical Variance — Approved (FYI)</h2>
      <p style="margin:0 0 16px 0;">A critical-tier POS variance has completed
      the approval workflow and a reclassification Journal Entry has been
      posted. No action is required from your office; this notification is
      informational.</p>

      <table style="border-collapse:collapse; width:100%; margin-bottom:16px;">
        <tr><td style="padding:6px 0; color:#6b7280;">Shift</td>
            <td style="padding:6px 0;"><strong>{doc.name}</strong></td></tr>
        <tr><td style="padding:6px 0; color:#6b7280;">Outlet</td>
            <td style="padding:6px 0;">{doc.pos_profile or '—'}</td></tr>
        <tr><td style="padding:6px 0; color:#6b7280;">Variance</td>
            <td style="padding:6px 0;"><strong>NGN {variance_amount:+,.2f}</strong></td></tr>
        <tr><td style="padding:6px 0; color:#6b7280;">Approved by</td>
            <td style="padding:6px 0;">{approver}</td></tr>
      </table>

      <p style="margin:0 0 16px 0;">
        <a href="{shift_url}"
           style="background:#1f2937; color:#fff; padding:10px 18px; border-radius:6px;
                  text-decoration:none; display:inline-block;">
          Open Shift in ERPNext
        </a>
      </p>

      <p style="font-size:12px; color:#6b7280; margin:24px 0 0 0;">
        The official approval chain ends with the Head of Finance. To make
        the COO an explicit workflow approver instead, enable
        <em>require_coo_on_critical</em> on Sungas Close Policy.
      </p>
    </div>
    """.strip()

    return subject, html
