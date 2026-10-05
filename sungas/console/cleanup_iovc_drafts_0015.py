"""Patch 0015 -- one-time cleanup for the 3 Draft IOVCs that pre-date the
Return-to-Source resolution path.

Usage (run via bench console on the Frappe Cloud site):

    $ bench --site <site> console
    >>> from sungas.console.cleanup_iovc_drafts_0015 import cleanup
    >>> cleanup(dry_run=True)   # inspect first
    >>> cleanup(dry_run=False)  # commit

What it does for each Draft IOVC:
  1. Cancels the auto-generated clearing Material Issue (restores GIT balance)
  2. Sets `clearing_cancelled = 1`
  3. Stamps an audit Comment on the case
  4. Leaves resolution untouched -- operator still has to pick
     Return to Source / Redeliver / Hold and sign off as HoD Ops.

Does NOT auto-submit cases. Does NOT create return SEs. Operator-driven
by design so the physical reality (gas still in truck? already returned?
driven elsewhere?) is captured accurately.

Safe to re-run: idempotent on `clearing_cancelled` flag.
"""
from __future__ import annotations

import frappe  # type: ignore


def cleanup(dry_run: bool = True) -> dict:
    """Return a report dict with per-case actions."""
    cases = frappe.get_all(
        "Inter-Outlet Variance Case",
        filters={"docstatus": 0},
        fields=["name", "clearing_stock_entry", "clearing_cancelled",
                "resolution", "qty_variance", "value_variance",
                "destination_warehouse", "source_warehouse"],
    )
    report = {"total_drafts": len(cases), "actions": [], "dry_run": dry_run}

    for c in cases:
        entry = {
            "case": c["name"],
            "destination": c.get("destination_warehouse"),
            "source": c.get("source_warehouse"),
            "qty_variance": c.get("qty_variance"),
            "value_variance": c.get("value_variance"),
            "clearing_se": c.get("clearing_stock_entry"),
            "already_cancelled": bool(c.get("clearing_cancelled")),
            "steps": [],
        }

        if entry["already_cancelled"]:
            entry["steps"].append("SKIP -- already cancelled")
            report["actions"].append(entry)
            continue

        if not entry["clearing_se"]:
            entry["steps"].append("SKIP -- no clearing_stock_entry linked")
            report["actions"].append(entry)
            continue

        try:
            clearing = frappe.get_doc("Stock Entry", entry["clearing_se"])
        except frappe.DoesNotExistError:
            entry["steps"].append(f"SKIP -- clearing SE {entry['clearing_se']} missing")
            report["actions"].append(entry)
            continue

        entry["steps"].append(
            f"Would cancel clearing SE {clearing.name} "
            f"(docstatus={clearing.docstatus})"
        )

        if not dry_run:
            if clearing.docstatus == 1:
                clearing.cancel()
                entry["steps"].append(f"CANCELLED {clearing.name}")
            frappe.db.set_value(
                "Inter-Outlet Variance Case",
                c["name"],
                {"clearing_cancelled": 1},
                update_modified=False,
            )
            frappe.get_doc({
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Inter-Outlet Variance Case",
                "reference_name": c["name"],
                "content": (
                    "<b>[Patch 0015 cleanup]</b> Auto-cancelled clearing SE "
                    f"<a href='/app/stock-entry/{clearing.name}'>{clearing.name}</a> "
                    "so this case can be reclassified as "
                    "<i>Return to Source</i>, <i>Redeliver</i>, or <i>Hold in GIT</i>. "
                    "GIT balance restored. Operator must now set the correct "
                    "resolution + sign off."
                ),
            }).insert(ignore_permissions=True)
            entry["steps"].append(f"STAMPED audit comment on {c['name']}")

        report["actions"].append(entry)

    if not dry_run:
        frappe.db.commit()
    return report
