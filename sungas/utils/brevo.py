"""sungas.utils.brevo
=======================

Minimal Brevo Transactional Email helper.

Reads the API key from site config (`bench set-config -g brevo_api_key ...`),
performs a single POST to the Brevo Transactional v3 endpoint, and isolates
failures so a downed Brevo service never breaks scheduled jobs.

Usage::

    from sungas.utils.brevo import send_transactional_email

    send_transactional_email(
        to=[{"email": "ops@example.com", "name": "Femi Lee"}],
        subject="Stale Shift Alert",
        html_content="<p>...</p>",
        sender={"email": "no-reply@sungas.org", "name": "Sungas ERP"},
        tags=["shift-escalation", "L1"],
    )

Returns a dict::
    {"ok": bool, "status": int | None, "message_id": str | None, "error": str | None}
"""

from __future__ import annotations

import json
from typing import Any

import frappe  # type: ignore
import requests


BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
DEFAULT_TIMEOUT = 10  # seconds — never block the worker queue


def _default_sender() -> dict[str, str]:
    """Read default sender from site config; fall back to no-reply."""
    sender_email = (
        frappe.conf.get("brevo_sender_email")
        or frappe.db.get_single_value("Email Account", "email_id")
        or "no-reply@sungas.org"
    )
    sender_name = frappe.conf.get("brevo_sender_name") or "Sungas ERP"
    return {"email": sender_email, "name": sender_name}


def send_transactional_email(
    to: list[dict[str, str]],
    subject: str,
    html_content: str,
    sender: dict[str, str] | None = None,
    tags: list[str] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a transactional email via Brevo.

    Args:
        to: list of {"email": ..., "name": ...} recipients (de-duplicated upstream).
        subject: email subject line.
        html_content: rendered HTML body.
        sender: optional sender override.
        tags: optional Brevo tags for reporting.
        params: optional Brevo template params (not used when html_content is given).

    Returns a small status dict; never raises on transport errors.
    """
    if not to:
        return {"ok": False, "status": None, "message_id": None, "error": "no_recipients"}

    api_key = frappe.conf.get("brevo_api_key")
    if not api_key:
        return {"ok": False, "status": None, "message_id": None, "error": "missing_brevo_api_key"}

    payload: dict[str, Any] = {
        "sender": sender or _default_sender(),
        "to": to,
        "subject": subject,
        "htmlContent": html_content,
    }
    if tags:
        payload["tags"] = tags
    if params:
        payload["params"] = params

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": api_key,
    }

    try:
        resp = requests.post(
            BREVO_ENDPOINT,
            headers=headers,
            data=json.dumps(payload),
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        frappe.log_error(
            f"Brevo transport error: {exc}",
            "sungas.utils.brevo",
        )
        return {"ok": False, "status": None, "message_id": None, "error": str(exc)}

    body: dict[str, Any] = {}
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {}

    if 200 <= resp.status_code < 300:
        return {
            "ok": True,
            "status": resp.status_code,
            "message_id": body.get("messageId"),
            "error": None,
        }

    frappe.log_error(
        f"Brevo {resp.status_code}: {resp.text[:1000]}",
        "sungas.utils.brevo",
    )
    return {
        "ok": False,
        "status": resp.status_code,
        "message_id": None,
        "error": body.get("message") or resp.text[:200],
    }
