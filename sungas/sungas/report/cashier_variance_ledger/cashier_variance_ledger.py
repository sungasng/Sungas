# Copyright (c) 2026, Manqala and contributors
# For license information, please see license.txt

"""Cashier Variance Ledger — Sungas Script Report (Wave K-2).

Aggregates GL postings on the cashier-recovery account (default
`2608 Cash Suspense - Cashier Recovery`, configured on
**Sungas Close Policy**) by `party = Employee` and surfaces ageing,
frequency, and average variance per cashier.

Data sources (zero new schema — everything is already posted by D-4):

  * tabGL Entry         — debit/credit movements on the recovery account
  * tabPOS Closing Shift — for last-shift back-references
  * tabEmployee         — for full_name + user_id resolution

The report is fully driven by Sungas Close Policy so an admin can swap
the underlying GL account without code changes (e.g. you reorganise
your CoA and 2608 moves).

Filter contract::

    {
        "from_date": "2026-01-01",      # inclusive
        "to_date":   "2026-01-31",      # inclusive
        "company":   "SUNGAS COMPANY LIMITED",
        "employee":  "EMP-0042",        # optional single-cashier drilldown
        "open_only": 1                  # default 1: hide fully-recovered cashiers
    }
"""

from __future__ import annotations

from typing import Any

import frappe  # type: ignore
from frappe import _
from frappe.utils import add_days, flt, getdate, today


def execute(filters: dict[str, Any] | None = None):
    filters = _normalise_filters(filters)
    recovery_account = _recovery_account(filters["company"])

    if not recovery_account:
        return _columns(), [], _no_account_message(), None

    rows = _aggregate(filters, recovery_account)
    columns = _columns()
    chart = _chart(rows)
    return columns, rows, None, chart


# ---------------------------------------------------------------------------
# Filter normalisation
# ---------------------------------------------------------------------------

def _normalise_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    filters = filters or {}
    out = {
        "from_date": filters.get("from_date") or add_days(today(), -90),
        "to_date": filters.get("to_date") or today(),
        "company": filters.get("company") or _default_company(),
        "employee": (filters.get("employee") or "").strip() or None,
        "open_only": 1 if filters.get("open_only") in (1, "1", True, "true") else 0,
    }
    return out


def _default_company() -> str | None:
    """Best-effort default company resolution (single-company tenants only)."""
    rows = frappe.db.get_all("Company", pluck="name", limit=1)
    return rows[0] if rows else None


def _recovery_account(company: str | None) -> str | None:
    """Resolve the cashier recovery GL account via Sungas Close Policy."""
    if not company:
        return None
    if not frappe.db.exists("DocType", "Sungas Close Policy"):
        return None
    policy = frappe.get_single("Sungas Close Policy")
    return policy.get("cashier_recovery_account")


# ---------------------------------------------------------------------------
# Column schema
# ---------------------------------------------------------------------------

def _columns() -> list[dict[str, Any]]:
    return [
        {"label": _("Cashier"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 130},
        {"label": _("Cashier Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
        {"label": _("User ID"), "fieldname": "user_id", "fieldtype": "Data", "width": 180},
        {"label": _("Open Balance (NGN)"), "fieldname": "open_balance", "fieldtype": "Currency", "options": "NGN", "width": 140},
        {"label": _("# Variances (in range)"), "fieldname": "n_variances", "fieldtype": "Int", "width": 100},
        {"label": _("# Variances (last 30d)"), "fieldname": "n_variances_30d", "fieldtype": "Int", "width": 100},
        {"label": _("Avg Variance (NGN)"), "fieldname": "avg_variance", "fieldtype": "Currency", "options": "NGN", "width": 140},
        {"label": _("First Variance"), "fieldname": "first_variance_date", "fieldtype": "Date", "width": 110},
        {"label": _("Days Open"), "fieldname": "days_open", "fieldtype": "Int", "width": 90},
        {"label": _("Last Shift"), "fieldname": "last_shift", "fieldtype": "Link", "options": "POS Closing Shift", "width": 160},
    ]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _aggregate(filters: dict[str, Any], recovery_account: str) -> list[dict[str, Any]]:
    employee_filter = ""
    params = {
        "account": recovery_account,
        "from": filters["from_date"],
        "to": filters["to_date"],
        "company": filters["company"],
    }
    if filters["employee"]:
        employee_filter = " AND gl.party = %(employee)s"
        params["employee"] = filters["employee"]

    # GL movement summary per employee. Debit = pending recovery, Credit =
    # recovery received. Open balance is sum(debit) - sum(credit) on the
    # cashier recovery account.
    sql = f"""
        SELECT gl.party AS employee,
               SUM(gl.debit) - SUM(gl.credit)               AS open_balance,
               COUNT(DISTINCT gl.voucher_no)                AS n_variances,
               SUM(CASE WHEN gl.posting_date >= %(d30)s
                        THEN 1 ELSE 0 END)                  AS n_variances_30d,
               AVG(NULLIF(gl.debit, 0))                     AS avg_debit,
               MIN(gl.posting_date)                         AS first_variance_date,
               MAX(gl.posting_date)                         AS last_variance_date
        FROM `tabGL Entry` gl
        WHERE gl.account = %(account)s
          AND gl.party_type = 'Employee'
          AND gl.company = %(company)s
          AND gl.posting_date BETWEEN %(from)s AND %(to)s
          AND gl.is_cancelled = 0
          {employee_filter}
        GROUP BY gl.party
        ORDER BY open_balance DESC
    """
    params["d30"] = add_days(today(), -30)
    raw = frappe.db.sql(sql, params, as_dict=True)
    if not raw:
        return []

    # Resolve employee details + last shift in batched lookups.
    emp_ids = [r["employee"] for r in raw if r.get("employee")]
    emp_meta = {
        r["name"]: r
        for r in frappe.db.get_all(
            "Employee",
            filters={"name": ["in", emp_ids]},
            fields=["name", "employee_name", "user_id"],
        )
    }
    last_shifts = _last_shift_per_user(
        [emp_meta.get(eid, {}).get("user_id") for eid in emp_ids if emp_meta.get(eid)]
    )

    rows: list[dict[str, Any]] = []
    today_date = getdate(today())
    for r in raw:
        open_bal = flt(r["open_balance"])
        if filters["open_only"] and abs(open_bal) < 0.01:
            continue
        meta = emp_meta.get(r["employee"], {})
        user_id = meta.get("user_id")
        first = getdate(r["first_variance_date"]) if r.get("first_variance_date") else None
        rows.append({
            "employee": r["employee"],
            "employee_name": meta.get("employee_name") or "",
            "user_id": user_id or "",
            "open_balance": open_bal,
            "n_variances": int(r.get("n_variances") or 0),
            "n_variances_30d": int(r.get("n_variances_30d") or 0),
            "avg_variance": flt(r.get("avg_debit") or 0),
            "first_variance_date": first,
            "days_open": (today_date - first).days if first else 0,
            "last_shift": last_shifts.get(user_id) if user_id else None,
        })
    return rows


def _last_shift_per_user(user_ids: list[str]) -> dict[str, str]:
    user_ids = [u for u in user_ids if u]
    if not user_ids:
        return {}
    rows = frappe.db.sql(
        """
        SELECT cs.user, cs.name, cs.period_end_date
        FROM `tabPOS Closing Shift` cs
        INNER JOIN (
            SELECT user, MAX(period_end_date) AS max_end
            FROM `tabPOS Closing Shift`
            WHERE user IN %(users)s AND docstatus = 1
            GROUP BY user
        ) latest
          ON latest.user = cs.user
         AND latest.max_end = cs.period_end_date
        WHERE cs.docstatus = 1
        """,
        {"users": tuple(user_ids)},
        as_dict=True,
    )
    # In case of ties on period_end_date, keep the first encountered.
    out: dict[str, str] = {}
    for r in rows:
        out.setdefault(r["user"], r["name"])
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Render a simple bar chart of the top-10 open balances."""
    if not rows:
        return None
    top = sorted(rows, key=lambda r: abs(r["open_balance"]), reverse=True)[:10]
    return {
        "data": {
            "labels": [r["employee_name"] or r["employee"] for r in top],
            "datasets": [
                {"name": "Open Balance (NGN)", "values": [flt(r["open_balance"]) for r in top]},
            ],
        },
        "type": "bar",
        "colors": ["#b91c1c"],
    }


def _no_account_message() -> str:
    return _(
        "Cashier recovery account is not configured on "
        "<b>Sungas Close Policy</b>. Set <code>cashier_recovery_account</code> "
        "and re-run the report."
    )
