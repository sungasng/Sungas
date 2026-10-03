"""sungas.utils.export_governance_fixtures
============================================

Wave HF-1 (Feb 2026) — Governance Fixture Hardening.

Dumps every governance artifact that currently lives ONLY in the
ERPNext database into JSON fixtures under ``sungas/fixtures/`` so the
next ``bench migrate`` on a fresh bench recreates them from git.

What it exports:
    * All Server Scripts whose name matches Sungas / LS / SE / MR / DLS
      prefixes (the ones we ship, not stock ones).
    * All Frappe Workflows we own (POS Closing Shift variance flow,
      Purchase Receipt Sungas flow, LPG PCR + Bulk Upload flows).
    * All Workflow States and Workflow Action Master rows referenced
      by our workflows.
    * All Custom Fields on the ``Company`` DocType (the LMD/auto-approve
      thresholds).
    * All Roles our approvers rely on.

Usage on Frappe Cloud (Bench Console or SSH):

    bench --site sungas.frappe.cloud execute \\
        sungas.utils.export_governance_fixtures.export_all

The function writes to ``sites/{site}/private/files/sungas_fixtures/``.
Zip that folder, download it via Files, and hand the ZIP to the agent
to inline into the git repo.

Design notes:
    * Uses ``frappe.get_doc(...).as_dict()`` with ``no_nulls=False`` so
      we round-trip cleanly.
    * Strips volatile fields (``owner``, ``modified``, ``creation``,
      ``modified_by``, ``docstatus``, ``idx``) before write, matching
      what ``bench export-fixtures`` does natively.
    * Idempotent: writes overwrite each run.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import frappe


# Naming filters for the artifacts we own. Uses Frappe LIKE-style match.
_SERVER_SCRIPT_PREFIXES = (
    "Sungas ",
    "SE ",
    "MR ",
    "LS ",
    "DLS ",
    # HF-2: Transit Loss + Inter-Outlet subsystems (previously DB-only).
    "Inter-Outlet ",
    "Outlet SE ",
    "Transit Loss ",
)

# Prefixes we own for Client Scripts too. HF-2.
_CLIENT_SCRIPT_PREFIXES = (
    "Sungas ",
    "PR ",
    "Inter-Outlet ",
    "Transit Loss ",
)

# HF-2: parent DocTypes whose custom fields we own end-to-end. We export
# Custom Fields where `dt` matches one of these so the fixture stays
# comprehensive without leaking unrelated stock ERPNext extensions.
_OWNED_CUSTOM_FIELD_PARENTS = (
    "Company",
    "Journal Entry",
    "POS Closing Shift",
    "POS Opening Shift",
    "POS Profile",
    "POS Invoice",
    "Purchase Order",
    "Purchase Receipt",
    "Stock Entry",
    "Material Request",
    "Item",
    "Customer",
    "Daily Loading Schedule",
    "Sungas Close Policy",
    "Sungas Procurement Policy",
    "Transit Loss Variance Case",
    "Inter-Outlet Variance Case",
    "Inter-Outlet Standing Agreement",
    "Customer Asset Custody",
)

# HF-2: modules that mean "ours". Used to filter dashboards / reports /
# print formats without hard-coding names.
_OWNED_MODULES = (
    "Sungas",
    "Posawesome",
)

# Explicit workflow list. Kept explicit rather than pattern-matched to
# avoid accidentally exporting stock ERPNext workflows into our repo.
_OWNED_WORKFLOWS = (
    "POS Closing Shift Variance",
    "Purchase Receipt Sungas",
    "Purchase Receipt",
    "Purchase Order Sungas",
    "LPG Price Change Request",
    "LPG Bulk Price Upload",
    "Transit Loss Variance Case",
    "Inter-Outlet Variance Case",
    "Material Request Sungas",
    "Daily Loading Schedule Sungas",
)

# Roles the approver chains rely on. Include everything we've provisioned;
# stock Frappe roles (System Manager, etc.) are re-exported harmlessly.
_OWNED_ROLES = (
    "LPG POS User",
    "LPG Plant Manager",
    "LPG Head of Operations",
    "LPG Head of Finance",
    "LPG Head of Sales",
    "LPG Chief Operating Officer",
    "Chief Operating Officer",
    "CFO",
    "Central Procurement Lead",
    "Accounts Manager",
    "Purchase Manager",
    "Stock User",
    "Sales User",
)

# Volatile Frappe metadata we strip before writing (match `bench export-fixtures`).
_VOLATILE_KEYS = ("owner", "modified", "creation", "modified_by",
                  "docstatus", "idx", "_user_tags", "_comments",
                  "_assign", "_liked_by")


def export_all(out_dir: str | None = None) -> str:
    """Main entry — writes every fixture file. Returns the output dir.

    Patch 0013 (B): accepts an optional out_dir so the daily fixture-
    drift audit can dump into a tmp folder for comparison without
    overwriting the git-tracked fixtures.
    """
    if out_dir is None:
        out_dir = _out_dir()
    os.makedirs(out_dir, exist_ok=True)

    written: list[tuple[str, int]] = []
    # HF-1
    written.append(("server_script.json", _dump_server_scripts(out_dir)))
    written.append(("workflow.json", _dump_workflows(out_dir)))
    written.append(("workflow_state.json", _dump_workflow_states(out_dir)))
    written.append(("workflow_action_master.json",
                    _dump_workflow_action_masters(out_dir)))
    written.append(("custom_field_company.json", _dump_company_custom_fields(out_dir)))
    written.append(("role.json", _dump_roles(out_dir)))
    # HF-2 (new)
    written.append(("custom_field_owned.json",
                    _dump_owned_custom_fields(out_dir)))
    written.append(("custom_docperm.json",
                    _dump_owned_custom_docperms(out_dir)))
    written.append(("client_script.json", _dump_client_scripts(out_dir)))
    written.append(("property_setter.json", _dump_property_setters(out_dir)))
    written.append(("dashboard.json", _dump_dashboards(out_dir)))
    written.append(("dashboard_chart.json", _dump_dashboard_charts(out_dir)))
    written.append(("number_card.json", _dump_number_cards(out_dir)))
    written.append(("report.json", _dump_reports(out_dir)))
    written.append(("print_format.json", _dump_print_formats(out_dir)))
    written.append(("notification.json", _dump_notifications(out_dir)))
    _write_manifest(out_dir, written)

    frappe.msgprint(
        "Sungas governance fixtures exported to:<br>"
        f"<code>{out_dir}</code><br><br>"
        + "<br>".join(f"<b>{name}</b>: {count} record(s)" for name, count in written)
    )
    return out_dir


# --------------------------------------------------------------------------- #
# Individual dumpers
# --------------------------------------------------------------------------- #

def _dump_server_scripts(out_dir: str) -> int:
    or_filters = [["name", "like", f"{p}%"] for p in _SERVER_SCRIPT_PREFIXES]
    names = frappe.get_all("Server Script", or_filters=or_filters, pluck="name")
    docs = [_clean(frappe.get_doc("Server Script", n).as_dict()) for n in names]
    _write(out_dir, "server_script.json", docs)
    return len(docs)


def _dump_workflows(out_dir: str) -> int:
    docs = []
    for wf_name in _OWNED_WORKFLOWS:
        if not frappe.db.exists("Workflow", wf_name):
            continue
        docs.append(_clean(frappe.get_doc("Workflow", wf_name).as_dict()))
    _write(out_dir, "workflow.json", docs)
    return len(docs)


def _dump_workflow_states(out_dir: str) -> int:
    """Only export states referenced by our owned workflows."""
    needed_states: set[str] = set()
    for wf_name in _OWNED_WORKFLOWS:
        if not frappe.db.exists("Workflow", wf_name):
            continue
        wf = frappe.get_doc("Workflow", wf_name)
        for row in (wf.get("states") or []):
            needed_states.add(row.state)

    docs = []
    for state_name in sorted(needed_states):
        if frappe.db.exists("Workflow State", state_name):
            docs.append(_clean(
                frappe.get_doc("Workflow State", state_name).as_dict()
            ))
    _write(out_dir, "workflow_state.json", docs)
    return len(docs)


def _dump_workflow_action_masters(out_dir: str) -> int:
    """Only export actions referenced by our owned workflows."""
    needed_actions: set[str] = set()
    for wf_name in _OWNED_WORKFLOWS:
        if not frappe.db.exists("Workflow", wf_name):
            continue
        wf = frappe.get_doc("Workflow", wf_name)
        for row in (wf.get("transitions") or []):
            needed_actions.add(row.action)

    docs = []
    for action_name in sorted(needed_actions):
        if frappe.db.exists("Workflow Action Master", action_name):
            docs.append(_clean(
                frappe.get_doc("Workflow Action Master", action_name).as_dict()
            ))
    _write(out_dir, "workflow_action_master.json", docs)
    return len(docs)


def _dump_company_custom_fields(out_dir: str) -> int:
    """Export the Company custom fields that carry the LMD thresholds/SLAs."""
    names = frappe.get_all(
        "Custom Field",
        filters={"dt": "Company"},
        pluck="name",
    )
    docs = [_clean(frappe.get_doc("Custom Field", n).as_dict()) for n in names]
    _write(out_dir, "custom_field_company.json", docs)
    return len(docs)


def _dump_roles(out_dir: str) -> int:
    docs = []
    for role_name in _OWNED_ROLES:
        if frappe.db.exists("Role", role_name):
            docs.append(_clean(frappe.get_doc("Role", role_name).as_dict()))
    _write(out_dir, "role.json", docs)
    return len(docs)


# --------------------------------------------------------------------------- #
# HF-2 dumpers -- expand coverage to Custom Fields on owned parent doctypes,
# Client Scripts, Property Setters, Dashboards, Dashboard Charts, Number
# Cards, Reports, Print Formats and Notifications owned by us.
# --------------------------------------------------------------------------- #

def _dump_owned_custom_fields(out_dir: str) -> int:
    """Custom Fields on every parent DocType we own end-to-end."""
    names = frappe.get_all(
        "Custom Field",
        filters={"dt": ["in", list(_OWNED_CUSTOM_FIELD_PARENTS)]},
        pluck="name",
    )
    docs = [_clean(frappe.get_doc("Custom Field", n).as_dict()) for n in names]
    _write(out_dir, "custom_field_owned.json", docs)
    return len(docs)


def _dump_owned_custom_docperms(out_dir: str) -> int:
    """Custom DocPerms on every parent DocType we own end-to-end.

    Patch 0011: previously PR docperms lived in DB only; the last
    fixture-sync wiped them silently. Now every DocPerm we grant to
    Sungas-owned roles on our owned doctypes is git-tracked.
    """
    names = frappe.get_all(
        "Custom DocPerm",
        filters={"parent": ["in", list(_OWNED_CUSTOM_FIELD_PARENTS)]},
        pluck="name",
    )
    docs = [_clean(frappe.get_doc("Custom DocPerm", n).as_dict()) for n in names]
    _write(out_dir, "custom_docperm.json", docs)
    return len(docs)


def _dump_client_scripts(out_dir: str) -> int:
    or_filters = [["name", "like", f"{p}%"] for p in _CLIENT_SCRIPT_PREFIXES]
    if not frappe.db.exists("DocType", "Client Script"):
        _write(out_dir, "client_script.json", [])
        return 0
    names = frappe.get_all("Client Script", or_filters=or_filters, pluck="name")
    docs = [_clean(frappe.get_doc("Client Script", n).as_dict()) for n in names]
    _write(out_dir, "client_script.json", docs)
    return len(docs)


def _dump_property_setters(out_dir: str) -> int:
    """Property Setters whose parent DocType is one we own."""
    names = frappe.get_all(
        "Property Setter",
        filters={"doc_type": ["in", list(_OWNED_CUSTOM_FIELD_PARENTS)]},
        pluck="name",
    )
    docs = [_clean(frappe.get_doc("Property Setter", n).as_dict()) for n in names]
    _write(out_dir, "property_setter.json", docs)
    return len(docs)


def _dump_dashboards(out_dir: str) -> int:
    names = frappe.get_all(
        "Dashboard",
        filters={"module": ["in", list(_OWNED_MODULES)]},
        pluck="name",
    )
    docs = [_clean(frappe.get_doc("Dashboard", n).as_dict()) for n in names]
    _write(out_dir, "dashboard.json", docs)
    return len(docs)


def _dump_dashboard_charts(out_dir: str) -> int:
    names = frappe.get_all(
        "Dashboard Chart",
        filters={"module": ["in", list(_OWNED_MODULES)]},
        pluck="name",
    )
    docs = [_clean(frappe.get_doc("Dashboard Chart", n).as_dict()) for n in names]
    _write(out_dir, "dashboard_chart.json", docs)
    return len(docs)


def _dump_number_cards(out_dir: str) -> int:
    names = frappe.get_all(
        "Number Card",
        filters={"module": ["in", list(_OWNED_MODULES)]},
        pluck="name",
    )
    docs = [_clean(frappe.get_doc("Number Card", n).as_dict()) for n in names]
    _write(out_dir, "number_card.json", docs)
    return len(docs)


def _dump_reports(out_dir: str) -> int:
    """Non-standard reports (custom Query / Script / Report Builder) in our modules."""
    names = frappe.get_all(
        "Report",
        filters={
            "is_standard": "No",
            "module": ["in", list(_OWNED_MODULES)],
        },
        pluck="name",
    )
    docs = [_clean(frappe.get_doc("Report", n).as_dict()) for n in names]
    _write(out_dir, "report.json", docs)
    return len(docs)


def _dump_print_formats(out_dir: str) -> int:
    """Non-standard print formats in our modules."""
    names = frappe.get_all(
        "Print Format",
        filters={
            "standard": "No",
            "module": ["in", list(_OWNED_MODULES)],
        },
        pluck="name",
    )
    docs = [_clean(frappe.get_doc("Print Format", n).as_dict()) for n in names]
    _write(out_dir, "print_format.json", docs)
    return len(docs)


def _dump_notifications(out_dir: str) -> int:
    names = frappe.get_all(
        "Notification",
        filters={"module": ["in", list(_OWNED_MODULES)]},
        pluck="name",
    )
    docs = [_clean(frappe.get_doc("Notification", n).as_dict()) for n in names]
    _write(out_dir, "notification.json", docs)
    return len(docs)


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #

def _out_dir() -> str:
    return os.path.join(
        frappe.get_site_path("private", "files"),
        "sungas_fixtures",
    )


def _clean(d: dict) -> dict:
    """Strip volatile Frappe metadata + recurse into child tables."""
    for k in _VOLATILE_KEYS:
        d.pop(k, None)
    for key, val in list(d.items()):
        if isinstance(val, list):
            d[key] = [
                _clean(row) if isinstance(row, dict) else row for row in val
            ]
    return d


def _write(out_dir: str, filename: str, docs: list[dict]) -> None:
    path = os.path.join(out_dir, filename)
    with open(path, "w") as f:
        json.dump(docs, f, indent=2, default=str, sort_keys=True)


def _write_manifest(out_dir: str, written: list[tuple[str, int]]) -> None:
    manifest = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "site": frappe.local.site,
        "sungas_version": frappe.get_attr("sungas.__version__")
        if frappe.db.exists("Module Def", "Sungas") else None,
        "files": [{"name": n, "record_count": c} for n, c in written],
    }
    with open(os.path.join(out_dir, "_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, default=str)
