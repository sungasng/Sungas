"""Patch 0015d -- one-time backfill of qty_received/qty_variance on Draft IOVCs.

For any Draft IOVC whose outgoing_stock_entry has >= 1 submitted sibling,
recompute qty_received as the SUM of all submitted sibling receipt qtys
and update qty_variance accordingly. Idempotent.

Usage:
    $ bench --site <site> console
    >>> from sungas.console.backfill_iovc_qty_0015d import backfill
    >>> backfill(dry_run=True)
    >>> backfill(dry_run=False)
"""
from __future__ import annotations

import frappe  # type: ignore


def backfill(dry_run: bool = True) -> dict:
    cases = frappe.get_all(
        "Inter-Outlet Variance Case",
        filters={"docstatus": 0},
        fields=["name", "dispatch_entry", "receipt_entry", "qty_dispatched",
                "qty_received", "qty_variance", "value_variance", "variance_pct"],
    )
    report = {"total": len(cases), "updates": [], "dry_run": dry_run}

    for c in cases:
        if not c["dispatch_entry"]:
            continue
        rows = frappe.get_all(
            "Stock Entry",
            filters={"outgoing_stock_entry": c["dispatch_entry"], "docstatus": 1},
            pluck="name",
        )
        if not rows:
            continue
        total_recv = 0.0
        for name in rows:
            for r in frappe.get_all(
                "Stock Entry Detail",
                filters={"parent": name},
                fields=["qty"],
            ):
                total_recv += (r.get("qty") or 0.0)

        new_variance = (c["qty_dispatched"] or 0.0) - total_recv
        if (c["qty_received"] or 0.0) == total_recv:
            continue  # idempotent

        report["updates"].append({
            "case": c["name"],
            "qty_received_old": c["qty_received"],
            "qty_received_new": total_recv,
            "qty_variance_old": c["qty_variance"],
            "qty_variance_new": new_variance,
        })
        if not dry_run:
            frappe.db.set_value(
                "Inter-Outlet Variance Case",
                c["name"],
                {
                    "qty_received": total_recv,
                    "qty_variance": new_variance,
                },
                update_modified=False,
            )

    if not dry_run:
        frappe.db.commit()
    return report
