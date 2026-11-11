"""Patch 0028 -- policy change log for the heads' morning briefing.

Reads Version records (track_changes) of the Sungas policy screens from the
last 24 hours: who changed which setting, from what to what, and when.
"""
from __future__ import annotations

import json

import frappe
from frappe.utils import add_to_date, escape_html, format_datetime, now_datetime

POLICY_DOCTYPES = ("Sungas Close Policy", "Sungas Procurement Policy", "Sungas Pricing Policy",
                   "Sungas Logistics Costing Policy", "Sungas Settings")
MAX_ROWS = 25


def _labels(doctype: str) -> dict:
    return {f.fieldname: f.label for f in frappe.get_meta(doctype).fields if f.label}


def describe(data: dict, labels: dict) -> list[str]:
    """Version.data -> readable lines."""
    out = [f"{labels.get(f, f)}: {old if old not in (None, '') else '(blank)'} -> {new if new not in (None, '') else '(blank)'}"
           for f, old, new in data.get("changed") or []]
    for key, verb in (("added", "added"), ("removed", "removed"), ("row_changed", "changed")):
        rows = data.get(key) or []
        if rows:
            tables = sorted({labels.get(r[0], r[0]) for r in rows})
            out.append(f"{', '.join(tables)}: {len(rows)} row{'s' if len(rows) > 1 else ''} {verb}")
    return out


def recent_changes(hours: int = 24) -> list[dict]:
    since = add_to_date(now_datetime(), hours=-hours)
    rows = frappe.get_all("Version", filters={"ref_doctype": ["in", list(POLICY_DOCTYPES)], "creation": [">=", since]},
                          fields=["ref_doctype", "owner", "creation", "data"], order_by="creation asc")
    out, labels = [], {}
    for r in rows:
        if r.ref_doctype not in labels:
            labels[r.ref_doctype] = _labels(r.ref_doctype)
        lines = describe(json.loads(r.data or "{}"), labels[r.ref_doctype])
        if lines:
            out.append({"policy": r.ref_doctype, "user": r.owner, "at": r.creation, "lines": lines})
    return out


def section(changes: list[dict]) -> str:
    if not changes:
        return ""
    items = []
    for c in changes[:MAX_ROWS]:
        who = frappe.db.get_value("User", c["user"], "full_name") or c["user"]
        detail = "".join(f"<li>{escape_html(line)}</li>" for line in c["lines"])
        items.append(f"<li><b>{escape_html(c['policy'])}</b> - {escape_html(who)}, "
                     f"{format_datetime(c['at'], 'dd MMM HH:mm')}<ul>{detail}</ul></li>")
    more = f"<p>... and {len(changes) - MAX_ROWS} more.</p>" if len(changes) > MAX_ROWS else ""
    return f"<h4>Policy changes in the last 24 hours ({len(changes)})</h4><ul>{''.join(items)}</ul>{more}"
