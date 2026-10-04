"""sungas.utils.verify_governance_fixtures
============================================

Wave HF-1b (Feb 2026) -- Governance Fixture Verifier.

Runs at the end of every ``bench migrate`` (wired via ``after_migrate``
in hooks.py). Never throws -- just checks that each critical
governance artifact we shipped as a fixture is now present in the DB,
and writes an ``Error Log`` entry (which surfaces in the ERPNext bell)
if anything is missing.

Rationale: fixture sync in Frappe silently ignores rows it can't
resolve (e.g. Server Script rows referencing DocTypes that don't
exist yet, workflow states typo'd against the workflow definition).
This verifier is the tripwire that catches those failures immediately
instead of after a production incident.
"""

from __future__ import annotations

import frappe


# --------------------------------------------------------------------------- #
# What "must exist" after a healthy migrate. Kept in sync with hooks.py
# fixtures = [...] block by hand -- deliberately duplicated so this
# verifier is a genuine second opinion, not a tautology.
# --------------------------------------------------------------------------- #

REQUIRED_SERVER_SCRIPTS = (
    # POS variance workflow
    "Sungas POS Close · variance_amount Backfill",
    "Sungas POS Close · Block-Tier Auto-Route",
    # Customer guards
    "Sungas - Block Customer Edits By Cashier",
    "Sungas - Force Retail Group On Customer Insert",
    # Stock Entry pack
    "Sungas SE — Material Receipt Guard",
    "Sungas SE — Auto Accounting Dimensions",
    "Sungas SE — Row-Level Permission (PM outlet scope)",
    "SE Inter-Outlet SoD Guard",
    "SE Inter-Outlet SoD Guard V2",
    "SE Single-Drop Spawn",
    "SE Multi-Drop Spawn",
    "SE Sync PR Discharge Totals",
    "SE Sync PR Discharge Totals On Cancel",
    # Material Request pack
    "MR Auto-Approve Rules",
    "MR Attach To Loading Schedule",
    "Sungas MR — Auto Status On Receipt",
    "Sungas MR — Share With Source PM",
    "Sungas MR — Auto Accounting Dimensions",
    "Sungas MR — Row-Level Permission (PM outlet scope)",
    # Daily Loading Schedule pack
    "Sungas DLS — Drop Integrity Guard",
    "Sungas DLS — Row-Level Permission (PM outlet scope)",
    "DLS Dispatch → Outward SE Spawn",
    "LS Capacity Check",
    "LS Truck-Return Guard",
    # HF-2: Transit Loss subsystem
    "Outlet SE Open Transit Loss Case",
    "Transit Loss Case Resolve",
    # HF-2: Inter-Outlet Variance subsystem
    "Inter-Outlet Open Variance Case on Receipt",
    "Inter-Outlet Variance Case Resolve",
    "Inter-Outlet Variance Enforce",
    "Inter-Outlet Auto-Receipt and Notify",
    "Inter-Outlet Clear COGS Expense",
    # Patch 0014b: Posting-Time Collision Guard
    "SE Transit Posting-Time Collision Guard",
)

REQUIRED_WORKFLOWS = (
    "POS Closing Shift Variance",
    "Sungas Purchase Receipt Approval",
)

REQUIRED_WORKFLOW_STATES = (
    "Draft",
    "Pending Plant Manager",
    "Pending HOD Operations",
    "Pending HOD Finance",
    "Pending COO",
    "Approved",
    "Rejected",
    "HoO Approved",
    "Submitted",
)

REQUIRED_ROLES = (
    "LPG POS User",
    "LPG Plant Manager",
    "LPG Head of Operations",
    "LPG Head of Finance",
    "LPG Head of Sales",
    "Accounts Manager",
    "Purchase Manager",
    "Sales User",
    "Stock User",
)

REQUIRED_COMPANY_FIELDS = (
    "auto_approve_bulk_kg",
    "escalation_after_minutes",
    "emergency_override_monthly_cap_per_pm",
    "cutoff_preliminary_hour",
    "cutoff_hard_hour",
    "truck_roll_hour",
    "transit_variance_threshold_pct",
)

# HF-2: additional artifact classes that must survive migrate.
REQUIRED_CLIENT_SCRIPTS = (
    "PR Variance Auto-Calc",
    "PR User Stamps on Workflow",
    "PR Weighbridge Live Preview",
    "PR Discharge Dashboard",
    "PR Get-Items Remaining Qty Hint",
    "PR Hide Close Menu",
    "Inter-Outlet Variance Auto-Calc",
    "Sungas MR — Client Enhancements",
    "Sungas SE — Material Transfer Auto-populate",
    "Sungas DLS — Drop Table Guards",
    "Sungas - Cashier Customer Restrictions",
    "PR - GIT Suppliers Cost Center Auto-populate",
    "PO Approval Matrix UI",
    "Transit Loss HoF Write-Off UI",
)

REQUIRED_DASHBOARDS = (
    "Transit Loss",
)

REQUIRED_DASHBOARD_CHARTS = (
    "Transit Loss by Hauler (90d)",
    "Transit Loss by Outlet (90d)",
    "Transit Loss by In-House Driver (90d)",
    "Transit Loss Trend (12mo)",
)

REQUIRED_NUMBER_CARDS = (
    "Transit Loss — Open Cases (90d)",
    "Transit Loss — Hauler Liable (90d)",
    "Transit Loss — Written Off (90d)",
)

REQUIRED_REPORTS = (
    "Transit Loss Recovery Aging",
)


def run() -> None:
    """Entry point wired to after_migrate. Never throws."""
    try:
        missing = _collect_missing()
        if missing:
            _report(missing)
    except Exception:
        # Even our verifier is best-effort. Don't destabilise migrate.
        frappe.log_error(
            title="verify_governance_fixtures crashed",
            message=frappe.get_traceback(),
        )


# --------------------------------------------------------------------------- #
# Existence checks
# --------------------------------------------------------------------------- #

def _collect_missing() -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}

    for cat, doctype, names in (
        ("Server Script", "Server Script", REQUIRED_SERVER_SCRIPTS),
        ("Workflow", "Workflow", REQUIRED_WORKFLOWS),
        ("Workflow State", "Workflow State", REQUIRED_WORKFLOW_STATES),
        ("Role", "Role", REQUIRED_ROLES),
        # HF-2
        ("Client Script", "Client Script", REQUIRED_CLIENT_SCRIPTS),
        ("Dashboard", "Dashboard", REQUIRED_DASHBOARDS),
        ("Dashboard Chart", "Dashboard Chart", REQUIRED_DASHBOARD_CHARTS),
        ("Number Card", "Number Card", REQUIRED_NUMBER_CARDS),
        ("Report", "Report", REQUIRED_REPORTS),
    ):
        gone = [n for n in names if not frappe.db.exists(doctype, n)]
        if gone:
            missing[cat] = gone

    gone_fields = [
        fn for fn in REQUIRED_COMPANY_FIELDS
        if not frappe.db.exists("Custom Field", {"dt": "Company", "fieldname": fn})
    ]
    if gone_fields:
        missing["Company Custom Field"] = gone_fields

    return missing


def _report(missing: dict[str, list[str]]) -> None:
    lines = ["Sungas governance fixture verifier: some artifacts are MISSING after migrate."]
    for cat, names in missing.items():
        lines.append(f"\n  {cat} ({len(names)} missing):")
        for n in names:
            lines.append(f"    - {n}")
    lines.append(
        "\nFix path: re-export from a healthy site via "
        "'sungas.utils.export_governance_fixtures.export_all', diff against "
        "sungas/fixtures/, and reconcile."
    )
    frappe.log_error(
        title="Sungas governance fixtures INCOMPLETE",
        message="\n".join(lines),
    )
