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
)

# Explicit workflow list. Kept explicit rather than pattern-matched to
# avoid accidentally exporting stock ERPNext workflows into our repo.
_OWNED_WORKFLOWS = (
    "POS Closing Shift Variance",
    "Purchase Receipt Sungas",
    "LPG Price Change Request",
    "LPG Bulk Price Upload",
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
    "CFO",
    "Accounts Manager",
)

# Volatile Frappe metadata we strip before writing (match `bench export-fixtures`).
_VOLATILE_KEYS = ("owner", "modified", "creation", "modified_by",
                  "docstatus", "idx", "_user_tags", "_comments",
                  "_assign", "_liked_by")


def export_all() -> str:
    """Main entry — writes every fixture file. Returns the output dir."""
    out_dir = _out_dir()
    os.makedirs(out_dir, exist_ok=True)

    written: list[tuple[str, int]] = []
    written.append(("server_script.json", _dump_server_scripts(out_dir)))
    written.append(("workflow.json", _dump_workflows(out_dir)))
    written.append(("workflow_state.json", _dump_workflow_states(out_dir)))
    written.append(("workflow_action_master.json",
                    _dump_workflow_action_masters(out_dir)))
    written.append(("custom_field_company.json", _dump_company_custom_fields(out_dir)))
    written.append(("role.json", _dump_roles(out_dir)))
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
