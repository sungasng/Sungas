"""Patch 0015d -- 3 fixes on top of Patch 0015a+b+c.

User-reported issues (2026-02-28):
  1. Sign-off fields (`hod_ops_signed_by`, `hod_ops_signed_on`, etc.) are
     being manually typed by operators (femi.lee typed in her own email).
     Must be auto-populated by the system on workflow transitions.
  2. Sign-off chain + resolution fields are editable by everyone -- should
     be read-only (sign-offs auto-stamped, resolution gated by state).
  3. Multi-drop IOVC `1k1ric518e` shows `Qty Received = 2200` (Pedro only),
     ignoring Bolade's `1800` discharged on the same outgoing SE
     MAT-STE-2026-00172. Variance = 2800 instead of correct 1000.

Fixes:
  A. Rewrite the qty_recv calculation in `Inter-Outlet Open Variance Case
     on Receipt` to use the already-summed `received` dict (whole-trip view).
  B. Property Setters making all `*_signed_by`, `*_signed_on` fields
     read-only. Resolution + redelivery_destination + culpable_employee
     fields gated by workflow_state (`read_only_depends_on`).
  C. New Server Script `IOVC Workflow Auto-Stamp Sign-Offs` (on_update)
     that auto-stamps hod_ops_signed_by + hod_ops_signed_on when the
     workflow_state transitions into 'Under Investigation'. Idempotent.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "sungas" / "fixtures"


# ---------------------------------------------------------------------------
# A. Fix qty_received to use whole-trip sum (sibling-aware)
# ---------------------------------------------------------------------------
OLD_BLOCK = (
    "        # 3) Open Draft variance case\n"
    "        qty_disp = 0\n"
    "        qty_recv = 0\n"
    "        for r in (outgoing_doc.items or []):\n"
    "            qty_disp = qty_disp + (r.qty or 0)\n"
    "        for r in (doc.items or []):\n"
    "            qty_recv = qty_recv + (r.qty or 0)\n"
)

NEW_BLOCK = (
    "        # 3) Open Draft variance case\n"
    "        # Patch 0015d -- qty_recv must reflect WHOLE trip (Pedro + Bolade\n"
    "        # on multi-drop), not just this leg. The `received` dict above\n"
    "        # already sums every submitted sibling receipt, so reuse it.\n"
    "        qty_disp = 0\n"
    "        for r in (outgoing_doc.items or []):\n"
    "            qty_disp = qty_disp + (r.qty or 0)\n"
    "        qty_recv = 0\n"
    "        for code in received:\n"
    "            qty_recv = qty_recv + (received[code] or 0)\n"
)


# ---------------------------------------------------------------------------
# B. Property Setters -- lock sign-off + resolution fields
# ---------------------------------------------------------------------------
def _ps(doc_type: str, field: str, property_: str, value, pt="Check"):
    return {
        "doc_type": doc_type,
        "doctype": "Property Setter",
        "doctype_or_field": "DocField",
        "field_name": field,
        "is_system_generated": 0,
        "module": None,
        "name": f"{doc_type}-{field}-{property_}",
        "property": property_,
        "property_type": pt,
        "value": str(value) if pt == "Check" else value,
    }


READ_ONLY_FIELDS = [
    "receiver_signed_by", "receiver_signed_on",
    "hod_ops_signed_by", "hod_ops_signed_on",
    "hod_finance_signed_by", "hod_finance_signed_on",
    "clearing_cancelled", "operational_resolution_se",
    "hof_remarks",
]

# Fields that are only editable while the case is in Draft or Under Investigation
STATE_GATED_FIELDS = [
    "resolution",
    "redelivery_destination",
    "culpable_employee",
]
STATE_GATE_CONDITION = (
    "eval:doc.workflow_state && !['Draft','Under Investigation'].includes(doc.workflow_state)"
)

NEW_PROPERTY_SETTERS = []
for f in READ_ONLY_FIELDS:
    NEW_PROPERTY_SETTERS.append(
        _ps("Inter-Outlet Variance Case", f, "read_only", 1, pt="Check")
    )
for f in STATE_GATED_FIELDS:
    NEW_PROPERTY_SETTERS.append(
        _ps("Inter-Outlet Variance Case", f, "read_only_depends_on",
            STATE_GATE_CONDITION, pt="Code")
    )


# ---------------------------------------------------------------------------
# C. NEW Server Script -- auto-stamp sign-offs on workflow transitions
# ---------------------------------------------------------------------------
AUTO_STAMP_SCRIPT = {
    "allow_guest": 0,
    "api_method": None,
    "cron_format": None,
    "disabled": 0,
    "doctype": "Server Script",
    "doctype_event": "Before Save",
    "enable_rate_limit": 0,
    "event_frequency": "All",
    "module": None,
    "name": "IOVC Workflow Auto-Stamp Sign-Offs",
    "rate_limit_count": 5,
    "rate_limit_seconds": 86400,
    "reference_doctype": "Inter-Outlet Variance Case",
    "script": (
        "# Patch 0015d -- auto-stamp HoD Ops sign-off on workflow transition\n"
        "# into 'Under Investigation'. Idempotent: never overwrites a stamp\n"
        "# already set. Also prevents operators from manually mis-typing the\n"
        "# sign-off field (which is now read-only via Property Setter).\n"
        "#\n"
        "# HoF stamp is NOT handled here -- the client-side 'Approve Write-Off\n"
        "# as HoF' button in client_script.json already stamps it via the\n"
        "# whitelisted governance API endpoint. Receiver stamp intentionally\n"
        "# NOT auto-populated here -- the receiving outlet already identifies\n"
        "# itself via the dispatch linkage, and auto-stamping on first save\n"
        "# would conflate the SE submitter with the variance receiver.\n"
        "if doc.get('workflow_state') == 'Under Investigation':\n"
        "    if not (doc.get('hod_ops_signed_by') or '').strip():\n"
        "        doc.hod_ops_signed_by = frappe.session.user\n"
        "    if not doc.get('hod_ops_signed_on'):\n"
        "        doc.hod_ops_signed_on = frappe.utils.now_datetime()\n"
    ),
    "script_type": "DocType Event",
}


# ---------------------------------------------------------------------------
# D. Backfill helper for pre-existing cases (one-time, operator-run)
# ---------------------------------------------------------------------------
BACKFILL_HELPER = '''"""Patch 0015d -- one-time backfill of qty_received/qty_variance on Draft IOVCs.

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
'''


def main() -> None:
    # A. Fix qty_received computation in server script
    ss_path = FIXTURES / "server_script.json"
    ss = json.loads(ss_path.read_text())
    patched = False
    for e in ss:
        if e.get("name") == "Inter-Outlet Open Variance Case on Receipt":
            if "Patch 0015d" in e["script"]:
                patched = True
                break
            if OLD_BLOCK not in e["script"]:
                raise SystemExit("ERROR: qty_recv anchor missing")
            e["script"] = e["script"].replace(OLD_BLOCK, NEW_BLOCK, 1)
            patched = True
            break
    if not patched:
        raise SystemExit("ERROR: Inter-Outlet Open Variance Case on Receipt not found")

    # C. Add auto-stamp script
    ss = [e for e in ss if e.get("name") != AUTO_STAMP_SCRIPT["name"]]
    ss.append(AUTO_STAMP_SCRIPT)
    ss_path.write_text(json.dumps(ss, indent=1) + "\n")
    print(f"[1/3] server_script.json -- patched qty_recv + added {AUTO_STAMP_SCRIPT['name']}")

    # B. Property Setters
    ps_path = FIXTURES / "property_setter.json"
    ps = json.loads(ps_path.read_text())
    new_names = {p["name"] for p in NEW_PROPERTY_SETTERS}
    ps = [p for p in ps if p.get("name") not in new_names]
    ps.extend(NEW_PROPERTY_SETTERS)
    ps_path.write_text(json.dumps(ps, indent=1) + "\n")
    print(f"[2/3] property_setter.json -- +{len(NEW_PROPERTY_SETTERS)} IOVC field locks")

    # D. Backfill helper
    helper = ROOT / "sungas" / "console" / "backfill_iovc_qty_0015d.py"
    helper.write_text(BACKFILL_HELPER)
    print(f"[3/3] console/backfill_iovc_qty_0015d.py -- backfill helper")

    print("[Patch 0015d] fixtures updated OK")


if __name__ == "__main__":
    main()
